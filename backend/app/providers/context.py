"""Who a provider call is for (session and turn), so provider_calls can say which provider served what.

A ContextVar: it follows the request into worker threads (anyio copies it) and each background task sets
its own. Nothing here is sensitive: only ids.
"""

from contextvars import ContextVar

_context: ContextVar[dict] = ContextVar("provider_call_context", default={})


def set_call_context(*, session_id: int | None = None, turn_id: int | None = None) -> None:
    _context.set({"session_id": session_id, "turn_id": turn_id})


def get_call_context() -> dict:
    return _context.get()
