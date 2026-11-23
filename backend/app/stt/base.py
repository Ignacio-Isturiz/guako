from abc import ABC, abstractmethod

from app.stt.schemas import TranscriptionResult


class STTProvider(ABC):
    """Turns a recorded audio file into text with word-level timestamps."""

    @abstractmethod
    def transcribe(self, audio_path: str) -> TranscriptionResult:
        """Transcribe the audio file at ``audio_path``.

        Raises:
            STTError: on any failure (missing key, bad file, API error, timeout).
        """
