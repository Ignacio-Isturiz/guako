import logging
from typing import Annotated

from fastapi import Depends

from app.config import Settings, settings
from app.llm.base import LLMProvider
from app.llm.errors import LLMAuthError
from app.llm.fallback import FallbackLLMProvider
from app.llm.gemini import GeminiProvider
from app.llm.groq import GroqProvider

logger = logging.getLogger("app.llm")


def get_settings() -> Settings:
    return settings


def build_provider(name: str, cfg: Settings) -> LLMProvider:
    """Build one concrete provider. Raises LLMAuthError when its API key is missing."""
    if name == "gemini":
        if cfg.gemini_api_key is None:
            raise LLMAuthError("GEMINI_API_KEY is not configured")
        return GeminiProvider(
            cfg.gemini_api_key,
            cfg.gemini_model,
            temperature=cfg.llm_temperature,
            timeout_seconds=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )
    if cfg.groq_api_key is None:
        raise LLMAuthError("GROQ_API_KEY is not configured")
    return GroqProvider(
        cfg.groq_api_key,
        cfg.groq_model,
        temperature=cfg.llm_temperature,
        timeout_seconds=cfg.llm_timeout_seconds,
        max_retries=cfg.llm_max_retries,
    )


def get_llm_provider(cfg: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    """Build the provider chosen by LLM_PROVIDER, backed up by LLM_FALLBACK_PROVIDER.

    Works as a FastAPI dependency (``Depends(get_llm_provider)``) and can be
    called directly with a Settings instance. Tests override via
    ``app.dependency_overrides``.

    A missing key on the primary is an error (misconfiguration must be visible).
    A missing key on the fallback only disables the fallback, with a warning.
    """
    primary = build_provider(cfg.llm_provider, cfg)
    fallback_name = cfg.llm_fallback_provider
    if fallback_name == "none" or fallback_name == cfg.llm_provider:
        return primary
    try:
        fallback = build_provider(fallback_name, cfg)
    except LLMAuthError:
        logger.warning("llm_fallback_disabled provider=%s reason=missing_api_key", fallback_name)
        return primary
    return FallbackLLMProvider(primary, fallback)
