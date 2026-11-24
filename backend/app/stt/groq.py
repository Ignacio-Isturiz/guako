import logging
import time
from pathlib import Path
from typing import Any

import groq
from pydantic import SecretStr, ValidationError

from app.config import settings
from app.stt.base import STTProvider
from app.stt.errors import STTError
from app.stt.schemas import TranscriptionResult, WordTiming

logger = logging.getLogger("app.stt")

# Whisper reads at most 224 tokens of prompt; the end of the context is the part that matters.
PROMPT_MAX_CHARS = 600

# Formats accepted by the Groq transcription endpoint.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}
)


class GroqWhisperSTTProvider(STTProvider):
    """Whisper hosted on Groq, with word-level timestamps."""

    def __init__(
        self,
        api_key: SecretStr | None = None,
        model: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        # Fall back to the app settings (which read GROQ_API_KEY from the environment).
        key = api_key if api_key is not None else settings.groq_api_key
        if key is None or not key.get_secret_value().strip():
            raise STTError("GROQ_API_KEY is not set")
        self.model = model or settings.stt_model
        self._timeout_seconds = timeout_seconds or settings.stt_timeout_seconds
        # SDK retries are off so the timeout is a real upper bound per call.
        self._client = groq.Groq(
            api_key=key.get_secret_value(),
            timeout=self._timeout_seconds,
            max_retries=0,
        )

    def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
        path = Path(audio_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise STTError(
                f"Unsupported audio format '{path.suffix}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        started = time.perf_counter()
        try:
            with path.open("rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    file=(path.name, audio_file.read()),
                    model=self.model,
                    # Without a hint Whisper often misdetects accented English
                    # as Spanish, Romanian, etc. and returns the wrong language.
                    **({"language": settings.stt_language} if settings.stt_language else {}),
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                    # Whisper's prompt is "the text before": it biases it toward words that fit there
                    # ("today" after "did you do anything special this morning?" instead of "to die").
                    **({"prompt": context.strip()[-PROMPT_MAX_CHARS:]} if context and context.strip() else {}),
                )
        except OSError as exc:
            raise STTError(f"Cannot read audio file '{path.name}': {exc.strerror or type(exc).__name__}") from exc
        except groq.APITimeoutError as exc:
            raise STTError(f"Groq transcription timed out after {self._timeout_seconds}s") from exc
        except groq.AuthenticationError as exc:
            raise STTError("Groq rejected the API key") from exc
        except groq.APIStatusError as exc:
            raise STTError(f"Groq API error (HTTP {exc.status_code})") from exc
        except groq.APIError as exc:
            raise STTError(f"Groq request failed: {type(exc).__name__}") from exc
        finally:
            latency = time.perf_counter() - started
            logger.info("stt model=%s file=%s latency=%.3fs", self.model, path.name, latency)

        return self._to_result(response.model_dump())

    @staticmethod
    def _to_result(payload: dict[str, Any]) -> TranscriptionResult:
        """Map Groq's verbose_json payload to our own model."""
        try:
            words = [
                WordTiming(
                    word=str(item["word"]),
                    start=float(item["start"]),
                    end=float(item["end"]),
                    confidence=None,  # Groq does not return per-word confidence.
                )
                for item in payload.get("words") or []
            ]
            return TranscriptionResult(
                text=str(payload.get("text", "")).strip(),
                language=payload.get("language"),
                duration=float(payload["duration"]) if payload.get("duration") is not None else None,
                words=words,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise STTError("Groq returned an unexpected transcription format") from exc
