import logging

from app.tts.base import TTSProvider
from app.tts.errors import TTSError
from app.tts.schemas import TTSResult

logger = logging.getLogger("app.tts")


class FallbackTTSProvider(TTSProvider):
    """Tries ``primary``; if it raises a TTSError (quota, outage), uses ``secondary``.

    Put the cache around each provider (not around this wrapper) so cached audio
    keeps the voice it was generated with.
    """

    def __init__(self, primary: TTSProvider, secondary: TTSProvider) -> None:
        self._primary = primary
        self._secondary = secondary
        self._used = primary

    @property  # type: ignore[override]
    def name(self) -> str:
        return self._used.name

    @property  # type: ignore[override]
    def voice(self) -> str:
        return self._used.voice

    @property
    def used_fallback(self) -> bool:
        return self._used is self._secondary

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        self._used = self._primary
        try:
            return self._primary.synthesize(text, output_path)
        except TTSError as exc:
            logger.warning("tts_fallback primary=%s status=%s", self._primary.name, exc.status_code)
        self._used = self._secondary
        return self._secondary.synthesize(text, output_path)
