"""Pronunciation analysis: Azure provider (mock transport + a real response saved as fixture), retries,
the monthly quota, long turns, skipped states and the report.

Nothing here calls Azure: conftest blocks it, and every test uses the fixture or a scripted provider.
"""

import base64
import json
import shutil
import sqlite3
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.analysis.pronunciation import plan_assessment
from app.config import settings
from app.conversation.deps import get_pronunciation_provider, get_stt_provider, get_tts_provider
from app.llm.factory import get_llm_provider
from app.main import app
from app.pronunciation import AzurePronunciationProvider, PronunciationResult, WordScore
from app.pronunciation import azure as azure_module
from app.pronunciation.errors import (
    PronunciationAudioError,
    PronunciationAuthError,
    PronunciationNotConfiguredError,
    PronunciationProviderError,
    PronunciationRateLimitError,
)
from app.pronunciation.quota import QUOTA_SAFETY_MARGIN_SECONDS, USABLE_MONTHLY_SECONDS, month_key
from app.reports import FAIRNESS_NOTE, HARD_WORD_THRESHOLD, build_pronunciation_report
from tests.analysis_helpers import ScriptedGrammarLLM, ScriptedPronunciation, busy, run_analyses
from tests.fakes import FakeSTT, FakeTTS
from tests.test_sessions_api import _allow_audio, AUDIO, _login, _new_session, _query

FIXTURE = Path(__file__).parent / "fixtures" / "azure_pronunciation_response.json"
KEY = "test-key-not-real"


def _azure_json() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _wav(path: Path, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


def _provider(handler) -> AzurePronunciationProvider:  # type: ignore[no-untyped-def]
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AzurePronunciationProvider(SecretStr(KEY), "brazilsouth", client=client)


# --- Azure provider (simulated responses) ---------------------------------------------------------


def test_azure_response_is_parsed_into_a_provider_neutral_result(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_azure_json())

    result = _provider(handler).score_turn(str(_wav(tmp_path / "a.wav")), "I think the weather is nice today.")

    assert (result.accuracy_score, result.pron_score) == (94.0, 79.0)
    assert [w.word for w in result.words] == ["I", "think", "the", "weather", "is", "nice", "today"]
    today = result.words[-1]
    assert today.accuracy == 82.0 and today.error_type == "None"
    assert [(p.phoneme, p.accuracy) for p in today.phonemes] == [("t", 100.0), ("ax", 69.0), ("d", 73.0), ("ey", 63.0)]
    assert "".join(p.ipa or "?" for p in today.phonemes) == "tədeɪ"  # SAPI -> IPA

    request = seen[0]
    assert request.url.host == "brazilsouth.stt.speech.microsoft.com"  # built from the region, not hard-coded
    assert request.url.params["language"] == "en-US" and request.url.params["format"] == "detailed"
    assert request.headers["ocp-apim-subscription-key"] == KEY
    assert request.headers["content-type"] == "audio/wav; codecs=audio/pcm; samplerate=16000"
    assessment = json.loads(base64.b64decode(request.headers["pronunciation-assessment"]))
    assert assessment == {
        "ReferenceText": "I think the weather is nice today.",
        "GradingSystem": "HundredMark",
        "Granularity": "Phoneme",
        "Dimension": "Comprehensive",
    }


def test_scores_nested_in_a_pronunciation_assessment_object_are_read_too() -> None:
    # The docs show two layouts (REST: flat, SDK: nested); both must parse.
    body = {
        "RecognitionStatus": "Success",
        "NBest": [
            {
                "PronunciationAssessment": {"AccuracyScore": 90, "PronScore": 80},
                "Words": [{"Word": "hi", "PronunciationAssessment": {"AccuracyScore": 55, "ErrorType": "Mispronunciation"}}],
            }
        ],
    }
    result = azure_module._parse_response(httpx.Response(200, json=body))
    assert (result.accuracy_score, result.words[0].accuracy, result.words[0].error_type) == (90.0, 55.0, "Mispronunciation")


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [
        (429, PronunciationRateLimitError, "azure_busy"),
        (503, PronunciationProviderError, "azure_unavailable"),
        (401, PronunciationAuthError, "azure_auth"),
    ],
)
def test_azure_http_errors_become_typed_errors(tmp_path: Path, status: int, error: type, code: str) -> None:
    provider = _provider(lambda request: httpx.Response(status, text="nope"))

    with pytest.raises(error) as info:
        provider.score_turn(str(_wav(tmp_path / "a.wav")), "hello")

    assert info.value.code == code and KEY not in str(info.value)


def test_a_timeout_counts_as_audio_processed_but_429_does_not(tmp_path: Path) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(Exception) as timeout:  # noqa: PT011
        _provider(slow).score_turn(str(_wav(tmp_path / "a.wav")), "hello")

    assert timeout.value.audio_processed is True  # type: ignore[attr-defined]
    assert PronunciationRateLimitError.audio_processed is False


def test_missing_key_or_bad_region_is_not_configured() -> None:
    with pytest.raises(PronunciationNotConfiguredError):
        AzurePronunciationProvider(SecretStr(""), "brazilsouth")
    with pytest.raises(PronunciationNotConfiguredError):
        AzurePronunciationProvider(SecretStr(KEY), "evil.example.com/x")  # the host is never built from it


def test_a_fitting_wav_is_sent_as_is_and_other_audio_needs_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = _wav(tmp_path / "ok.wav", seconds=1.0)
    assert azure_module._prepare_audio(wav, 28.0) == wav.read_bytes()

    monkeypatch.setattr(azure_module.shutil, "which", lambda name: None)
    with pytest.raises(PronunciationAudioError) as info:
        azure_module._prepare_audio(Path(__file__).parent / "fixtures" / "sample.ogg", 28.0)
    assert info.value.code == "ffmpeg_missing"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_non_wav_audio_is_converted_to_pcm_16k_mono(tmp_path: Path) -> None:
    data = azure_module._prepare_audio(Path(__file__).parent / "fixtures" / "sample.ogg", 28.0)

    out = tmp_path / "out.wav"
    out.write_bytes(data)
    with wave.open(str(out), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)


# --- the plan: which text and how much audio -----------------------------------------------------


def test_a_short_turn_uses_the_whole_transcript() -> None:
    plan = plan_assessment("  I like   trains ", None, 3.0, 28.0)

    assert (plan.reference_text, plan.audio_seconds, plan.truncated) == ("I like trains", 3.0, False)


def test_a_long_turn_is_cut_to_the_words_that_fit_in_the_audio_limit() -> None:
    timings = [{"word": "first", "start": 0.0, "end": 10.0}, {"word": "second", "start": 10.0, "end": 27.9}, {"word": "third", "start": 28.0, "end": 40.0}]

    plan = plan_assessment("first second third", timings, 40.0, 28.0)

    assert (plan.reference_text, plan.audio_seconds, plan.truncated) == ("first second", 28.0, True)


def test_a_long_turn_without_timings_cannot_be_cut() -> None:
    assert plan_assessment("a b c", None, 40.0, 28.0) is None


# --- the runner: retries, failure, quota ----------------------------------------------------------


def _result(*scores: tuple[str, float]) -> PronunciationResult:
    words = [WordScore(word=w, accuracy=a) for w, a in scores]
    return PronunciationResult(accuracy_score=80.0, pron_score=75.0, words=words)


def _turn(
    db_path: Path, tmp_path: Path, *, transcript: str = "I think so", seconds: float = 2.5, words: str | None = None, audio: bool = True
) -> int:
    audio_path = str(_wav(tmp_path / "turn.wav")) if audio else None
    with sqlite3.connect(db_path) as conn:
        conn.execute("insert into sessions (user_id, level, topic, audio_consent, created_at) values (1, 'B1', 't', 1, current_timestamp)")
        session_id = conn.execute("select max(id) from sessions").fetchone()[0]
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path, user_audio_path,"
            " user_audio_seconds, word_timestamps) values (?, 1, ?, 'ok', 'z', ?, ?, ?)",
            (session_id, transcript, audio_path, seconds, words),
        )
    return session_id


@pytest.fixture
def seeded(client: TestClient, db_path: Path) -> Path:
    _login(client, "ana")
    return db_path


def _row(db_path: Path, dimension: str = "pronunciation") -> tuple:
    return _query(db_path, f"select status, result, error from turn_analyses where dimension = '{dimension}'")[0]


def _usage(db_path: Path) -> float:
    rows = _query(db_path, "select seconds from azure_speech_usage")
    return rows[0][0] if rows else 0.0


def test_a_scored_turn_is_stored_and_its_audio_counted(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path)
    azure = ScriptedPronunciation([_result(("I", 95.0), ("think", 40.0))])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    status, result, error = _row(seeded)
    stored = json.loads(result)
    assert (status, error) == ("done", None)
    assert [w["word"] for w in stored["words"]] == ["I", "think"] and stored["truncated"] is False
    assert azure.calls[0][1] == "I think so"  # the reference is the Whisper transcript
    assert _usage(seeded) == pytest.approx(2.5)


def test_429_and_503_are_retried_with_growing_waits_and_only_the_success_is_counted(
    seeded: Path, tmp_path: Path, backoff_waits: list[float]
) -> None:
    _turn(seeded, tmp_path)
    azure = ScriptedPronunciation([PronunciationRateLimitError("429"), PronunciationProviderError("503"), _result(("I", 90.0))])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded)[0] == "done"
    assert len(azure.calls) == 3 and backoff_waits[:2] == [2.0, 6.0]
    assert _usage(seeded) == pytest.approx(2.5)  # refused attempts did not consume quota


def test_a_definitive_failure_marks_only_pronunciation_failed(seeded: Path, tmp_path: Path, backoff_waits: list[float]) -> None:
    _turn(seeded, tmp_path)
    azure = ScriptedPronunciation(busy())

    run_analyses(seeded, ScriptedGrammarLLM(), azure)  # must not raise

    assert _row(seeded)[0] == "failed" and _row(seeded)[2] == "azure_busy" and _row(seeded)[1] is None
    assert _row(seeded, "fluency")[0] == "done"  # the session carries on
    assert backoff_waits == [2.0, 6.0, 18.0] and len(azure.calls) == 4
    assert _usage(seeded) == 0.0


def test_a_bad_key_is_not_retried(seeded: Path, tmp_path: Path, backoff_waits: list[float]) -> None:
    _turn(seeded, tmp_path)
    azure = ScriptedPronunciation([PronunciationAuthError("401")])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded)[0] == "failed" and _row(seeded)[2] == "azure_auth" and backoff_waits == [] and len(azure.calls) == 1


def test_only_one_azure_call_at_a_time_and_the_slot_is_free_afterwards(seeded: Path, tmp_path: Path) -> None:
    from app.analysis import runner

    _turn(seeded, tmp_path)
    run_analyses(seeded, ScriptedGrammarLLM(), ScriptedPronunciation(busy()))

    assert runner._AZURE_SLOT.acquire(blocking=False)
    runner._AZURE_SLOT.release()


def test_without_azure_configured_pronunciation_fails_alone(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path)

    run_analyses(seeded, ScriptedGrammarLLM(), None)

    assert _row(seeded)[0] == "failed" and _row(seeded)[2] == "not_configured"
    assert _row(seeded, "fluency")[0] == "done"


def _set_usage(db_path: Path, seconds: float) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("insert into azure_speech_usage (month, seconds) values (?, ?)", (month_key(), seconds))


def test_the_quota_stops_calls_when_the_margin_is_reached(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path, seconds=2.5)
    _set_usage(seeded, USABLE_MONTHLY_SECONDS - 2.0)  # 2.5 s more would cross the line
    azure = ScriptedPronunciation([_result(("I", 90.0))])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded) == ("skipped_quota", None, None)
    assert azure.calls == []  # Azure was not called
    assert _usage(seeded) == USABLE_MONTHLY_SECONDS - 2.0  # and nothing was added


def test_the_quota_allows_the_call_that_fits_exactly(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path, seconds=2.5)
    _set_usage(seeded, USABLE_MONTHLY_SECONDS - 2.5)
    azure = ScriptedPronunciation([_result(("I", 90.0))])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded)[0] == "done" and len(azure.calls) == 1
    assert _usage(seeded) == pytest.approx(USABLE_MONTHLY_SECONDS)


def test_the_margin_is_a_named_constant_below_the_real_free_limit() -> None:
    assert QUOTA_SAFETY_MARGIN_SECONDS > 0 and USABLE_MONTHLY_SECONDS == 5 * 3600 - QUOTA_SAFETY_MARGIN_SECONDS


def test_the_quota_counts_each_month_separately(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path)
    with sqlite3.connect(seeded) as conn:  # last month was full; this month is empty
        conn.execute("insert into azure_speech_usage (month, seconds) values ('2000-01', 99999)")
    azure = ScriptedPronunciation([_result(("I", 90.0))])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded)[0] == "done"


def test_a_turn_without_stored_audio_is_skipped_not_left_pending(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path, audio=False)
    azure = ScriptedPronunciation()

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded) == ("skipped_no_audio", None, None) and azure.calls == []


def test_silence_sends_nothing_to_azure(seeded: Path, tmp_path: Path) -> None:
    _turn(seeded, tmp_path, transcript="   ")
    azure = ScriptedPronunciation()

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert _row(seeded)[0] == "done" and json.loads(_row(seeded)[1])["words"] == [] and azure.calls == []


def test_a_long_turn_sends_only_the_words_that_fit_and_counts_only_that_audio(seeded: Path, tmp_path: Path) -> None:
    words = json.dumps([{"word": "one", "start": 0.0, "end": 20.0}, {"word": "two", "start": 20.0, "end": 27.0}, {"word": "three", "start": 29.0, "end": 45.0}])
    _turn(seeded, tmp_path, transcript="one two three", seconds=45.0, words=words)
    azure = ScriptedPronunciation([_result(("one", 90.0), ("two", 90.0))])

    run_analyses(seeded, ScriptedGrammarLLM(), azure)

    assert azure.calls[0][1] == "one two"
    assert json.loads(_row(seeded)[1])["truncated"] is True
    assert _usage(seeded) == pytest.approx(28.0)


# --- wiring in the turn endpoint -----------------------------------------------------------------


class _Tutor:
    def generate(self, prompt: str, response_model: type, *, system: str | None = None):  # type: ignore[no-untyped-def]
        if "communication" in response_model.model_fields:
            return response_model.model_validate(__import__("tests.analysis_helpers", fromlist=["x"]).DEFAULT_JUDGEMENT)
        if "errors" in response_model.model_fields:
            return response_model(errors=[])
        return response_model(reply="Nice!")


def test_a_turn_with_audio_consent_is_assessed_after_saving(client: TestClient, tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    azure = ScriptedPronunciation([_result(("I", 88.0), ("like", 70.0))])
    calls: list[str] = []
    app.dependency_overrides[get_stt_provider] = lambda: FakeSTT(calls, text="I like trains")
    app.dependency_overrides[get_tts_provider] = lambda: FakeTTS(calls)
    app.dependency_overrides[get_llm_provider] = lambda: _Tutor()
    app.dependency_overrides[get_pronunciation_provider] = lambda: azure
    _login(client, "ana")
    session_id = _new_session(client)
    _allow_audio(client)
    assert client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True}).status_code == 200

    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201

    assert _row(db_path)[0] == "done" and azure.calls[0][1] == "I like trains"


def test_a_turn_without_consent_never_reaches_azure(client: TestClient, tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    azure = ScriptedPronunciation()
    calls: list[str] = []
    app.dependency_overrides[get_stt_provider] = lambda: FakeSTT(calls)
    app.dependency_overrides[get_tts_provider] = lambda: FakeTTS(calls)
    app.dependency_overrides[get_llm_provider] = lambda: _Tutor()
    app.dependency_overrides[get_pronunciation_provider] = lambda: azure
    _login(client, "ana")
    session_id = _new_session(client)

    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201

    assert _row(db_path) == ("skipped_no_audio", None, None) and azure.calls == []


# --- the report ----------------------------------------------------------------------------------


def _done(turn_number: int, *scores: tuple[str, float], truncated: bool = False) -> tuple[int, SimpleNamespace]:
    words = [{"word": w, "accuracy": a} for w, a in scores]
    return turn_number, SimpleNamespace(status="done", result={"words": words, "truncated": truncated})


def _state(turn_number: int, status: str) -> tuple[int, SimpleNamespace]:
    return turn_number, SimpleNamespace(status=status, result=None)


def test_score_and_hard_words() -> None:
    report = build_pronunciation_report(
        [_done(1, ("I", 100.0), ("think", 50.0), ("the", 90.0)), _done(2, ("Think", 30.0), ("today", HARD_WORD_THRESHOLD))]
    )

    assert report.status == "ok" and report.score == round((100 + 50 + 90 + 30 + HARD_WORD_THRESHOLD) / 5)
    assert [(h.word, h.score, h.turn_number, h.times) for h in report.hard_words] == [("Think", 30, 2, 2)]  # 60 is not below 60
    assert FAIRNESS_NOTE in report.notes


def test_hard_words_come_with_ipa_and_the_sound_that_cost_most() -> None:
    phonemes = [{"phoneme": "t", "ipa": "t", "accuracy": 100.0}, {"phoneme": "ax", "ipa": "ə", "accuracy": 69.0}, {"phoneme": "ey", "ipa": "eɪ", "accuracy": 40.0}]
    row = SimpleNamespace(status="done", result={"words": [{"word": "today", "accuracy": 50.0, "phonemes": phonemes}], "truncated": False})

    word = build_pronunciation_report([(1, row)]).hard_words[0]

    assert word.ipa == "təeɪ" and word.weakest_sound == 2
    assert [(s.ipa, s.score) for s in word.sounds] == [("t", 100), ("ə", 69), ("eɪ", 40)]


def test_hard_words_of_old_results_without_ipa_still_work() -> None:
    old = [{"phoneme": "th", "accuracy": 30.0}]  # stored before ipa existed: the provider symbol is shown
    row = SimpleNamespace(status="done", result={"words": [{"word": "think", "accuracy": 30.0, "phonemes": old}], "truncated": False})

    assert build_pronunciation_report([(1, row)]).hard_words[0].ipa == "th"
    row.result["words"][0]["phonemes"] = []  # and results with no phonemes at all
    assert build_pronunciation_report([(1, row)]).hard_words[0].weakest_sound is None


def test_the_threshold_is_strict_and_function_words_are_not_listed() -> None:
    report = build_pronunciation_report(
        [_done(1, ("for", 20.0), ("The", 30.0), ("today", HARD_WORD_THRESHOLD - 1), ("beach", HARD_WORD_THRESHOLD), ("weather", 60.0))]
    )

    # "for" and "the" are said reduced in a sentence: not worth practising. 84 counts as hard; 85 does not.
    assert [h.word for h in report.hard_words] == ["weather", "today"]
    assert HARD_WORD_THRESHOLD == 85.0
    assert report.score == round((20 + 30 + 84 + 85 + 60) / 5)  # they still count in the score


def test_the_report_never_judges_the_accent() -> None:
    forbidden = ("acento incorrecto", "mal acento", "acento malo", "mispronounc", "pronuncias mal", "error de pronunciación", "wrong accent")
    reports = [
        build_pronunciation_report([_done(1, ("think", 20.0)), _state(2, "skipped_quota"), _state(3, "skipped_no_audio")]),
        build_pronunciation_report([_state(1, "skipped_no_audio")]),
        build_pronunciation_report([_state(1, "skipped_quota")]),
        build_pronunciation_report([_state(1, "failed")]),
    ]
    text = json.dumps([r.model_dump() for r in reports], ensure_ascii=False).lower()

    assert not any(phrase in text for phrase in forbidden)
    assert "palabras que costaron" in text or "hard_words" in text


def test_no_audio_consent_is_explained_in_the_report_not_left_pending() -> None:
    report = build_pronunciation_report([_state(1, "skipped_no_audio"), _state(2, "skipped_no_audio")])

    assert (report.status, report.reason, report.score) == ("unavailable", "no_audio_consent", None)
    assert report.turns_without_audio == 2 and "audio" in report.notes[0]


def test_quota_failure_and_pending_have_their_own_states() -> None:
    assert build_pronunciation_report([_state(1, "skipped_quota")]).reason == "quota"
    assert build_pronunciation_report([_state(1, "failed")]).reason == "failed"
    assert build_pronunciation_report([_state(1, "pending"), _done(2, ("a", 90.0))]).status == "incomplete"
    assert build_pronunciation_report([_state(1, "pending")]).status == "pending"
    assert build_pronunciation_report([(1, None)]).status == "pending"  # never queued counts as pending


def test_partial_turns_are_flagged_in_the_report() -> None:
    report = build_pronunciation_report([_done(1, ("a", 90.0), truncated=True)])

    assert report.turns_partial == 1 and any("primeros segundos" in n for n in report.notes)


def test_the_saved_old_placeholder_still_loads() -> None:
    from app.reports import SessionReport

    old = {"session_id": 1, "user_turns": 0, "grammar": {"status": "empty", "score": None, "errors": [], "turns_analyzed": 0, "turns_failed": 0},
           "fluency": {"status": "empty", "score": None, "words_per_minute": None, "long_pauses": 0, "filler_words": 0, "total_words": 0},
           "pronunciation": {"status": "pending", "score": None}}

    assert SessionReport.model_validate(old).pronunciation.status == "pending"
