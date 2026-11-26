"""Langfuse tracing: off without keys (and harmless), masks personal data, and follows the router's attempts."""

from contextlib import contextmanager

import pytest

from app import observability
from app.config import settings


@pytest.fixture(autouse=True)
def _reset_client():
    observability._client = None
    yield
    observability._client = None


def test_off_without_keys_and_every_call_is_a_no_op() -> None:
    assert not settings.langfuse_enabled
    assert not observability.enabled()
    with observability.trace("turno", session_id=1, user_id=2), observability.span("grammar") as traced:
        traced.update(output={"grammar": "done"})
        traced.failed("timeout")
        with observability.provider_call("llm", "analysis", "groq", "m", fallback_from=None, skipped=[]) as call:
            call.succeeded(prompt_tokens=1, completion_tokens=1, cost=0.0, metadata={})
            observability.record_io(input="hola", output="hi")
        observability.score("communication", 4)
    observability.flush()
    observability.shutdown()


def test_mask_hides_emails_and_phone_numbers_everywhere() -> None:
    data = {
        "prompt": "write to ana.perez+x@mail.co or call +57 300 123 4567",
        "list": ["me@x.org", 3],
        "n": 5,
    }
    masked = observability._mask(data=data)
    assert masked["prompt"] == "write to [email] or call [telefono]"
    assert masked["list"] == ["[email]", 3]
    assert masked["n"] == 5


def test_mask_keeps_ordinary_numbers() -> None:
    assert observability._mask(data="I was born in 1998 and I have 2 dogs") == "I was born in 1998 and I have 2 dogs"


class _FakeObservation:
    def __init__(self, log: list, name: str) -> None:
        self.log, self.name = log, name

    def update(self, **kwargs) -> None:
        self.log.append((self.name, kwargs))


class _FakeClient:
    """Records what would have been sent to Langfuse."""

    def __init__(self) -> None:
        self.log: list = []

    @contextmanager
    def start_as_current_observation(self, *, name: str, **kwargs):
        self.log.append((name, {"start": kwargs}))
        yield _FakeObservation(self.log, name)

    def update_current_generation(self, **kwargs) -> None:
        self.log.append(("current", kwargs))


def test_router_traces_every_attempt_with_failure_and_fallback(monkeypatch) -> None:
    from app.llm.errors import LLMRateLimitError
    from app.providers.routed import classify_llm, llm_exhausted
    from app.providers.router import ProviderRouter, Route
    from app.providers.state import ProviderState
    from app.providers.types import Usage

    fake = _FakeClient()
    monkeypatch.setattr(observability, "_client", fake)

    class _Provider:
        def __init__(self, model: str) -> None:
            self.model = model

    state = ProviderState(settings)
    router = ProviderRouter(
        "llm", "analysis", [Route("groq", _Provider("g")), Route("gemini", _Provider("m"))], state,
        classify_llm, llm_exhausted("analysis"),
    )  # fmt: skip

    def invoke(route: Route):
        if route.name == "groq":
            raise LLMRateLimitError("busy")
        return "ok", Usage(prompt_tokens=10, completion_tokens=5)

    assert router.run(invoke) == "ok"

    starts = [(name, entry["start"]) for name, entry in fake.log if "start" in entry]
    assert [name for name, _ in starts] == ["llm:groq", "llm:gemini"]
    assert starts[0][1]["as_type"] == "generation" and starts[0][1]["model"] == "g"
    assert starts[1][1]["metadata"]["fallback_from"] == "groq"
    updates = {name: kwargs for name, kwargs in fake.log if "start" not in kwargs}
    assert updates["llm:groq"]["level"] == "WARNING"
    assert updates["llm:gemini"]["usage_details"] == {"input": 10, "output": 5}
