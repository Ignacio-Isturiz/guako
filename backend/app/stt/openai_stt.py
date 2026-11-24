import logging
import time
from pathlib import Path

import openai
from pydantic import SecretStr

from app.config import settings
from app.providers.util import retry_after_seconds
from app.stt.base import STTProvider
from app.stt.errors import STTError
from app.stt.groq import SUPPORTED_EXTENSIONS
from app.stt.schemas import TranscriptionResult
from app.stt.verbose_json import to_result

logger = logging.getLogger("app.stt")


class OpenAIWhisperSTTProvider(STTProvider):
    """OpenAI Whisper (``whisper-1``). Paid: the backup of Groq.

    It has to be whisper-1: fluency and pronunciation need the word timestamps, and the context prompt is
    what keeps a mispronounced word from becoming another one.
    """

    name = "openai"

    def __init__(
        self,
        api_key: SecretStr | None = None,
        model: str | None = None,
        *,
        timeout_seconds: float | None = None,
        client: openai.OpenAI | None = None,
    ) -> None:
        key = api_key if api_key is not None else settings.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise STTError("OPENAI_API_KEY is not set", kind="auth")
        self.model = model or settings.openai_stt_model
        self._timeout_seconds = timeout_seconds or settings.stt_timeout_seconds
        # SDK retries are off so the timeout is a real upper bound and a 429 surfaces to the router.
        self._client = client or openai.OpenAI(api_key=key.get_secret_value(), timeout=self._timeout_seconds, max_retries=0)

    def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
        path = Path(audio_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise STTError(f"Unsupported audio format '{path.suffix}'", kind="invalid_input")

        started = time.perf_counter()
        try:
            response = self._client.audio.transcriptions.create(
                file=(path.name, path.read_bytes()),
                model=self.model,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],  # segments carry the confidence
                **({"language": settings.stt_language} if settings.stt_language else {}),
                **({"prompt": context.strip()[-600:]} if context and context.strip() else {}),
            )
        except OSError as exc:
            raise STTError(f"Cannot read audio file '{path.name}': {exc.strerror or type(exc).__name__}", kind="invalid_input") from exc
        except openai.APITimeoutError as exc:
            raise STTError(f"OpenAI transcription timed out after {self._timeout_seconds}s", kind="timeout") from exc
        except openai.AuthenticationError as exc:
            raise STTError("OpenAI rejected the API key", status_code=401, kind="auth") from exc
        except openai.APIStatusError as exc:
            raise STTError(
                f"OpenAI API error (HTTP {exc.status_code})", status_code=exc.status_code, retry_after=retry_after_seconds(exc)
            ) from exc
        except openai.APIError as exc:
            raise STTError(f"OpenAI request failed: {type(exc).__name__}") from exc
        finally:
            logger.info("stt provider=openai model=%s file=%s latency=%.3fs", self.model, path.name, time.perf_counter() - started)

        return to_result(response.model_dump(), "OpenAI")
