import logging
import time
from pathlib import Path

import openai
from pydantic import SecretStr

from app.config import settings
from app.tts.base import TTSProvider
from app.tts.errors import TTSError
from app.tts.schemas import TTSResult

logger = logging.getLogger("app.tts")


class OpenAITTSProvider(TTSProvider):
    """OpenAI speech synthesis (POST /v1/audio/speech). Paid: used as the backup of Groq."""

    name = "openai"

    def __init__(
        self,
        api_key: SecretStr | None = None,
        model: str | None = None,
        voice: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        key = api_key if api_key is not None else settings.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise TTSError("OPENAI_API_KEY is not set")
        self.model = model or settings.openai_tts_model
        self.voice = voice or settings.openai_tts_voice
        self._timeout_seconds = timeout_seconds or settings.tts_timeout_seconds
        # SDK retries are off so the timeout is a real upper bound per call.
        self._client = openai.OpenAI(api_key=key.get_secret_value(), timeout=self._timeout_seconds, max_retries=0)

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        if not text.strip():
            raise TTSError("Cannot synthesize empty text")

        started = time.perf_counter()
        try:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with self._client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="wav",
            ) as response:
                response.stream_to_file(out)
        except openai.APITimeoutError as exc:
            raise TTSError(f"OpenAI speech request timed out after {self._timeout_seconds}s") from exc
        except openai.AuthenticationError as exc:
            raise TTSError("OpenAI rejected the API key", status_code=401) from exc
        except openai.APIStatusError as exc:
            raise TTSError(f"OpenAI speech API error (HTTP {exc.status_code})", status_code=exc.status_code) from exc
        except openai.APIError as exc:
            raise TTSError(f"OpenAI speech request failed: {type(exc).__name__}") from exc
        except OSError as exc:
            raise TTSError(f"Cannot write audio file: {exc.strerror or type(exc).__name__}") from exc
        finally:
            logger.info(
                "tts provider=openai model=%s voice=%s latency=%.3fs",
                self.model,
                self.voice,
                time.perf_counter() - started,
            )

        return TTSResult(audio_path=str(output_path), provider=self.name, from_cache=False)
