from abc import ABC, abstractmethod

from app.pronunciation.schemas import PronunciationResult


class PronunciationProvider(ABC):
    """Scores how a learner pronounced a known text. The rest of the app depends only on this."""

    # Longest audio the provider assesses in one call. The caller cuts the reference text to the
    # words that fit; implementations cut the audio to the same length.
    max_audio_seconds: float

    @abstractmethod
    def score_turn(self, audio_path: str, reference_text: str) -> PronunciationResult:
        """Blocking. Raises a ``PronunciationError`` subclass on any failure."""
