class TTSError(Exception):
    """Raised for any text-to-speech failure.

    Covers missing configuration, API errors, timeouts and local synthesis
    problems. ``status_code`` carries the HTTP status when the failure came
    from an API response (e.g. 429 for rate limits). The message never
    contains the API key.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
