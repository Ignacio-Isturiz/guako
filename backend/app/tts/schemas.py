from pydantic import BaseModel


class TTSResult(BaseModel):
    """Outcome of one synthesis request."""

    # Path of the WAV file the caller asked for.
    audio_path: str
    # Name of the provider that produced the audio (e.g. "groq").
    provider: str
    # True when the audio was served from the local cache (no provider call).
    from_cache: bool
