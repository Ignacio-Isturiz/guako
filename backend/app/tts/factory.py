import logging

from app.config import Settings, settings
from app.tts.base import TTSProvider
from app.tts.cached import CachedTTSProvider
from app.tts.errors import TTSError
from app.tts.fallback import FallbackTTSProvider
from app.tts.groq import GroqOrpheusTTSProvider
from app.tts.openai_tts import OpenAITTSProvider

logger = logging.getLogger("app.tts")


def get_tts_provider(cfg: Settings = settings) -> TTSProvider:
    """Groq Orpheus (free, daily quota) backed up by OpenAI (paid) when configured.

    Each provider gets its own cache, so a cached phrase costs nothing on either.
    A missing OpenAI key only disables the backup, with a warning.
    """
    primary = CachedTTSProvider(GroqOrpheusTTSProvider(cfg.groq_api_key))
    if cfg.tts_fallback_provider == "none":
        return primary
    if cfg.openai_api_key is None:
        logger.warning("tts_fallback_disabled provider=openai reason=missing_api_key")
        return primary
    try:
        backup = CachedTTSProvider(OpenAITTSProvider(cfg.openai_api_key))
    except TTSError:  # blank key
        logger.warning("tts_fallback_disabled provider=openai reason=missing_api_key")
        return primary
    return FallbackTTSProvider(primary, backup)
