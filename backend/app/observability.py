"""Tracing with Langfuse: what each turn and each analysis did, step by step, with models, tokens, costs and times.

The rest of the app only talks to this module. Without the keys (tests, a fresh clone) every function here
is a no-op and nothing is sent: the app never depends on Langfuse, and a failure inside it never reaches a
request. It only OBSERVES: budgets, caps and fallbacks stay in app.providers.

What leaves the process:
- ids only for people (session and user ids, never names or emails);
- the text of prompts, transcripts and answers only while ``langfuse_capture_content`` is on, and always
  through ``_mask`` (emails and phone numbers);
- never audio.

Shape of the data (see the Langfuse UI, Sessions and Traces):
    session (one conversation)
     ├─ trace "turno"     -> one generation per provider attempt (stt, llm, tts)
     └─ trace "analisis"  -> one span per dimension (fluency, grammar, judge...) -> its generations, + scores
"""

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import settings

logger = logging.getLogger("app.observability")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")

_client: Any = None  # the Langfuse client, created on first use; False = tracing off
_failed_once = False


def _mask(*, data: Any, **_: Any) -> Any:
    """Applied by the SDK to every input, output and metadata before it is sent."""
    if isinstance(data, str):
        return _PHONE.sub("[telefono]", _EMAIL.sub("[email]", data))
    if isinstance(data, dict):
        return {key: _mask(data=value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask(data=value) for value in data]
    return data


def _get() -> Any:
    """The client, or None when tracing is off."""
    global _client
    if _client is None:
        if not settings.langfuse_enabled:
            _client = False
        else:
            try:
                from langfuse import Langfuse

                _client = Langfuse(
                    public_key=settings.langfuse_public_key.get_secret_value(),  # type: ignore[union-attr]
                    secret_key=settings.langfuse_secret_key.get_secret_value(),  # type: ignore[union-attr]
                    base_url=settings.langfuse_base_url,
                    environment=settings.langfuse_environment,
                    sample_rate=settings.langfuse_sample_rate,
                    mask=_mask,
                )
            except Exception:
                logger.exception("langfuse_init_failed: tracing stays off")
                _client = False
    return _client or None


def enabled() -> bool:
    return _get() is not None


def _safe(action: str, fn: Any, **kwargs: Any) -> None:
    """Tracing must never break a request: errors are logged once and swallowed."""
    global _failed_once
    try:
        fn(**kwargs)
    except Exception:
        if not _failed_once:
            _failed_once = True
            logger.exception("langfuse_%s_failed (further errors are not logged)", action)


@contextmanager
def trace(
    name: str,
    *,
    session_id: int | None = None,
    user_id: int | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    """The root of one trace. Everything traced inside (also in worker threads) hangs from it."""
    client = _get()
    if client is None:
        yield
        return
    from langfuse import propagate_attributes

    with (
        client.start_as_current_observation(name=name, as_type="span", metadata=metadata),
        propagate_attributes(
            trace_name=name,
            session_id=str(session_id) if session_id is not None else None,
            user_id=str(user_id) if user_id is not None else None,
            tags=tags,
        ),
    ):
        yield


@contextmanager
def span(name: str, **metadata: Any) -> Iterator["_Observation"]:
    """One step inside a trace (a node of the analysis graph, for instance)."""
    client = _get()
    if client is None:
        yield _Observation(None)
        return
    with client.start_as_current_observation(name=name, as_type="span", metadata=metadata or None) as obs:
        yield _Observation(obs)


class _Observation:
    """What the callers may do with an open span or generation; a no-op when tracing is off."""

    def __init__(self, obs: Any) -> None:
        self._obs = obs

    def update(self, **kwargs: Any) -> None:
        if self._obs is not None:
            _safe("update", self._obs.update, **kwargs)

    def failed(self, kind: str) -> None:
        """A provider attempt that did not answer (429, timeout, invalid output...): the router moves on."""
        self.update(level="WARNING", status_message=kind)

    def succeeded(self, *, prompt_tokens: int, completion_tokens: int, cost: float, metadata: dict[str, Any]) -> None:
        usage = {"input": prompt_tokens, "output": completion_tokens} if prompt_tokens or completion_tokens else None
        self.update(usage_details=usage, cost_details={"total": cost}, metadata=metadata)


@contextmanager
def provider_call(
    capability: str,
    use: str,
    provider: str,
    model: str,
    *,
    fallback_from: str | None,
    skipped: list[str],
) -> Iterator[_Observation]:
    """One attempt of the ProviderRouter on one provider, as a Langfuse generation (model, tokens, cost)."""
    client = _get()
    if client is None:
        yield _Observation(None)
        return
    metadata = {"provider": provider, "use": use, "fallback_from": fallback_from, "skipped": skipped or None}
    with client.start_as_current_observation(
        name=f"{capability}:{provider}",
        as_type="generation",
        model=model,
        metadata={k: v for k, v in metadata.items() if v is not None},
    ) as obs:
        yield _Observation(obs)


def record_io(*, input: Any = None, output: Any = None) -> None:  # noqa: A002
    """Input and output of the provider call in progress (only while capture_content is on)."""
    client = _get()
    if client is None or not settings.langfuse_capture_content:
        return
    if hasattr(output, "model_dump"):
        output = output.model_dump()
    kwargs = {k: v for k, v in {"input": input, "output": output}.items() if v is not None}
    if kwargs:
        _safe("record_io", client.update_current_generation, **kwargs)


def score(name: str, value: float, *, comment: str | None = None) -> None:
    """A score on the current trace (the judges' marks, the number of grammar errors...)."""
    client = _get()
    if client is not None:
        if client.get_current_trace_id() is None:  # outside a trace (a script, a test): nothing to attach it to
            return
        _safe("score", client.score_current_trace, name=name, value=float(value), comment=comment)


def flush() -> None:
    """Send what is queued now (scripts that end right after their work)."""
    client = _get()
    if client is not None:
        _safe("flush", client.flush)


def shutdown() -> None:
    """At process exit: sends the last batch. Without it the last traces are lost."""
    client = _get()
    if client is not None:
        _safe("shutdown", client.shutdown)


def forget_user(user_id: int) -> None:
    """Delete every trace of a learner from Langfuse (their account was deleted: Law 1581 "supresión").

    Finds the traces through the learner's observations (all of them carry the user id) and deletes them in
    batches. Blocking network calls: run it in the background. Like everything here, a failure is logged and
    swallowed; a trace still being ingested at that moment can escape and is caught by Langfuse's retention.
    """
    client = _get()
    if client is None:
        return

    def run() -> None:
        client.flush()  # what is still queued for this learner goes out first, so it can be found
        trace_ids: set[str] = set()
        cursor: str | None = None
        while True:
            page = client.api.observations.get_many(user_id=str(user_id), fields="core", limit=100, cursor=cursor)
            trace_ids.update(obs.trace_id for obs in page.data if obs.trace_id)
            cursor = page.meta.cursor
            if not cursor or not page.data:
                break
        ids = sorted(trace_ids)
        for start in range(0, len(ids), 100):
            client.api.trace.delete_multiple(trace_ids=ids[start : start + 100])
        logger.info("langfuse_forget_user user=%s traces=%d", user_id, len(ids))

    _safe("forget_user", run)
