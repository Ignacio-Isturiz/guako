"""FastAPI dependencies for the speech providers. Tests override these with fakes."""

from app.stt import GroqWhisperSTTProvider, STTProvider
from app.tts import TTSProvider
from app.tts.factory import get_tts_provider as build_tts_provider


def get_stt_provider() -> STTProvider:
    return GroqWhisperSTTProvider()


def get_tts_provider() -> TTSProvider:
    return build_tts_provider()
