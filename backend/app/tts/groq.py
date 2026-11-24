import logging
import time
from pathlib import Path

import groq
from pydantic import SecretStr

from app.config import settings
from app.providers.util import retry_after_seconds
from app.tts.base import TTSProvider
from app.tts.errors import TTSError
from app.tts.schemas import TTSResult

logger = logging.getLogger("app.tts")


class GroqOrpheusTTSProvider(TTSProvider):
    """Orpheus English TTS hosted on Groq (POST /openai/v1/audio/speech)."""

    name = "groq"

    def __init__(
        self,
        api_key: SecretStr | None = None,
        model: str | None = None,
        voice: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        # Fall back to the app settings (which read GROQ_API_KEY from the environment).
        key = api_key if api_key is not None else settings.groq_api_key
        if key is None or not key.get_secret_value().strip():
            raise TTSError("GROQ_API_KEY is not set")
        self.model = model or settings.tts_model
        self.voice = voice or settings.tts_voice
        self._timeout_seconds = timeout_seconds or settings.tts_timeout_seconds
        # SDK retries are off so the timeout is a real upper bound and a 429
        # surfaces immediately (the fallback decides what to do next).
        self._client = groq.Groq(
            api_key=key.get_secret_value(),
            timeout=self._timeout_seconds,
            max_retries=0,
        )

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        if not text.strip():
            raise TTSError("Cannot synthesize empty text", kind="invalid_input")

        started = time.perf_counter()
        try:
            response = self._client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="wav",
            )
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            response.write_to_file(out)
        except groq.APITimeoutError as exc:
            raise TTSError(f"Groq speech request timed out after {self._timeout_seconds}s", kind="timeout") from exc
        except groq.AuthenticationError as exc:
            raise TTSError("Groq rejected the API key", status_code=401) from exc
        except groq.APIStatusError as exc:
            # 429 = rate limit / daily quota.
            if "model_terms_required" in str(exc.body):
                raise TTSError(
                    "Groq Orpheus terms not accepted: an org admin must accept them in the Groq console "
                    "(console.groq.com/playground?model=canopylabs%2Forpheus-v1-english)",
                    status_code=exc.status_code,
                ) from exc
            raise TTSError(
                f"Groq speech API error (HTTP {exc.status_code})",
                status_code=exc.status_code,
                retry_after=retry_after_seconds(exc),
            ) from exc
        except groq.APIError as exc:
            raise TTSError(f"Groq speech request failed: {type(exc).__name__}") from exc
        except OSError as exc:
            raise TTSError(f"Cannot write audio file: {exc.strerror or type(exc).__name__}") from exc
        finally:
            logger.info(
                "tts provider=groq model=%s voice=%s latency=%.3fs",
                self.model,
                self.voice,
                time.perf_counter() - started,
            )

        return TTSResult(audio_path=str(output_path), provider=self.name, from_cache=False)
