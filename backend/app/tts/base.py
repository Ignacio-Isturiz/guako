from abc import ABC, abstractmethod

from app.tts.schemas import TTSResult


class TTSProvider(ABC):
    """Turns English text into a WAV file."""

    # Short provider name reported in TTSResult.provider.
    name: str
    # Voice identifier; part of the cache key so different voices never collide.
    voice: str

    @abstractmethod
    def synthesize(self, text: str, output_path: str) -> TTSResult:
        """Write the spoken ``text`` as WAV to ``output_path``.

        Raises:
            TTSError: on any failure (missing config, API error, timeout).
        """
