class PronunciationError(Exception):
    """Any pronunciation-scoring failure. ``code`` is a short, safe string stored in turn_analyses.error.

    ``audio_processed`` says whether the provider may already have consumed the audio (and so the
    free quota) when this error happened. Messages never contain the API key.
    """

    code = "pronunciation_error"
    audio_processed = False

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code


class PronunciationNotConfiguredError(PronunciationError):
    code = "not_configured"


class PronunciationAuthError(PronunciationError):
    """Bad or missing key (401/403): retrying will not help."""

    code = "azure_auth"


class PronunciationRateLimitError(PronunciationError):
    """HTTP 429: too many requests; worth retrying later."""

    code = "azure_busy"


class PronunciationProviderError(PronunciationError):
    """HTTP 503 and other 5xx, or a network failure: worth retrying later."""

    code = "azure_unavailable"


class PronunciationTimeoutError(PronunciationError):
    """The request timed out; Azure may have processed the audio, so it counts toward the quota."""

    code = "azure_timeout"
    audio_processed = True


class PronunciationAudioError(PronunciationError):
    """The audio could not be prepared (unreadable, or ffmpeg is missing). Nothing was sent."""

    code = "bad_audio"


class PronunciationNoSpeechError(PronunciationError):
    """Azure processed the audio but recognised no speech to assess (NoMatch, silence...)."""

    code = "no_speech"
    audio_processed = True
