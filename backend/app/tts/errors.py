class TTSError(Exception):
    """Raised for any text-to-speech failure.

    Covers missing configuration, API errors, timeouts and local synthesis
    problems. ``status_code`` carries the HTTP status when the failure came
    from an API response (e.g. 429 for rate limits). The message never
    contains the API key.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        # Seconds the provider asked us to wait (429), and the cause when the status does not say it
        # ("timeout", "auth", "invalid_input"): the provider router decides from these.
        self.retry_after = retry_after
        self.kind = kind
