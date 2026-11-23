import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.llm.errors import LLMError

logger = logging.getLogger("app.llm")


async def _handle_llm_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LLMError)
    # The technical detail stays in the server log; the client gets a plain message.
    logger.error("llm_error type=%s detail=%s", type(exc).__name__, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": exc.user_message}},
    )


def register_llm_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LLMError, _handle_llm_error)
