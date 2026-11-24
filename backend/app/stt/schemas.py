from pydantic import BaseModel


class WordTiming(BaseModel):
    """One spoken word with its position in the audio."""

    word: str
    # Offsets in seconds from the start of the audio.
    start: float
    end: float
    # Whisper on Groq does not report per-word confidence; None when unavailable.
    confidence: float | None = None


class TranscriptionResult(BaseModel):
    """Full transcription of one audio file."""

    text: str
    # Language detected or reported by the provider (e.g. "english"), if any.
    language: str | None = None
    # Length of the audio in seconds, when the provider reports it.
    duration: float | None = None
    words: list[WordTiming]
    # How much to trust the text, from the recognizer's own numbers (None when it did not send them):
    # exp of the average log-probability of the words, and the highest probability that there is no speech.
    confidence: float | None = None
    no_speech_prob: float | None = None
