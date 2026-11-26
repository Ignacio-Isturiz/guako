from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.llm.base import BaseLLMProvider, RawCompletion
from app.llm.errors import LLMAuthError, LLMOutputError, LLMRateLimitError
from app.llm.factory import get_llm_provider
from app.llm.gemini import GeminiProvider
from app.llm.groq import GroqProvider
from app.llm.schemas import GrammarAnalysis

VALID = '{"errors": [{"original": "I goed", "correction": "I went", "error_type": "verb", "explanation": "Irregular."}]}'
INVALID = '{"errors": [{"original": "x"}]}'


class FakeProvider(BaseLLMProvider):
    """Returns scripted answers; never touches the network."""

    name = "fake"
    model = "fake-model"

    def __init__(self, answers: list[str], *, max_retries: int = 2) -> None:
        super().__init__(max_retries=max_retries)
        self.answers = answers
        self.prompts: list[str] = []

    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        self.prompts.append(prompt)
        return RawCompletion(text=self.answers[len(self.prompts) - 1])


def test_valid_response_returns_model_instance() -> None:
    result = FakeProvider([VALID]).generate("hi", GrammarAnalysis)
    assert isinstance(result, GrammarAnalysis)
    assert result.errors[0].correction == "I went"


def test_retry_after_invalid_json_returns_second_answer() -> None:
    provider = FakeProvider(["not json at all", VALID])
    result = provider.generate("hi", GrammarAnalysis)
    assert result.errors[0].original == "I goed"
    assert len(provider.prompts) == 2
    assert "Validation error" in provider.prompts[1]  # error was fed back


def test_all_invalid_raises_output_error() -> None:
    provider = FakeProvider([INVALID] * 3, max_retries=2)
    with pytest.raises(LLMOutputError) as info:
        provider.generate("hi", GrammarAnalysis)
    assert info.value.attempts == 3
    assert info.value.last_error


def test_auth_and_rate_limit_errors_are_not_retried() -> None:
    class Failing(FakeProvider):
        def __init__(self, exc: Exception) -> None:
            super().__init__([])
            self.exc = exc

        def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
            self.prompts.append(prompt)
            raise self.exc

    for exc in (LLMAuthError("bad key"), LLMRateLimitError("quota")):
        provider = Failing(exc)
        with pytest.raises(type(exc)):
            provider.generate("hi", GrammarAnalysis)
        assert len(provider.prompts) == 1


def _make(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def _settings(order: str) -> Settings:
    return _make(
        llm_conversation_order=order,
        gemini_api_key=SecretStr("dummy-a"),
        groq_api_key=SecretStr("dummy-b"),
    )


def _first_provider(order: str) -> object:
    return get_llm_provider(_settings(order))._router.routes[0].provider  # type: ignore[attr-defined]


def test_factory_returns_provider_for_setting() -> None:
    assert isinstance(_first_provider("gemini"), GeminiProvider)
    assert isinstance(_first_provider("groq"), GroqProvider)


def test_factory_without_key_raises_auth_error() -> None:
    with pytest.raises(LLMAuthError):
        get_llm_provider(_make(llm_conversation_order="groq"))


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ValueError):
        _make(llm_conversation_order="nope")


def test_secret_not_in_repr() -> None:
    assert "dummy-a" not in repr(_settings("gemini"))


def test_low_reasoning_only_in_the_conversation_chain() -> None:
    """The learner waits for the conversation; the background analysis keeps the model's own effort."""
    from app.llm.factory import get_analysis_llm_provider

    cfg = _make(llm_conversation_order="groq", llm_analysis_order="groq", groq_api_key=SecretStr("dummy-b"))
    conversation = get_llm_provider(cfg)._router.routes[0].provider  # type: ignore[attr-defined]
    analysis = get_analysis_llm_provider(cfg)._router.routes[0].provider  # type: ignore[attr-defined]
    assert conversation._extra == {"reasoning_effort": "low"}
    assert analysis._extra == {}


def test_empty_reasoning_effort_is_not_sent() -> None:
    cfg = _make(llm_conversation_order="groq", groq_api_key=SecretStr("dummy-b"), groq_conversation_reasoning_effort="")
    assert get_llm_provider(cfg)._router.routes[0].provider._extra == {}  # type: ignore[attr-defined]
