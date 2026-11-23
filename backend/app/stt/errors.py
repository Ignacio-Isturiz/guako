class STTError(Exception):
    """Raised for any speech-to-text failure.

    Covers a missing API key, an unreadable file, an unsupported audio format,
    API errors and timeouts. The message never contains the API key.
    """
