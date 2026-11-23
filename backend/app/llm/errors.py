class LLMError(Exception):
    """Base class for all errors raised by the LLM layer.

    ``code`` is a stable identifier the frontend can translate, ``user_message``
    is a plain-language explanation safe to show to end users (no provider names,
    keys or stack details), and ``status_code`` is the HTTP status the API returns.
    """

    code = "ai_unavailable"
    status_code = 503
    user_message = "El tutor de IA no está disponible en este momento. Inténtalo de nuevo en unos minutos."


class LLMAuthError(LLMError):
    """The provider rejected the API key (or none is configured). Never retried."""

    code = "ai_misconfigured"
    status_code = 503
    user_message = "El tutor de IA no está disponible por un problema de configuración nuestro. Ya estamos en ello."


class LLMRateLimitError(LLMError):
    """Quota or rate limit exceeded. Never retried."""

    code = "ai_busy"
    status_code = 429
    user_message = "El tutor de IA está recibiendo muchas solicitudes ahora mismo. Espera un minuto e inténtalo otra vez."


class LLMTimeoutError(LLMError):
    """The provider did not answer within the configured timeout."""

    code = "ai_slow"
    status_code = 504
    user_message = "El tutor de IA tardó demasiado en responder. Inténtalo de nuevo."


class LLMProviderError(LLMError):
    """Any other transport or server-side failure."""

    code = "ai_unavailable"
    status_code = 502
    user_message = "No pudimos comunicarnos con el tutor de IA. Inténtalo de nuevo en unos minutos."


class LLMOutputError(LLMError):
    """The model never produced output matching the requested schema."""

    code = "ai_bad_answer"
    status_code = 502
    user_message = "El tutor de IA no pudo preparar una respuesta válida esta vez. Inténtalo de nuevo."

    def __init__(self, message: str, *, last_error: str, attempts: int) -> None:
        super().__init__(message)
        self.last_error = last_error
        self.attempts = attempts
