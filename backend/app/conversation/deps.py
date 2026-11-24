"""FastAPI dependencies for the speech providers. Tests override these with fakes."""

import logging

from app.pronunciation import AzurePronunciationProvider, PronunciationError, PronunciationProvider
from app.config import settings
from app.providers import chains
from app.stt import STTProvider
from app.tts import TTSProvider
from app.tts.factory import get_tts_provider as build_tts_provider


def get_stt_provider() -> STTProvider:
    return chains.speech_to_text(settings)


def get_tts_provider() -> TTSProvider:
    return build_tts_provider()


def get_pronunciation_provider() -> PronunciationProvider | None:
    """None when Azure Speech is not configured: the pronunciation analysis then fails, nothing else does."""
    try:
        return AzurePronunciationProvider()
    except PronunciationError as exc:
        logging.getLogger("app.pronunciation").warning("pronunciation_unavailable error=%s", exc.code)
        return None
