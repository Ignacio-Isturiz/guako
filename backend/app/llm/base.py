import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.errors import LLMOutputError

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("app.llm")


class LLMProvider(Protocol):
    """What the rest of the app depends on: text in, validated model out."""

    def generate(self, prompt: str, response_model: type[T], *, system: str | None = None) -> T: ...


@dataclass(frozen=True)
class RawCompletion:
    """Raw provider answer before validation."""

    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class BaseLLMProvider(ABC):
    """Shared validate-and-retry loop; subclasses only implement one raw call."""

    name: str
    model: str

    def __init__(self, *, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    @abstractmethod
    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        """Call the provider once. Must raise LLMAuthError / LLMRateLimitError /
        LLMTimeoutError / LLMProviderError for transport failures."""

    def generate(self, prompt: str, response_model: type[T], *, system: str | None = None) -> T:
        current_prompt = prompt
        last_error = ""
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            start = time.perf_counter()
            raw = self._complete(current_prompt, system, response_model)
            latency_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "llm_call provider=%s model=%s attempt=%d latency_ms=%.0f prompt_tokens=%s completion_tokens=%s",
                self.name,
                self.model,
                attempt,
                latency_ms,
                raw.prompt_tokens,
                raw.completion_tokens,
            )
            try:
                return response_model.model_validate_json(raw.text)
            except ValidationError as exc:
                last_error = str(exc)
                # Log only the error summary, never the prompt or the model output.
                logger.warning(
                    "llm_invalid_output provider=%s model=%s attempt=%d errors=%d",
                    self.name,
                    self.model,
                    attempt,
                    exc.error_count(),
                )
                # Feed the validation error back so the model can fix its own output.
                current_prompt = (
                    f"{prompt}\n\n"
                    "Your previous answer was invalid JSON for the required schema. "
                    f"Validation error:\n{last_error}\n"
                    "Return ONLY corrected JSON that satisfies the schema."
                )
        raise LLMOutputError(
            f"{self.name} did not return valid output after {attempts} attempts",
            last_error=last_error,
            attempts=attempts,
        )
