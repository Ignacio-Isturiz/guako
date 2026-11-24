"""Small helpers shared by the provider adapters."""


def retry_after_seconds(exc: Exception) -> float | None:
    """Seconds the provider asks us to wait (``retry-after`` header of a 429), if it sent one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None
