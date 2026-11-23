import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.llm.errors import LLMAuthError, LLMProviderError, LLMRateLimitError
from app.llm.factory import get_llm_provider
from app.llm.fallback import FallbackLLMProvider
from app.llm.schemas import TutorReply


class Stub:
    """Minimal provider: returns a reply or raises, and counts its calls."""

    def __init__(self, name: str, *, reply: str = "ok", error: Exception | None = None) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.last_attempts = 1
        self.reply = reply
        self.error = error
        self.calls = 0

    def generate(self, prompt: str, response_model: type[BaseModel], *, system: str | None = None) -> BaseModel:
        self.calls += 1
        if self.error:
            raise self.error
        return response_model(reply=self.reply)


def test_primary_answers_and_fallback_is_not_called() -> None:
    primary, backup = Stub("groq", reply="from groq"), Stub("gemini")
    provider = FallbackLLMProvider(primary, backup)

    assert provider.generate("hi", TutorReply).reply == "from groq"
    assert (primary.calls, backup.calls) == (1, 0)
    assert (provider.name, provider.used_fallback) == ("groq", False)


def test_fallback_answers_when_primary_fails() -> None:
    primary, backup = Stub("groq", error=LLMRateLimitError("429")), Stub("gemini", reply="from gemini")
    provider = FallbackLLMProvider(primary, backup)

    assert provider.generate("hi", TutorReply).reply == "from gemini"
    assert (provider.name, provider.model, provider.used_fallback) == ("gemini", "gemini-model", True)


def test_next_call_tries_the_primary_again() -> None:
    primary = Stub("groq", error=LLMProviderError("down"))
    provider = FallbackLLMProvider(primary, Stub("gemini"))
    provider.generate("hi", TutorReply)

    primary.error = None
    provider.generate("hi", TutorReply)

    assert primary.calls == 2 and provider.used_fallback is False


def test_both_failing_raises_the_fallback_error() -> None:
    provider = FallbackLLMProvider(
        Stub("groq", error=LLMProviderError("a")), Stub("gemini", error=LLMRateLimitError("b"))
    )
    with pytest.raises(LLMRateLimitError):
        provider.generate("hi", TutorReply)


def _cfg(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    base = {
        "llm_provider": "groq",
        "llm_fallback_provider": "gemini",
        "groq_api_key": SecretStr("g"),
        "gemini_api_key": SecretStr("m"),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_factory_wraps_primary_with_the_fallback() -> None:
    provider = get_llm_provider(_cfg())
    assert isinstance(provider, FallbackLLMProvider)
    assert provider.name == "groq"


def test_factory_without_fallback_key_uses_primary_only() -> None:
    provider = get_llm_provider(_cfg(gemini_api_key=None))
    assert not isinstance(provider, FallbackLLMProvider) and provider.name == "groq"  # type: ignore[attr-defined]


def test_factory_fallback_none_or_same_provider_is_primary_only() -> None:
    assert not isinstance(get_llm_provider(_cfg(llm_fallback_provider="none")), FallbackLLMProvider)
    assert not isinstance(get_llm_provider(_cfg(llm_fallback_provider="groq")), FallbackLLMProvider)


def test_factory_missing_primary_key_is_an_error() -> None:
    with pytest.raises(LLMAuthError):
        get_llm_provider(_cfg(groq_api_key=None))
