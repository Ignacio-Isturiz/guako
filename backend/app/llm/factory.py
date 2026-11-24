"""FastAPI dependencies for the LLM. The chains (order, fallback, breakers, budget) live in app.providers."""

from typing import Annotated

from fastapi import Depends

from app.config import Settings, settings
from app.llm.base import LLMProvider
from app.providers import chains


def get_settings() -> Settings:
    return settings


def get_llm_provider(cfg: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    """The conversation chain (LLM_CONVERSATION_ORDER): latency matters, the learner is waiting.

    Works as a FastAPI dependency and can be called directly with a Settings instance. Tests override it
    via ``app.dependency_overrides``.
    """
    return chains.conversation_llm(cfg)


def get_analysis_llm_provider(cfg: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    """The analysis chain (LLM_ANALYSIS_ORDER): background work, so it spends the paid provider first and
    leaves the free quota of the conversation chain alone."""
    return chains.analysis_llm(cfg)
