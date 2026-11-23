import wave
from pathlib import Path

# Orpheus and OpenAI both return 24 kHz, 16-bit, mono WAV; used only to estimate
# the length when the WAV header cannot be trusted (e.g. streamed files).
_FALLBACK_BYTES_PER_SECOND = 24_000 * 2
_WAV_HEADER_BYTES = 44


def wav_duration_seconds(path: str) -> float:
    """Length of a WAV file in seconds (0.0 if the file is missing)."""
    file = Path(path)
    try:
        with wave.open(str(file), "rb") as wav:
            rate = wav.getframerate()
            frames = wav.getnframes()
            # A streamed WAV can carry a placeholder length: trust it only if it fits the file.
            if rate > 0 and frames * wav.getsampwidth() * wav.getnchannels() <= file.stat().st_size:
                return frames / rate
    except (wave.Error, EOFError, OSError):
        pass
    try:
        return max(file.stat().st_size - _WAV_HEADER_BYTES, 0) / _FALLBACK_BYTES_PER_SECOND
    except OSError:
        return 0.0
