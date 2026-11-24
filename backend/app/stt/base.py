from abc import ABC, abstractmethod

from app.stt.schemas import TranscriptionResult


class STTProvider(ABC):
    """Turns a recorded audio file into text with word-level timestamps."""

    @abstractmethod
    def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
        """Transcribe the audio file at ``audio_path``.

        ``context`` is the text that came just before (the tutor's last message): the recognizer uses it
        to prefer words that make sense there instead of a different word that sounds alike.

        Raises:
            STTError: on any failure (missing key, bad file, API error, timeout).
        """
