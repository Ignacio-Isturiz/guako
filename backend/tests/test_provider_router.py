"""The provider router: fallback on 429, circuit breaker, spending cap, daily caps, "everyone is out" and the
order read from the environment. No test calls any API: providers are stubs and the clock is faked.
"""

import logging
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings, parse_caps
from app.conversation.nodes import make_synthesize
from app.llm.base import LLMUsage
from app.llm.errors import LLMAuthError, LLMOutputError, LLMProviderError, LLMRateLimitError
from app.llm.openai_llm import OpenAIProvider
from app.llm.schemas import TutorReply
from app.providers import chains
from app.providers.context import set_call_context
from app.providers.errors import LLMExhausted, STTExhausted, TTSExhausted
from app.providers.pricing import Pricing
from app.providers.router import ProviderRouter, Route
from app.providers.routed import (
    RoutedLLM,
    RoutedSTT,
    RoutedTTS,
    classify_llm,
    classify_stt,
    classify_tts,
    llm_exhausted,
    stt_exhausted,
    tts_exhausted,
)
from app.providers.state import ProviderState
from app.providers.types import Usage
from app.stt.errors import NoSpeechError, STTError
from app.stt.schemas import TranscriptionResult
from app.tts.errors import TTSError
from tests.fakes import FakeTTS

TODAY = date(2026, 11, 24)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def cfg(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    base = {"groq_api_key": SecretStr("g"), "gemini_api_key": SecretStr("m"), "openai_api_key": SecretStr("o")}
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


def make_state(clock: Clock | None = None, day: list[date] | None = None, **overrides) -> ProviderState:  # type: ignore[no-untyped-def]
    holder = day or [TODAY]
    return ProviderState(cfg(**overrides), clock=clock or Clock(), today=lambda: holder[0])


# --- stub providers ---------------------------------------------------------------------------------


class StubLLM:
    def __init__(self, name: str, *, error: Exception | None = None, prompt_tokens: int = 100, completion_tokens: int = 20) -> None:
        self.name, self.model = name, f"{name}-model"
        self.error = error
        self.prompt_tokens, self.completion_tokens = prompt_tokens, completion_tokens
        self.calls = 0

    def generate_with_usage(self, prompt: str, response_model: type, *, system: str | None = None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.error:
            raise self.error
        return response_model(reply=f"from {self.name}"), LLMUsage(self.prompt_tokens, self.completion_tokens)


def llm_chain(state: ProviderState, *stubs: StubLLM, use: str = "conversation") -> RoutedLLM:
    routes = [Route(s.name, s) for s in stubs]
    return RoutedLLM(ProviderRouter("llm", use, routes, state, classify_llm, llm_exhausted(use)))


def ask(llm: RoutedLLM, prompt: str = "hi") -> str:
    return llm.generate(prompt, TutorReply).reply


class StubVoice(FakeTTS):
    def __init__(self, name: str, *, error: Exception | None = None, cached: set[str] | None = None) -> None:
        super().__init__([], error)
        self.name, self.voice = name, f"{name}-voice"
        self.cached = cached or set()
        self.requests = 0

    def has_cached(self, text: str) -> bool:
        return text in self.cached

    def synthesize(self, text: str, output_path: str):  # type: ignore[no-untyped-def]
        self.requests += 1
        result = super().synthesize(text, output_path)
        return result.model_copy(update={"provider": self.name, "from_cache": text in self.cached})


def tts_chain(state: ProviderState, *voices: StubVoice) -> RoutedTTS:
    routes = [Route(v.name, v) for v in voices]
    return RoutedTTS(ProviderRouter("tts", "conversation", routes, state, classify_tts, tts_exhausted))


# --- 429 moves on to the next provider --------------------------------------------------------------


def test_a_429_makes_the_router_use_the_next_provider() -> None:
    groq, openai = StubLLM("groq", error=LLMRateLimitError("429")), StubLLM("openai")

    llm = llm_chain(make_state(), groq, openai)

    assert ask(llm) == "from openai"
    assert (groq.calls, openai.calls) == (1, 1) and llm.name == "openai" and llm.used_fallback is True


def test_the_first_provider_answers_and_the_rest_are_untouched() -> None:
    groq, openai = StubLLM("groq"), StubLLM("openai")

    llm = llm_chain(make_state(), groq, openai)

    assert ask(llm) == "from groq" and openai.calls == 0 and llm.used_fallback is False


def test_the_next_call_tries_the_first_provider_again() -> None:
    groq, openai = StubLLM("groq", error=LLMProviderError("503")), StubLLM("openai")
    llm = llm_chain(make_state(), groq, openai)
    ask(llm)

    groq.error = None

    assert ask(llm) == "from groq" and groq.calls == 2


def test_every_call_is_counted_per_provider_with_its_tokens_and_the_fallback() -> None:
    state = make_state()
    llm = llm_chain(state, StubLLM("groq", error=LLMRateLimitError("429")), StubLLM("openai", prompt_tokens=300, completion_tokens=40))

    ask(llm)
    aggregates, calls = state.drain()

    groq = aggregates[(TODAY, "groq", "llm", "conversation")]
    openai = aggregates[(TODAY, "openai", "llm", "conversation")]
    assert (groq["requests"], groq["rate_limited"], groq["successes"]) == (1, 1, 0)
    assert (openai["requests"], openai["successes"], openai["as_fallback"]) == (1, 1, 1)
    assert (openai["prompt_tokens"], openai["completion_tokens"]) == (300, 40)
    assert [c["provider"] for c in calls] == ["groq", "openai"] and calls[1]["fallback_from"] == "groq"


def test_the_log_says_which_provider_answered_and_never_what_was_asked(caplog: pytest.LogCaptureFixture) -> None:
    secret_prompt = "the learner's private sentence"
    llm = llm_chain(make_state(), StubLLM("groq"))

    with caplog.at_level(logging.INFO, logger="app.providers"):
        set_call_context(session_id=7, turn_id=42)
        ask(llm, secret_prompt)

    text = caplog.text
    assert "provider_call" in text and "provider=groq" in text and "outcome=ok" in text and "session=7 turn=42" in text
    assert secret_prompt not in text


def test_the_call_log_carries_the_session_and_turn() -> None:
    state = make_state()
    set_call_context(session_id=3, turn_id=9)

    ask(llm_chain(state, StubLLM("groq")))

    _, calls = state.drain()
    assert (calls[0]["session_id"], calls[0]["turn_id"]) == (3, 9)


# --- the circuit breaker opens and closes -----------------------------------------------------------


def test_the_breaker_opens_after_three_failures_and_closes_when_the_probe_works() -> None:
    clock = Clock()
    state = make_state(clock)
    groq, openai = StubLLM("groq", error=LLMProviderError("503")), StubLLM("openai")
    llm = llm_chain(state, groq, openai)

    for _ in range(3):  # three consecutive failures
        ask(llm)
    assert groq.calls == 3
    assert state.breaker("groq", "llm").snapshot()["state"] == "open"

    ask(llm)  # open: groq is not even tried
    assert groq.calls == 3

    clock.advance(31)  # the 30 s wait is over: one probe goes through, it fails, so it re-opens for twice as long
    ask(llm)
    assert groq.calls == 4 and state.breaker("groq", "llm").snapshot()["retry_in_seconds"] == pytest.approx(60)

    clock.advance(30)
    ask(llm)
    assert groq.calls == 4  # still open (only 30 of the 60 s)

    groq.error = None
    clock.advance(31)  # probe works
    assert ask(llm) == "from groq"
    assert state.breaker("groq", "llm").snapshot()["state"] == "closed"
    assert ask(llm) == "from groq" and groq.calls == 6


def test_two_failures_do_not_open_the_breaker() -> None:
    state = make_state()
    groq = StubLLM("groq", error=LLMProviderError("503"))
    llm = llm_chain(state, groq, StubLLM("openai"))

    ask(llm)
    ask(llm)
    groq.error = None
    ask(llm)  # a success resets the count

    assert state.breaker("groq", "llm").snapshot()["state"] == "closed" and groq.calls == 3


def test_only_one_probe_goes_through_while_half_open() -> None:
    clock = Clock()
    state = make_state(clock)
    breaker = state.breaker("groq", "llm")
    for _ in range(3):
        breaker.record_failure(__import__("app.providers.types", fromlist=["FailureKind"]).FailureKind.UNAVAILABLE)
    clock.advance(31)

    assert breaker.allow() is True  # the probe
    assert breaker.allow() is False  # nobody else until it reports


def test_a_429_that_asks_for_a_long_wait_opens_the_breaker_at_once_for_that_long() -> None:
    state = make_state()
    groq = StubLLM("groq", error=LLMRateLimitError("daily quota", retry_after=900))
    llm = llm_chain(state, groq, StubLLM("openai"))

    ask(llm)

    snapshot = state.breaker("groq", "llm").snapshot()
    assert snapshot["state"] == "open" and snapshot["reason"] == "quota" and snapshot["retry_in_seconds"] == pytest.approx(900)
    ask(llm)
    assert groq.calls == 1


def test_a_short_retry_after_is_an_ordinary_failure() -> None:
    state = make_state()
    llm = llm_chain(state, StubLLM("groq", error=LLMRateLimitError("slow down", retry_after=5)), StubLLM("openai"))

    ask(llm)

    assert state.breaker("groq", "llm").snapshot()["state"] == "closed"


def test_an_account_out_of_credit_opens_the_breaker_for_the_longest_wait() -> None:
    state = make_state()
    llm = llm_chain(state, StubLLM("openai", error=LLMRateLimitError("no credit", quota=True)), StubLLM("groq"))

    ask(llm)

    snapshot = state.breaker("openai", "llm").snapshot()
    assert snapshot["state"] == "open" and snapshot["retry_in_seconds"] == pytest.approx(3600)


def test_a_bad_key_opens_the_breaker_for_an_hour(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    state = make_state(clock)
    groq = StubLLM("groq", error=LLMAuthError("bad key"))
    llm = llm_chain(state, groq, StubLLM("openai"))

    with caplog.at_level(logging.ERROR, logger="app.providers"):
        ask(llm)
    clock.advance(600)
    ask(llm)

    assert groq.calls == 1 and "breaker_open" in caplog.text and "reason=auth" in caplog.text


def test_an_invalid_model_answer_is_not_the_providers_fault() -> None:
    state = make_state()
    llm = llm_chain(state, StubLLM("groq", error=LLMOutputError("bad", last_error="x", attempts=3, prompt_tokens=50, completion_tokens=10)))

    for _ in range(4):
        with pytest.raises(LLMOutputError):  # re-raised as it was, not "everyone is busy"
            ask(llm)

    assert state.breaker("groq", "llm").snapshot()["state"] == "closed"
    aggregates, _ = state.drain()
    assert aggregates[(TODAY, "groq", "llm", "conversation")]["prompt_tokens"] == 200  # the failed attempts cost tokens


# --- spending cap -----------------------------------------------------------------------------------


def _paid_state(**overrides) -> ProviderState:  # type: ignore[no-untyped-def]
    # 1000 USD per million input tokens: 500 tokens cost 0.50 USD.
    base = {"paid_budget_usd": 1.0, "price_openai_llm_input_per_m": 1000.0, "price_openai_llm_output_per_m": 0.0}
    return make_state(**{**base, **overrides})


def test_at_the_cap_the_paid_provider_is_no_longer_used_and_the_free_one_takes_over(caplog: pytest.LogCaptureFixture) -> None:
    state = _paid_state()
    openai, groq = StubLLM("openai", prompt_tokens=500, completion_tokens=0), StubLLM("groq")
    llm = llm_chain(state, openai, groq, use="analysis")

    with caplog.at_level(logging.INFO, logger="app.providers"):
        ask(llm)  # 0.50
        assert state.budget.status() == "ok"
        openai.prompt_tokens = 400
        ask(llm)  # 0.90: past 80 %
        assert state.budget.status() == "warning" and "budget_warning" in caplog.text
        openai.prompt_tokens = 500
        ask(llm)  # 1.40: the cap is crossed by this last call
        assert state.budget.status() == "exhausted" and "budget_exhausted" in caplog.text

    assert (openai.calls, groq.calls) == (3, 0)
    assert ask(llm) == "from groq"  # the paid one is skipped from now on
    assert (openai.calls, groq.calls) == (3, 1)


def test_a_call_that_would_cross_the_cap_is_not_made() -> None:
    state = _paid_state()
    state.budget.load_baseline(0.95)
    openai, groq = StubLLM("openai", prompt_tokens=10), StubLLM("groq")
    llm = llm_chain(state, openai, groq)

    assert ask(llm, "x" * 400_000) == "from groq"  # ~100k tokens would cost 100 USD: refused before calling

    assert openai.calls == 0


def test_a_zero_cap_disables_the_paid_providers() -> None:
    openai, groq = StubLLM("openai"), StubLLM("groq")

    assert ask(llm_chain(make_state(paid_budget_usd=0), openai, groq)) == "from groq" and openai.calls == 0


def test_free_providers_never_touch_the_budget() -> None:
    state = _paid_state()

    ask(llm_chain(state, StubLLM("groq", prompt_tokens=10_000_000)))

    assert state.budget.spent == 0.0


def test_the_budget_starts_again_when_the_period_changes() -> None:
    today = [TODAY]
    state = _paid_state(paid_budget_period="month")
    state = make_state(day=today, paid_budget_usd=1.0, price_openai_llm_input_per_m=1000.0, price_openai_llm_output_per_m=0.0)
    llm = llm_chain(state, StubLLM("openai", prompt_tokens=1000, completion_tokens=0), StubLLM("groq"))
    ask(llm)  # 1.00: the whole month
    assert state.budget.status() == "exhausted"

    today[0] = date(2026, 12, 1)  # next month

    assert state.budget.status() == "ok" and ask(llm) == "from openai"


def test_the_estimate_of_each_kind_of_call() -> None:
    pricing = Pricing(cfg(price_openai_llm_input_per_m=0.15, price_openai_llm_output_per_m=0.6, price_openai_stt_per_minute=0.006,
                          price_openai_tts_per_minute=0.015, tts_cost_safety_factor=1.3))

    assert pricing.cost("openai", "llm", Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)) == pytest.approx(0.75)
    assert pricing.cost("openai", "stt", Usage(audio_seconds_in=120)) == pytest.approx(0.012)
    assert pricing.cost("openai", "tts", Usage(audio_seconds_out=60)) == pytest.approx(0.015 * 1.3)
    assert pricing.cost("groq", "llm", Usage(prompt_tokens=10**9)) == 0.0  # free providers cost nothing here
    assert pricing.cost("openai", "tts", Usage(audio_seconds_out=60, from_cache=True)) == 0.0


# --- daily caps and the cache ------------------------------------------------------------------------


def test_the_free_quota_is_used_first_and_the_cap_sends_the_rest_to_the_paid_voice(tmp_path: Path) -> None:
    state = make_state(provider_daily_caps="groq:tts=2")
    groq, openai = StubVoice("groq"), StubVoice("openai")
    tts = tts_chain(state, groq, openai)

    results = [tts.synthesize(f"line {i}", str(tmp_path / f"{i}.wav")).provider for i in range(4)]

    assert results == ["groq", "groq", "openai", "openai"]  # not a single 429: the switch is proactive
    assert groq.requests == 2


def test_cached_audio_is_served_even_with_the_cap_reached_and_costs_nothing(tmp_path: Path) -> None:
    state = make_state(provider_daily_caps="groq:tts=1")
    groq, openai = StubVoice("groq", cached={"hello"}), StubVoice("openai")
    tts = tts_chain(state, groq, openai)
    tts.synthesize("first", str(tmp_path / "a.wav"))  # uses Groq's only request of the day

    result = tts.synthesize("hello", str(tmp_path / "b.wav"))  # cached on Groq

    assert result.provider == "groq" and result.from_cache is True and openai.requests == 0
    aggregates, _ = state.drain()
    assert aggregates[(TODAY, "groq", "tts", "conversation")]["requests"] == 1  # the cache hit did not count


def test_daily_counters_restart_with_the_day() -> None:
    day = [TODAY]
    state = make_state(day=day, provider_daily_caps="groq:tts=1")
    state.record(__import__("app.providers.state", fromlist=["CallRecord"]).CallRecord("tts", "conversation", "groq", "m", "ok"))
    assert state.cap_reached("groq", "tts") is True

    day[0] = date(2026, 11, 25)

    assert state.cap_reached("groq", "tts") is False


def test_a_429_does_not_use_up_the_days_quota() -> None:
    state = make_state(provider_daily_caps="groq:llm=2")
    llm = llm_chain(state, StubLLM("groq", error=LLMRateLimitError("429")), StubLLM("openai"))

    for _ in range(2):
        ask(llm)

    assert state.cap_reached("groq", "llm") is False


def test_cap_settings_are_validated() -> None:
    assert parse_caps("groq:tts=90, gemini:llm=500") == {("groq", "tts"): 90, ("gemini", "llm"): 500}
    for bad in ("groq=90", "groq:video=3", "groq:tts=0", "groq:tts=many"):
        with pytest.raises(ValueError):
            parse_caps(bad)


# --- everyone is out ------------------------------------------------------------------------------------


def test_every_llm_provider_out_raises_a_handled_error_with_a_wait_hint() -> None:
    state = make_state()
    llm = llm_chain(
        state,
        StubLLM("openai", error=LLMRateLimitError("quota", retry_after=900)),
        StubLLM("groq", error=LLMProviderError("503")),
        use="analysis",
    )

    with pytest.raises(LLMExhausted) as info:
        ask(llm)

    assert isinstance(info.value, LLMRateLimitError) and info.value.retry_later is True  # the HTTP handler still works
    assert info.value.retry_after == pytest.approx(900)
    with pytest.raises(LLMExhausted):
        ask(llm)  # now the breaker of openai is open and the router knows without calling


def test_every_speech_to_text_provider_out_raises_stt_exhausted() -> None:
    class DeadSTT:
        model = "dead"

        def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
            raise STTError("503", status_code=503)

    state = make_state()
    stt = RoutedSTT(ProviderRouter("stt", "conversation", [Route("groq", DeadSTT())], state, classify_stt, stt_exhausted))

    with pytest.raises(STTExhausted) as info:
        stt.transcribe("a.wav")

    assert isinstance(info.value, STTError)  # the existing handler answers 503 stt_unavailable


def test_silence_is_an_answer_not_a_provider_failure() -> None:
    class SilentSTT:
        model = "m"

        def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
            raise NoSpeechError("silence")

    state = make_state()
    stt = RoutedSTT(ProviderRouter("stt", "conversation", [Route("groq", SilentSTT()), Route("openai", SilentSTT())], state, classify_stt, stt_exhausted))

    with pytest.raises(NoSpeechError):
        stt.transcribe("a.wav")

    assert state.breaker("groq", "stt").snapshot()["consecutive_failures"] == 0


def test_every_voice_provider_out_raises_tts_exhausted(tmp_path: Path) -> None:
    tts = tts_chain(make_state(), StubVoice("groq", error=TTSError("quota", status_code=429)), StubVoice("openai", error=TTSError("down", status_code=500)))

    with pytest.raises(TTSExhausted) as info:
        tts.synthesize("hi", str(tmp_path / "a.wav"))

    assert isinstance(info.value, TTSError)


def test_the_synthesis_step_degrades_to_no_audio_instead_of_failing(tmp_path: Path) -> None:
    tts = tts_chain(make_state(), StubVoice("groq", error=TTSError("quota", status_code=429)))
    node = make_synthesize(tts, str(tmp_path))

    update = node({"session_id": 1, "turn_number": 2, "reply_text": "Hello!"})  # type: ignore[arg-type]

    assert update == {"reply_audio_path": "", "reply_audio_seconds": 0.0}


def test_our_own_bad_input_is_not_hidden_behind_a_fallback(tmp_path: Path) -> None:
    openai = StubVoice("openai")
    tts = tts_chain(make_state(), StubVoice("groq", error=TTSError("empty", kind="invalid_input")), openai)

    with pytest.raises(TTSError):
        tts.synthesize("", str(tmp_path / "a.wav"))

    assert openai.requests == 0


def test_a_bad_key_on_every_provider_is_reported_as_it_is() -> None:
    llm = llm_chain(make_state(), StubLLM("groq", error=LLMAuthError("bad")), StubLLM("openai", error=LLMAuthError("bad")))

    with pytest.raises(LLMAuthError):
        ask(llm)


# --- the order comes from the environment ------------------------------------------------------------------


def _names(router_owner) -> list[str]:  # type: ignore[no-untyped-def]
    return [r.name for r in router_owner._router.routes]


def test_the_order_in_the_environment_is_respected() -> None:
    conversation = chains.build_llm("conversation", cfg(llm_conversation_order="gemini,groq"))
    analysis = chains.build_llm("analysis", cfg(llm_analysis_order="groq,openai"))

    assert _names(conversation) == ["gemini", "groq"] and _names(analysis) == ["groq", "openai"]


def test_the_defaults_are_the_approved_design() -> None:
    settings = cfg()

    assert _names(chains.build_llm("conversation", settings)) == ["groq", "openai", "gemini"]
    assert _names(chains.build_llm("analysis", settings)) == ["openai", "groq", "gemini"]
    assert _names(chains.build_stt(settings)) == ["groq", "openai"]
    assert _names(chains.build_tts(settings)) == ["groq", "openai"]


def test_conversation_and_analysis_are_separate_chains_with_different_leaders() -> None:
    settings = cfg()

    assert chains.build_llm("conversation", settings)._router.routes[0].name != chains.build_llm("analysis", settings)._router.routes[0].name


def test_the_paid_provider_can_disappear_and_the_chain_still_works(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.providers"):
        analysis = chains.build_llm("analysis", cfg(openai_api_key=None))
        voice = chains.build_tts(cfg(openai_api_key=None))

    assert _names(analysis) == ["groq", "gemini"] and _names(voice) == ["groq"]
    assert "provider_disabled provider=openai" in caplog.text


def test_a_chain_with_no_usable_provider_is_an_error() -> None:
    nothing = cfg(groq_api_key=None, gemini_api_key=None, openai_api_key=None)

    with pytest.raises(LLMAuthError):
        chains.build_llm("conversation", nothing)
    with pytest.raises(TTSError):
        chains.build_tts(nothing)
    with pytest.raises(STTError):
        chains.build_stt(nothing)


def test_a_bad_order_is_rejected_when_the_settings_load() -> None:
    for bad in ("", "groq,groq", "groq,claude"):
        with pytest.raises(ValueError):
            cfg(llm_conversation_order=bad)
    with pytest.raises(ValueError):
        cfg(tts_order="gemini")  # gemini has no voice


def test_openai_is_a_real_llm_provider_in_the_chain() -> None:
    analysis = chains.build_llm("analysis", cfg())

    assert isinstance(analysis._router.routes[0].provider, OpenAIProvider)
