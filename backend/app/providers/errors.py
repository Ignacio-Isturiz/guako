"""Raised when every provider of a capability is out: breaker open, daily cap reached or budget spent.

They subclass the errors each layer already handles, so the existing HTTP handlers keep working: an
exhausted LLM answers 429 "ai_busy", an exhausted STT answers 503 "stt_unavailable". Callers that can
do better catch them: text to speech degrades to the browser's voice, background analysis stays pending.
"""

from app.llm.errors import LLMRateLimitError
from app.stt.errors import STTError
from app.tts.errors import TTSError


class LLMExhausted(LLMRateLimitError):
    retry_later = True

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message, retry_after=retry_after)


class STTExhausted(STTError):
    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message, retry_after=retry_after, kind="exhausted")


class TTSExhausted(TTSError):
    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message, retry_after=retry_after, kind="exhausted")
