from typing import Annotated

from fastapi import Depends

from app.config import Settings, settings
from app.llm.base import LLMProvider
from app.llm.errors import LLMAuthError
from app.llm.gemini import GeminiProvider
from app.llm.groq import GroqProvider


def get_settings() -> Settings:
    return settings


def get_llm_provider(cfg: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    """Build the provider chosen by LLM_PROVIDER.

    Works as a FastAPI dependency (``Depends(get_llm_provider)``) and can be
    called directly with a Settings instance. Tests override via
    ``app.dependency_overrides``.
    """
    if cfg.llm_provider == "gemini":
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
