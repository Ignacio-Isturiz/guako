"""Adapters that give each capability its existing interface on top of a ProviderRouter.

The rest of the app keeps depending on LLMProvider / STTProvider / TTSProvider and never learns which
provider answered. Each adapter says how to call a provider, what a call consumed, and how to read its errors.
"""

import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app import observability
from app.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMOutputError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.providers.errors import LLMExhausted, STTExhausted, TTSExhausted
from app.providers.router import ProviderRouter, Route
from app.providers.types import Classified, FailureKind, Usage
from app.stt.audio import CONVERT_FIRST, as_flac
from app.stt.base import STTProvider
from app.stt.errors import NoSpeechError, STTError
from app.stt.schemas import TranscriptionResult
from app.tts.audio import wav_duration_seconds
from app.tts.base import TTSProvider
from app.tts.errors import TTSError
from app.tts.schemas import TTSResult

T = TypeVar("T", bound=BaseModel)

# Statuses that mean "what we sent is wrong": no other provider can fix them.
_BAD_INPUT_STATUSES = {400, 413, 415, 422}

# The provider could not read the recording: re-encoding it may fix that (a 413 or 422 it would not).
_REJECTED_AUDIO_STATUSES = {400, 415}

logger = logging.getLogger("app.stt")


def _classify_http(status: int | None, kind: str | None, retry_after: float | None) -> Classified:
    """Shared reading of STT/TTS errors, which carry a status and/or a kind."""
    if kind == "invalid_input" or status in _BAD_INPUT_STATUSES:
        return Classified(FailureKind.FATAL)
    if kind == "auth" or status in (401, 403):
        return Classified(FailureKind.AUTH)
    if status == 429:
        return Classified(FailureKind.RATE_LIMITED, retry_after)
    if kind == "timeout":
        return Classified(FailureKind.TIMEOUT)
    return Classified(FailureKind.UNAVAILABLE, retry_after)


# --- LLM -----------------------------------------------------------------------------------------


def classify_llm(exc: Exception) -> Classified:
    if isinstance(exc, LLMOutputError):
        return Classified(FailureKind.BAD_OUTPUT, prompt_tokens=exc.prompt_tokens, completion_tokens=exc.completion_tokens)
    if isinstance(exc, LLMAuthError):
        return Classified(FailureKind.AUTH)
    if isinstance(exc, LLMRateLimitError):
        return Classified(FailureKind.RATE_LIMITED, exc.retry_after, exc.quota)
    if isinstance(exc, LLMTimeoutError):
        return Classified(FailureKind.TIMEOUT)
    if isinstance(exc, LLMError):
        return Classified(FailureKind.UNAVAILABLE)
    return Classified(FailureKind.FATAL)  # not ours (a bug): do not hide it behind a fallback


class RoutedLLM:
    """Satisfies the LLMProvider protocol; ``use`` is "conversation" or "analysis"."""

    def __init__(self, router: ProviderRouter) -> None:
        self._router = router

    @property
    def name(self) -> str:
        route = self._router.last_route
        return route.name if route else "unknown"

    @property
    def model(self) -> str:
        route = self._router.last_route
        return route.model if route else "unknown"

    @property
    def used_fallback(self) -> bool:
        return self._router.used_fallback

    @property
    def last_attempts(self) -> int:
        return int(getattr(self._router.last_route.provider, "last_attempts", 0)) if self._router.last_route else 0

    def generate(self, prompt: str, response_model: type[T], *, system: str | None = None) -> T:
        def invoke(route: Route) -> tuple[T, Usage]:
            provider = route.provider
            observability.record_io(input={"system": system, "prompt": prompt})
            if hasattr(provider, "generate_with_usage"):
                result, used = provider.generate_with_usage(prompt, response_model, system=system)
                usage = Usage(prompt_tokens=used.prompt_tokens, completion_tokens=used.completion_tokens)
            else:
                result, usage = provider.generate(prompt, response_model, system=system), Usage()
            observability.record_io(output=result)
            return result, usage

        pricing = self._router.state.pricing
        size = len(prompt) + len(system or "")
        return self._router.run(invoke, estimate=lambda route: pricing.estimate_llm(route.name, size))


# --- Speech to text ------------------------------------------------------------------------------


def classify_stt(exc: Exception) -> Classified:
    if isinstance(exc, NoSpeechError):
        return Classified(FailureKind.FATAL)  # the audio was silent: that is an answer, not a failure
    if isinstance(exc, STTError):
        return _classify_http(exc.status_code, exc.kind, exc.retry_after)
    return Classified(FailureKind.FATAL)


class RoutedSTT(STTProvider):
    def __init__(self, router: ProviderRouter) -> None:
        self._router = router

    @property
    def model(self) -> str:
        route = self._router.last_route
        return route.model if route else "unknown"

    def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
        # iOS MP4 is converted up front. Any other recording a provider rejects (HTTP 400/415, as Groq does with
        # some iOS recordings) is converted with ffmpeg and tried once more: the happy path pays no conversion.
        if Path(audio_path).suffix.lower() in CONVERT_FIRST:
            with as_flac(audio_path) as flac:
                return self._run(flac or audio_path, context)
        try:
            return self._run(audio_path, context)
        except STTError as exc:
            if exc.status_code not in _REJECTED_AUDIO_STATUSES:
                raise
            with as_flac(audio_path) as flac:
                if flac is None:
                    raise
                logger.warning("stt_retry_converted file=%s first_error=%s", Path(audio_path).name, exc)
                return self._run(flac, context)

    def _run(self, audio_path: str, context: str | None) -> TranscriptionResult:
        def invoke(route: Route) -> tuple[TranscriptionResult, Usage]:
            result = route.provider.transcribe(audio_path, context)
            observability.record_io(output=result.text)  # the transcript only: audio never leaves the server
            seconds = result.duration if result.duration is not None else (result.words[-1].end if result.words else 0.0)
            return result, Usage(audio_seconds_in=seconds)

        pricing = self._router.state.pricing
        return self._router.run(invoke, estimate=lambda route: pricing.estimate_stt(route.name))


# --- Text to speech ------------------------------------------------------------------------------


def classify_tts(exc: Exception) -> Classified:
    if isinstance(exc, TTSError):
        return _classify_http(exc.status_code, exc.kind, exc.retry_after)
    return Classified(FailureKind.FATAL)


class RoutedTTS(TTSProvider):
    def __init__(self, router: ProviderRouter) -> None:
        self._router = router

    @property  # type: ignore[override]
    def name(self) -> str:
        route = self._router.last_route or self._router.routes[0]
        return route.name

    @property  # type: ignore[override]
    def voice(self) -> str:
        route = self._router.last_route or self._router.routes[0]
        return str(getattr(route.provider, "voice", "unknown"))

    @property
    def used_fallback(self) -> bool:
        return self._router.used_fallback

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        def invoke(route: Route) -> tuple[TTSResult, Usage]:
            observability.record_io(input=text)
            result = route.provider.synthesize(text, output_path)
            seconds = 0.0 if result.from_cache else wav_duration_seconds(result.audio_path)
            return result, Usage(audio_seconds_out=seconds, chars=len(text), from_cache=result.from_cache)

        def cached(route: Route) -> bool:
            has_cached = getattr(route.provider, "has_cached", None)
            return bool(has_cached and has_cached(text))

        pricing = self._router.state.pricing
        return self._router.run(
            invoke, estimate=lambda route: pricing.estimate_tts(route.name, text), free_hit=cached
        )


def llm_exhausted(use: str):  # noqa: ANN201
    return lambda retry_after: LLMExhausted(f"Every LLM provider for '{use}' is unavailable right now", retry_after=retry_after)


def stt_exhausted(retry_after: float | None) -> Exception:
    return STTExhausted("Every speech-to-text provider is unavailable right now", retry_after=retry_after)


def tts_exhausted(retry_after: float | None) -> Exception:
    return TTSExhausted("Every text-to-speech provider is unavailable right now", retry_after=retry_after)
