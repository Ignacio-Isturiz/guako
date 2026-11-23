import logging
from typing import TypeVar

from pydantic import BaseModel

from app.llm.base import LLMProvider
from app.llm.errors import LLMError

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("app.llm")


class FallbackLLMProvider:
    """Tries ``primary``; if it raises an LLMError, answers with ``secondary`` instead.

    Each provider keeps its own validate-and-retry loop, so the secondary only
    runs once the primary has given up. If both fail, the secondary's error is
    raised (the primary's stays in the log and as ``__context__``).
    """

    def __init__(self, primary: LLMProvider, secondary: LLMProvider) -> None:
        self._primary = primary
        self._secondary = secondary
        # Provider that produced the most recent answer (or failed last).
        self._used: LLMProvider = primary

    @property
    def name(self) -> str:
        return str(getattr(self._used, "name", "unknown"))

    @property
    def model(self) -> str:
        return str(getattr(self._used, "model", "unknown"))

    @property
    def last_attempts(self) -> int:
        return int(getattr(self._used, "last_attempts", 0))

    @property
    def used_fallback(self) -> bool:
        return self._used is self._secondary

    def generate(self, prompt: str, response_model: type[T], *, system: str | None = None) -> T:
        self._used = self._primary
        try:
            return self._primary.generate(prompt, response_model, system=system)
        except LLMError as exc:
            logger.warning(
                "llm_fallback primary=%s error=%s",
                getattr(self._primary, "name", "unknown"),
                type(exc).__name__,
            )
        self._used = self._secondary
        return self._secondary.generate(prompt, response_model, system=system)
