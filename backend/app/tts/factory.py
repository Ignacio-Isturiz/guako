from app.config import Settings, settings
from app.providers import chains
from app.tts.base import TTSProvider


def get_tts_provider(cfg: Settings = settings) -> TTSProvider:
    """The text-to-speech chain (TTS_ORDER), each provider behind its own cache."""
    return chains.text_to_speech(cfg)
