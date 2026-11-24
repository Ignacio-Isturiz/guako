class STTError(Exception):
    """Raised for any speech-to-text failure.

    Covers a missing API key, an unreadable file, an unsupported audio format,
    API errors and timeouts. The message never contains the API key.

    ``status_code`` / ``retry_after`` come from the API response when there was one, and ``kind`` names the
    cause when the status does not ("timeout", "auth", "invalid_input"): the provider router uses them to
    decide whether to try the next provider.
    """

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.kind = kind


class NoSpeechError(STTError):
    """The audio was transcribed but contains no speech (silence or noise)."""
