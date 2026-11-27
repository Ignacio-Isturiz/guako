"""HTTP answers for speech failures (LLM failures are handled in app.llm.handlers)."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.stt.errors import NoSpeechError, STTError
from app.tts.errors import TTSError

logger = logging.getLogger("app.conversation")

# The provider answered "what you sent is wrong" (bad or unreadable audio), not "I am down"
_BAD_AUDIO_STATUSES = {400, 413, 415, 422}


def _body(code: str, message: str) -> dict:
    return {"detail": {"code": code, "message": message}}


async def _handle_stt_error(_: Request, exc: Exception) -> JSONResponse:
    # Technical detail stays in the log; the client gets a plain message.
    logger.error("stt_error type=%s detail=%s", type(exc).__name__, exc)
    if isinstance(exc, NoSpeechError):
        return JSONResponse(
            status_code=422,
            content=_body("no_speech", "No se escuchó nada en el audio. Inténtalo de nuevo hablando más cerca del micrófono."),
        )
    if exc.kind == "invalid_input" or exc.status_code in _BAD_AUDIO_STATUSES:
        # The provider rejected the recording itself: retrying the same audio will not help
        return JSONResponse(
            status_code=422,
            content=_body("audio_unreadable", "No pudimos leer tu grabación. Inténtalo de nuevo."),
        )
    return JSONResponse(
        status_code=503,
        content=_body("stt_unavailable", "No pudimos transcribir tu audio en este momento. Inténtalo de nuevo en unos minutos."),
    )


async def _handle_tts_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("tts_error type=%s detail=%s", type(exc).__name__, exc)
    return JSONResponse(
        status_code=503,
        content=_body("tts_unavailable", "No pudimos generar la voz del tutor en este momento. Inténtalo de nuevo en unos minutos."),
    )


def register_speech_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(STTError, _handle_stt_error)
    app.add_exception_handler(TTSError, _handle_tts_error)
