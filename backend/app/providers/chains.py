"""Builds the provider chains from the order the environment asks for (LLM_CONVERSATION_ORDER, ...).

The order is configuration, never code. A provider without an API key is left out with a warning, so the
paid one can disappear and the app keeps working; a chain with no usable provider is an error.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

from app.config import Settings, parse_order, settings
from app.llm.errors import LLMAuthError
from app.llm.gemini import GeminiProvider
from app.llm.groq import GroqProvider
from app.llm.openai_llm import OpenAIProvider
from app.providers.router import ProviderRouter, Route
from app.providers.routed import (
    RoutedLLM,
    RoutedSTT,
    RoutedTTS,
    classify_llm,
    classify_stt,
    classify_tts,
    llm_exhausted,
    stt_exhausted,
    tts_exhausted,
)
from app.providers.state import ProviderState, get_state
from app.stt.errors import STTError
from app.stt.groq import GroqWhisperSTTProvider
from app.stt.openai_stt import OpenAIWhisperSTTProvider
from app.tts import CachedTTSProvider, GroqOrpheusTTSProvider
from app.tts.errors import TTSError
from app.tts.openai_tts import OpenAITTSProvider

logger = logging.getLogger("app.providers")

_MISSING_KEY = (LLMAuthError, STTError, TTSError)


def _has_key(key: Any) -> bool:
    return key is not None and bool(key.get_secret_value().strip())


def _llm_provider(name: str, cfg: Settings):  # noqa: ANN202
    keys = {"groq": cfg.groq_api_key, "gemini": cfg.gemini_api_key, "openai": cfg.openai_api_key}
    if not _has_key(keys[name]):
        raise LLMAuthError(f"{name} API key is not configured")
    common = {"temperature": cfg.llm_temperature, "timeout_seconds": cfg.llm_timeout_seconds, "max_retries": cfg.llm_max_retries}
    if name == "groq":
        return GroqProvider(keys[name], cfg.groq_model, **common)
    if name == "gemini":
        return GeminiProvider(keys[name], cfg.gemini_model, **common)
    return OpenAIProvider(keys[name], cfg.openai_llm_model, **common)


def _speech_key(name: str, cfg: Settings) -> Any:
    return cfg.groq_api_key if name == "groq" else cfg.openai_api_key


def _stt_provider(name: str, cfg: Settings):  # noqa: ANN202
    # The key is checked here, against THIS settings object: a provider given no key would fall back to
    # the global settings (the real .env) and be built anyway.
    if not _has_key(_speech_key(name, cfg)):
        raise STTError(f"{name} API key is not configured", kind="auth")
    if name == "groq":
        return GroqWhisperSTTProvider(cfg.groq_api_key)
    return OpenAIWhisperSTTProvider(cfg.openai_api_key)


def _tts_provider(name: str, cfg: Settings):  # noqa: ANN202
    # Each provider gets its own cache, so a cached phrase costs nothing on either and keeps its voice.
    if not _has_key(_speech_key(name, cfg)):
        raise TTSError(f"{name} API key is not configured", kind="auth")
    if name == "groq":
        return CachedTTSProvider(GroqOrpheusTTSProvider(cfg.groq_api_key))
    return CachedTTSProvider(OpenAITTSProvider(cfg.openai_api_key))


def _routes(order: str, make: Callable[[str], Any], capability: str, use: str, empty: Exception) -> list[Route]:
    routes: list[Route] = []
    for name in parse_order(order):
        try:
            routes.append(Route(name, make(name)))
        except _MISSING_KEY:
            logger.warning("provider_disabled provider=%s capability=%s use=%s reason=missing_api_key", name, capability, use)
    if not routes:
        raise empty
    logger.info("provider_chain capability=%s use=%s order=%s", capability, use, ",".join(r.name for r in routes))
    return routes


def _state_for(cfg: Settings, state: ProviderState | None) -> ProviderState:
    if state is not None:
        return state
    return get_state() if cfg is settings else ProviderState(cfg)


def build_llm(use: str, cfg: Settings = settings, state: ProviderState | None = None) -> RoutedLLM:
    """use = "conversation" (latency first) or "analysis" (background; keeps the conversation's free quota)."""
    order = cfg.llm_conversation_order if use == "conversation" else cfg.llm_analysis_order
    empty = LLMAuthError(f"No LLM provider is configured for '{use}' (check the API keys and LLM_{use.upper()}_ORDER)")
    routes = _routes(order, lambda n: _llm_provider(n, cfg), "llm", use, empty)
    return RoutedLLM(ProviderRouter("llm", use, routes, _state_for(cfg, state), classify_llm, llm_exhausted(use)))


def build_stt(cfg: Settings = settings, state: ProviderState | None = None) -> RoutedSTT:
    empty = STTError("No speech-to-text provider is configured (check the API keys and STT_ORDER)", kind="auth")
    routes = _routes(cfg.stt_order, lambda n: _stt_provider(n, cfg), "stt", "conversation", empty)
    return RoutedSTT(ProviderRouter("stt", "conversation", routes, _state_for(cfg, state), classify_stt, stt_exhausted))


def build_tts(cfg: Settings = settings, state: ProviderState | None = None) -> RoutedTTS:
    empty = TTSError("No text-to-speech provider is configured (check the API keys and TTS_ORDER)", kind="auth")
    routes = _routes(cfg.tts_order, lambda n: _tts_provider(n, cfg), "tts", "conversation", empty)
    return RoutedTTS(ProviderRouter("tts", "conversation", routes, _state_for(cfg, state), classify_tts, tts_exhausted))


# The app's own chains are built once per process: breakers and counters live in the shared state, and a new
# HTTP client per request would be wasteful. Any other Settings (tests, scripts) gets a fresh chain.
_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def _cached(key: str, cfg: Settings, build: Callable[[], Any]) -> Any:
    if cfg is not settings:
        return build()
    with _cache_lock:
        if key not in _cache:
            _cache[key] = build()
        return _cache[key]


def conversation_llm(cfg: Settings = settings) -> RoutedLLM:
    return _cached("llm:conversation", cfg, lambda: build_llm("conversation", cfg))


def analysis_llm(cfg: Settings = settings) -> RoutedLLM:
    return _cached("llm:analysis", cfg, lambda: build_llm("analysis", cfg))


def speech_to_text(cfg: Settings = settings) -> RoutedSTT:
    return _cached("stt", cfg, lambda: build_stt(cfg))


def text_to_speech(cfg: Settings = settings) -> RoutedTTS:
    return _cached("tts", cfg, lambda: build_tts(cfg))


def clear_chain_cache() -> None:
    """Forget the built chains (tests)."""
    with _cache_lock:
        _cache.clear()
