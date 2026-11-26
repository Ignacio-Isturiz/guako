"""Provider router wiring: OpenAI providers (fake clients), usage persistence, the admin endpoint, a voice that
degrades to the browser's, and analyses that stay pending and are retried. No API is called.
"""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.fakes import TERMS
from app.analysis.retry import EXPIRE_AFTER, MIN_AGE_SECONDS, retry_pending_once
from app.config import settings
from app.conversation.deps import get_stt_provider, get_tts_provider
from app.llm.base import BaseLLMProvider, RawCompletion
from app.llm.errors import LLMAuthError, LLMOutputError, LLMProviderError, LLMRateLimitError, LLMTimeoutError
from app.llm.factory import get_llm_provider
from app.llm.openai_llm import OpenAIProvider
from app.llm.schemas import TutorReply
from app.main import app
from app.providers.errors import LLMExhausted, TTSExhausted
from app.providers.state import CallRecord, get_state
from app.providers.usage import flush_usage, load_baseline, prune_calls
from app.stt.errors import STTError
from app.stt.openai_stt import OpenAIWhisperSTTProvider
from tests.analysis_helpers import ScriptedGrammarLLM, run_analyses
from tests.fakes import FakeSTT, FakeTTS
from tests.test_intent import _conversation, _row
from tests.test_provider_router import StubLLM, ask, llm_chain, make_state
from tests.test_sessions_api import AUDIO, _login, _new_session, _query

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/test")


def _openai_error(cls: type, status: int, *, headers: dict | None = None, body: dict | None = None) -> Exception:
    return cls("boom", response=httpx.Response(status, headers=headers or {}, request=REQUEST), body=body)


# --- usage per call: tokens come back with the answer ---------------------------------------------------


class TokenProvider(BaseLLMProvider):
    name, model = "tokens", "tokens-model"

    def __init__(self, answers: list[str], max_retries: int = 2) -> None:
        super().__init__(max_retries=max_retries)
        self.answers = answers

    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        return RawCompletion(self.answers.pop(0), prompt_tokens=100, completion_tokens=10)


def test_generate_with_usage_sums_every_attempt_not_only_the_last() -> None:
    provider = TokenProvider(["not json", '{"reply": "hi"}'])

    reply, usage = provider.generate_with_usage("hi", TutorReply)

    assert reply.reply == "hi" and (usage.prompt_tokens, usage.completion_tokens, usage.attempts) == (200, 20, 2)


def test_an_invalid_answer_still_reports_the_tokens_it_spent() -> None:
    provider = TokenProvider(["x", "y", "z"])

    with pytest.raises(LLMOutputError) as info:
        provider.generate_with_usage("hi", TutorReply)

    assert (info.value.prompt_tokens, info.value.completion_tokens) == (300, 30)


# --- OpenAI LLM provider ----------------------------------------------------------------------------------


def _openai_llm(create) -> OpenAIProvider:  # type: ignore[no-untyped-def]
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return OpenAIProvider(SecretStr("k"), "gpt-4o-mini", temperature=0.2, timeout_seconds=5, max_retries=0, client=client)  # type: ignore[arg-type]


def _completion(text: str = '{"reply": "hello"}') -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3))


def test_openai_llm_returns_the_answer_and_its_tokens() -> None:
    seen: list[dict] = []

    def create(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs)
        return _completion()

    reply, usage = _openai_llm(create).generate_with_usage("hi", TutorReply, system="be kind")

    assert reply.reply == "hello" and (usage.prompt_tokens, usage.completion_tokens) == (12, 3)
    assert seen[0]["model"] == "gpt-4o-mini" and seen[0]["temperature"] == 0.2
    assert "be kind" in seen[0]["messages"][0]["content"]


def test_openai_reasoning_models_get_no_temperature() -> None:
    seen: list[dict] = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: seen.append(kw) or _completion())))
    provider = OpenAIProvider(SecretStr("k"), "gpt-5-mini", temperature=0.2, timeout_seconds=5, client=client)  # type: ignore[arg-type]

    provider.generate("hi", TutorReply)

    assert "temperature" not in seen[0]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_openai_error(openai.AuthenticationError, 401), LLMAuthError),
        (_openai_error(openai.PermissionDeniedError, 403), LLMAuthError),
        (_openai_error(openai.RateLimitError, 429), LLMRateLimitError),
        (openai.APITimeoutError(request=REQUEST), LLMTimeoutError),
        (_openai_error(openai.InternalServerError, 503), LLMProviderError),
    ],
)
def test_openai_errors_become_our_typed_errors(error: Exception, expected: type) -> None:
    def create(**kwargs):  # type: ignore[no-untyped-def]
        raise error

    with pytest.raises(expected):
        _openai_llm(create).generate("hi", TutorReply)


def test_openai_rate_limit_carries_the_wait_and_tells_out_of_credit_apart() -> None:
    def busy(**kwargs):  # type: ignore[no-untyped-def]
        raise _openai_error(openai.RateLimitError, 429, headers={"retry-after": "7"})

    def broke(**kwargs):  # type: ignore[no-untyped-def]
        raise _openai_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"})

    with pytest.raises(LLMRateLimitError) as slow:
        _openai_llm(busy).generate("hi", TutorReply)
    with pytest.raises(LLMRateLimitError) as no_credit:
        _openai_llm(broke).generate("hi", TutorReply)

    assert (slow.value.retry_after, slow.value.quota) == (7.0, False)
    assert no_credit.value.quota is True


def test_the_router_treats_an_openai_429_like_any_other_and_moves_on() -> None:
    def busy(**kwargs):  # type: ignore[no-untyped-def]
        raise _openai_error(openai.RateLimitError, 429)

    state = make_state()
    llm = llm_chain(state, _openai_llm(busy), StubLLM("groq"))  # type: ignore[arg-type]
    llm._router.routes[0].name = "openai"

    assert ask(llm) == "from groq"


# --- OpenAI speech to text --------------------------------------------------------------------------------


def _openai_stt(create) -> OpenAIWhisperSTTProvider:  # type: ignore[no-untyped-def]
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    return OpenAIWhisperSTTProvider(SecretStr("k"), client=client)  # type: ignore[arg-type]


def _audio(tmp_path: Path) -> str:
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFFfake")
    return str(path)


def test_openai_whisper_gives_word_timings_and_receives_the_context(tmp_path: Path) -> None:
    seen: list[dict] = []

    def create(**kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs)
        payload = {"text": " Hello there", "language": "english", "duration": 1.5, "words": [{"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "there", "start": 0.6, "end": 1.0}]}
        return SimpleNamespace(model_dump=lambda: payload)

    result = _openai_stt(create).transcribe(_audio(tmp_path), "How are you?")

    assert result.text == "Hello there" and [w.word for w in result.words] == ["Hello", "there"] and result.duration == 1.5
    assert seen[0]["model"] == "whisper-1" and seen[0]["timestamp_granularities"] == ["word", "segment"] and seen[0]["prompt"] == "How are you?"


def test_openai_whisper_errors_say_why(tmp_path: Path) -> None:
    def limited(**kwargs):  # type: ignore[no-untyped-def]
        raise _openai_error(openai.RateLimitError, 429, headers={"retry-after": "3"})

    def bad_key(**kwargs):  # type: ignore[no-untyped-def]
        raise _openai_error(openai.AuthenticationError, 401)

    with pytest.raises(STTError) as rate:
        _openai_stt(limited).transcribe(_audio(tmp_path))
    with pytest.raises(STTError) as auth:
        _openai_stt(bad_key).transcribe(_audio(tmp_path))
    with pytest.raises(STTError) as fmt:
        _openai_stt(limited).transcribe(str(tmp_path / "a.txt"))

    assert (rate.value.status_code, rate.value.retry_after) == (429, 3.0)
    assert (auth.value.status_code, auth.value.kind) == (401, "auth")
    assert fmt.value.kind == "invalid_input"


# --- usage is written to the database and read back ---------------------------------------------------------


def _maker(db_path: Path):  # type: ignore[no-untyped-def]
    return async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{db_path}"), expire_on_commit=False)


def _usage_rows(db_path: Path) -> list[tuple]:
    return _query(db_path, "select provider, capability, use, requests, rate_limited, prompt_tokens, round(cost_usd, 6) from provider_usage order by provider")


def test_the_flush_writes_the_daily_totals_and_the_call_log_and_adds_up(client: TestClient, db_path: Path) -> None:
    state = make_state(price_openai_llm_input_per_m=1000.0, price_openai_llm_output_per_m=0.0)
    maker = _maker(db_path)
    llm = llm_chain(state, StubLLM("groq", error=LLMRateLimitError("429")), StubLLM("openai", prompt_tokens=500, completion_tokens=0))
    set_call = __import__("app.providers.context", fromlist=["set_call_context"]).set_call_context
    set_call(session_id=5, turn_id=8)
    ask(llm)

    assert asyncio.run(flush_usage(maker, state)) == 2
    ask(llm)
    assert asyncio.run(flush_usage(maker, state)) == 2

    assert _usage_rows(db_path) == [("groq", "llm", "conversation", 2, 2, 0, 0.0), ("openai", "llm", "conversation", 2, 0, 1000, 1.0)]
    calls = _query(db_path, "select provider, outcome, fallback_from, session_id, turn_id from provider_calls order by id")
    assert calls[:2] == [("groq", "rate_limited", None, 5, 8), ("openai", "ok", "groq", 5, 8)]


def test_a_failed_flush_keeps_the_numbers_for_the_next_one(client: TestClient, db_path: Path) -> None:
    state = make_state()
    ask(llm_chain(state, StubLLM("groq")))

    def broken():  # type: ignore[no-untyped-def]
        raise RuntimeError("database is down")

    assert asyncio.run(flush_usage(broken, state)) == 0  # type: ignore[arg-type]
    assert asyncio.run(flush_usage(_maker(db_path), state)) == 1

    assert _usage_rows(db_path)[0][:4] == ("groq", "llm", "conversation", 1)


def test_after_a_restart_the_counters_and_the_spending_come_back_from_the_database(client: TestClient, db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        for day, provider, capability, requests, cost in (
            ("2026-11-24", "groq", "tts", 5, 0.0),
            ("2026-11-24", "openai", "tts", 3, 0.8),
            ("2026-11-02", "openai", "llm", 9, 0.2),  # earlier this month: counts for the monthly budget
            ("2026-10-30", "openai", "llm", 9, 9.0),  # last month: does not
        ):
            conn.execute(
                "insert into provider_usage (day, provider, capability, use, requests, cost_usd) values (?, ?, ?, 'conversation', ?, ?)",
                (day, provider, capability, requests, cost),
            )
    state = make_state(provider_daily_caps="groq:tts=5", paid_budget_usd=2.0)

    asyncio.run(load_baseline(_maker(db_path), state))

    assert state.cap_reached("groq", "tts") is True  # the 5 requests of today count
    assert state.budget.spent == pytest.approx(1.0) and state.budget.can_spend(0.5) is True and state.budget.can_spend(1.5) is False


def test_the_call_log_is_pruned_after_thirty_days(client: TestClient, db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        for age in (1, 40):
            created = (datetime.now(UTC) - timedelta(days=age)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "insert into provider_calls (created_at, capability, use, provider, model, outcome, latency_ms) values (?, 'llm', 'x', 'groq', 'm', 'ok', 1)",
                (created,),
            )

    asyncio.run(prune_calls(_maker(db_path)))

    assert _query(db_path, "select count(*) from provider_calls") == [(1,)]


# --- GET /api/admin/usage -----------------------------------------------------------------------------------


def test_the_admin_endpoint_is_only_for_superusers(client: TestClient, db_path: Path) -> None:
    assert client.get("/api/admin/usage").status_code == 401

    _login(client, "ana")
    assert client.get("/api/admin/usage").status_code == 403  # a normal account

    with sqlite3.connect(db_path) as conn:
        conn.execute('update "user" set is_superuser = 1 where username = ?', ("ana",))
    state = get_state()
    state.record(CallRecord("tts", "conversation", "groq", "orpheus", "ok", 120))
    state.record(CallRecord("llm", "analysis", "openai", "gpt-4o-mini", "ok", 800, usage=__import__("app.providers.types", fromlist=["Usage"]).Usage(prompt_tokens=300, completion_tokens=50), cost_usd=0.0003))

    res = client.get("/api/admin/usage")

    assert res.status_code == 200
    body = res.json()
    assert {(p["provider"], p["capability"], p["use"]) for p in body["providers"]} == {("groq", "tts", "conversation"), ("openai", "llm", "analysis")}
    assert body["totals"]["requests"] == 2 and body["totals"]["cost_usd"] == pytest.approx(0.0003)
    assert body["budget"]["status"] == "ok" and body["budget"]["limit_usd"] == settings.paid_budget_usd
    assert {"breakers", "daily_caps"} <= set(body)
    assert "api_key" not in str(body).lower() and "secret" not in str(body).lower()  # nothing sensitive in the answer


def test_registration_cannot_make_someone_an_admin(client: TestClient, db_path: Path) -> None:
    res = client.post("/api/auth/register", json={"username": "eve", "email": "eve@example.com", "password": "Passw0rd123", "is_superuser": True, **TERMS})

    assert res.status_code == 201
    assert _query(db_path, "select is_superuser from \"user\" where username = 'eve'") == [(0,)]


# --- no voice at all: the turn is saved without audio ----------------------------------------------------------


class _Tutor:
    def generate(self, prompt: str, response_model: type, *, system: str | None = None):  # type: ignore[no-untyped-def]
        if "communication" in response_model.model_fields:
            return response_model.model_validate(__import__("tests.analysis_helpers", fromlist=["x"]).DEFAULT_JUDGEMENT)
        if "errors" in response_model.model_fields:
            return response_model(errors=[])
        return response_model(reply="That sounds fun!")


def _without_voice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    app.dependency_overrides[get_stt_provider] = lambda: FakeSTT([], text="I like trains")
    app.dependency_overrides[get_tts_provider] = lambda: FakeTTS([], error=TTSExhausted("every voice is out"))
    app.dependency_overrides[get_llm_provider] = lambda: _Tutor()


def test_when_every_voice_is_out_the_turn_is_saved_without_audio(
    client: TestClient, db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_voice(monkeypatch, tmp_path)
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == 201
    body = res.json()
    assert body["reply_text"] == "That sounds fun!" and body["reply_audio_url"] is None  # the browser reads it aloud
    assert _query(db_path, "select reply_audio_path, reply_audio_seconds from turns") == [(None, 0.0)]
    assert client.get(f"/api/sessions/{session_id}/turns/1/reply-audio").status_code == 404
    assert client.get(f"/api/sessions/{session_id}/turns").json()[0]["reply_audio_url"] is None


def test_the_opening_also_degrades_to_no_audio(client: TestClient, db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _without_voice(monkeypatch, tmp_path)
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.post(f"/api/sessions/{session_id}/opening")

    assert res.status_code == 201 and res.json()["reply_audio_url"] is None and res.json()["reply_text"]


# --- analysis with nobody to ask: it stays pending and is retried ---------------------------------------------


class _DeadLLM:
    def generate(self, *args: object, **kwargs: object) -> object:
        raise LLMExhausted("every provider is out", retry_after=60)


def _retry(db_path: Path, llm: object, *, hours: float = 0.0, seconds: float = MIN_AGE_SECONDS + 1) -> int:
    now = datetime.now(UTC) + timedelta(hours=hours, seconds=seconds)
    return asyncio.run(retry_pending_once(_maker(db_path), llm, None, now=now))  # type: ignore[arg-type]


def test_an_analysis_with_every_provider_out_stays_pending_and_does_not_wait_and_retry(
    client: TestClient, db_path: Path, tmp_path: Path, backoff_waits: list[float]
) -> None:
    _login(client, "ana")
    _conversation(db_path, tmp_path)

    run_analyses(db_path, _DeadLLM())  # type: ignore[arg-type]

    assert _row(db_path, "grammar")[0] == "pending"  # not failed: nobody could answer *yet*
    assert _row(db_path, "fluency")[0] == "done"  # what needs no provider is not held back
    assert backoff_waits == []  # no 2/6/18 s of sleeping: the breakers are open


def test_the_retrier_finishes_the_pending_analysis_when_a_provider_is_back(client: TestClient, db_path: Path, tmp_path: Path) -> None:
    _login(client, "ana")
    _conversation(db_path, tmp_path)
    run_analyses(db_path, _DeadLLM())  # type: ignore[arg-type]
    llm = ScriptedGrammarLLM()
    llm.script = [{"errors": [], "intended_text": ""}]

    assert _retry(db_path, llm) == 1

    assert _row(db_path, "grammar")[0] == "done"
    assert _retry(db_path, llm) == 0  # nothing pending any more


def test_a_row_that_was_just_queued_is_left_alone(client: TestClient, db_path: Path, tmp_path: Path) -> None:
    _login(client, "ana")
    _conversation(db_path, tmp_path)
    run_analyses(db_path, _DeadLLM())  # type: ignore[arg-type]

    assert _retry(db_path, _DeadLLM(), seconds=1) == 0  # its own background task may still be running


def test_a_row_still_pending_after_a_day_is_given_up(client: TestClient, db_path: Path, tmp_path: Path) -> None:
    _login(client, "ana")
    _conversation(db_path, tmp_path)
    run_analyses(db_path, _DeadLLM())  # type: ignore[arg-type]

    _retry(db_path, _DeadLLM(), hours=EXPIRE_AFTER.total_seconds() / 3600 + 1)

    status, _, error = _row(db_path, "grammar")
    assert (status, error) == ("failed", "expired")


# --- the API process: startup and shutdown -------------------------------------------------------------------


def test_startup_checks_the_chains_restores_the_counters_and_shutdown_saves_what_is_left(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main

    started: list[str] = []
    checked: list[int] = []

    async def flusher(maker, state) -> None:  # type: ignore[no-untyped-def]
        started.append("flusher")
        await asyncio.sleep(3600)

    async def retrier(maker, get_llm, get_pronunciation) -> None:  # type: ignore[no-untyped-def]
        started.append("retrier")
        await asyncio.sleep(3600)

    monkeypatch.setattr(settings, "background_tasks_enabled", True)
    monkeypatch.setattr(main, "_check_providers", lambda: checked.append(1))
    monkeypatch.setattr(main, "run_flusher", flusher)
    monkeypatch.setattr(main, "run_retrier", retrier)
    monkeypatch.setattr(main, "async_session_maker", _maker(db_path))
    today = datetime.now(UTC).date().isoformat()
    with sqlite3.connect(db_path) as conn:  # Groq already served its 90 voices today, before this restart
        conn.execute("insert into provider_usage (day, provider, capability, use, requests) values (?, 'groq', 'tts', 'conversation', 90)", (today,))
    state = get_state()

    with TestClient(main.app):
        assert state.cap_reached("groq", "tts") is True  # restored from the database
        state.record(CallRecord("llm", "analysis", "groq", "m", "ok", 5))  # recorded just before the shutdown

    assert checked == [1] and sorted(started) == ["flusher", "retrier"]
    assert _query(db_path, "select requests from provider_usage where capability = 'llm'") == [(1,)]  # flushed on the way out


def test_with_background_tasks_off_nothing_is_started(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    called: list[str] = []
    monkeypatch.setattr(main, "_check_providers", lambda: called.append("check"))
    monkeypatch.setattr(settings, "background_tasks_enabled", False)

    with TestClient(main.app):
        pass

    assert called == []
