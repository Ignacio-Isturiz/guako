"""Building blocks of the background analysis of saved turns, and the entry point that runs it.

Runs after the turn is saved and the voice reply has been sent, so it adds no latency to the reply.
It never raises: a failed analysis is stored as ``failed`` and the session carries on.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import observability
from app.analysis.grammar import analyze_grammar
from app.analysis.judge import judge_turn
from app.analysis.pronunciation import empty_result, plan_assessment, stored_result
from app.db import ConversationSession, Turn, TurnAnalysis
from app.enums import AnalysisDimension, AnalysisStatus
from app.llm.base import LLMProvider
from app.llm.errors import LLMProviderError, LLMRateLimitError, LLMTimeoutError
from app.providers.errors import LLMExhausted
from app.pronunciation import PronunciationError, PronunciationProvider, PronunciationResult
from app.pronunciation.errors import (
    PronunciationNotConfiguredError,
    PronunciationProviderError,
    PronunciationRateLimitError,
    PronunciationTimeoutError,
)
from app.pronunciation.quota import can_spend, record_usage

logger = logging.getLogger("app.analysis")

# Rate limit (429), overload (503 and other 5xx) and timeouts are worth waiting for; a bad key or an
# unusable answer is not. Waits grow ×3 between attempts: 4 attempts in total.
RETRYABLE = (LLMRateLimitError, LLMProviderError, LLMTimeoutError)
RETRY_WAITS_SECONDS = (2.0, 6.0, 18.0)

# Azure's 429 and 503 (and timeouts) are retried with the same growing waits as the LLM.
PRONUNCIATION_RETRYABLE = (PronunciationRateLimitError, PronunciationProviderError, PronunciationTimeoutError)

# One LLM call at a time for the whole process: the free quotas are tiny and analyses must not
# compete with the tutor's own replies. Held per attempt, not while waiting to retry.
_LLM_SLOT = threading.Semaphore(1)

# One Azure call at a time too (free plan: tiny quota, and one concurrent request is plenty).
_AZURE_SLOT = threading.Semaphore(1)

# Turn ids being analysed in this process: two runs for the same turn never overlap.
_IN_FLIGHT: set[int] = set()

# Replaceable in tests so the backoff does not really wait.
_sleep: Callable[[float], None] = time.sleep


def _generate_with_backoff(llm: LLMProvider, transcript: str, context: str = "") -> dict:
    """Runs in a worker thread (the providers are blocking)."""
    for attempt, wait in enumerate((*RETRY_WAITS_SECONDS, None), start=1):
        try:
            with _LLM_SLOT:
                return analyze_grammar(llm, transcript, context)
        except RETRYABLE as exc:
            # Every provider is out (the router already tried them all and its breakers are open): waiting
            # a few seconds here would not help. The row stays pending and the retrier picks it up later.
            if wait is None or isinstance(exc, LLMExhausted):
                raise
            logger.warning("analysis_retry attempt=%d wait_s=%.0f error=%s", attempt, wait, type(exc).__name__)
            _sleep(wait)
    raise AssertionError("unreachable")


def _judge_with_backoff(llm: LLMProvider, ctx: dict, want_listening: bool, intended: dict | None) -> dict:
    """Runs in a worker thread. Same policy as the grammar: growing waits, and no waiting when every provider is out."""
    for attempt, wait in enumerate((*RETRY_WAITS_SECONDS, None), start=1):
        try:
            with _LLM_SLOT:
                return judge_turn(llm, ctx, want_listening, intended)
        except RETRYABLE as exc:
            if wait is None or isinstance(exc, LLMExhausted):
                raise
            logger.warning("judge_retry attempt=%d wait_s=%.0f error=%s", attempt, wait, type(exc).__name__)
            _sleep(wait)
    raise AssertionError("unreachable")


def _score_with_backoff(
    provider: PronunciationProvider,
    audio_path: str,
    reference_text: str,
    attempts_with_audio: list[int],
    waits: tuple[float, ...] = RETRY_WAITS_SECONDS,
) -> PronunciationResult:
    """Runs in a worker thread. ``attempts_with_audio`` gets one item per attempt that may have used
    up quota (a success, a timeout...); attempts Azure refused (429/503) or that never left the
    machine are not counted."""
    for attempt, wait in enumerate((*waits, None), start=1):
        try:
            with _AZURE_SLOT:
                result = provider.score_turn(audio_path, reference_text)
            attempts_with_audio.append(attempt)
            return result
        except PronunciationError as exc:
            if exc.audio_processed:
                attempts_with_audio.append(attempt)
            if not isinstance(exc, PRONUNCIATION_RETRYABLE) or wait is None:
                raise
            logger.warning("pronunciation_retry attempt=%d wait_s=%.0f error=%s", attempt, wait, exc.code)
            _sleep(wait)
    raise AssertionError("unreachable")


async def ensure_pending_rows(db: AsyncSession, turn_ids: Iterable[int]) -> list[int]:
    """Create the missing (turn, dimension) rows as ``pending``; returns the turns that got new rows.

    Does not commit: the caller commits (the turn endpoint does it together with the turn itself).
    """
    ids = list(turn_ids)
    existing = set(
        (await db.execute(select(TurnAnalysis.turn_id, TurnAnalysis.dimension).where(TurnAnalysis.turn_id.in_(ids)))).all()
    )
    created: list[int] = []
    for turn_id in ids:
        for dimension in AnalysisDimension:
            if (turn_id, dimension.value) not in existing:
                db.add(TurnAnalysis(turn_id=turn_id, dimension=dimension.value, status=AnalysisStatus.PENDING.value))
                if turn_id not in created:
                    created.append(turn_id)
    return created


async def run_turn_analysis(
    turn_id: int,
    llm: LLMProvider,
    maker: async_sessionmaker[AsyncSession],
    pronunciation: PronunciationProvider | None = None,
) -> None:
    """Analyse one turn: every ``pending`` row is finished (done, failed or skipped); others are left alone.

    The work itself is the graph in ``app.analysis.graph`` (what runs, in what order, what in parallel);
    this module keeps the building blocks it calls (retries, quota, pronunciation) and the in-flight guard.
    ``pronunciation`` is None when Azure is not configured: that dimension then fails with ``not_configured``.
    """
    from app.analysis.graph import build_analysis_graph  # imported here: graph.py uses this module's blocks

    if turn_id in _IN_FLIGHT:
        return
    _IN_FLIGHT.add(turn_id)
    try:
        session_id, user_id = await _owner(maker, turn_id) if observability.enabled() else (None, None)
        # Its own trace (the turn's one closed when the response was sent), in the same Langfuse session.
        with observability.trace(
            "analisis", session_id=session_id, user_id=user_id, tags=["analisis"], metadata={"turn_id": turn_id}
        ):
            await build_analysis_graph(maker, llm, pronunciation).ainvoke({"turn_id": turn_id})
    except Exception:  # background task: nothing may escape
        logger.exception("analysis_crashed turn=%s", turn_id)
    finally:
        _IN_FLIGHT.discard(turn_id)


async def _owner(maker: async_sessionmaker[AsyncSession], turn_id: int) -> tuple[int | None, int | None]:
    """Session and user of a turn, to file its analysis trace under the right conversation."""
    async with maker() as db:
        row = (
            await db.execute(
                select(ConversationSession.id, ConversationSession.user_id)
                .join(Turn, Turn.session_id == ConversationSession.id)
                .where(Turn.id == turn_id)
            )
        ).first()
    return (row[0], row[1]) if row else (None, None)


async def _previous_tutor_text(db: AsyncSession, turn: Turn) -> str:
    """What Guako said right before this turn (context for telling which words were misrecognised)."""
    reply = await db.scalar(
        select(Turn.reply_text).where(Turn.session_id == turn.session_id, Turn.turn_number == turn.turn_number - 1)
    )
    return reply or ""


async def _intended(db: AsyncSession, turn: Turn) -> dict | None:
    """What the learner meant, from the grammar analysis, if it is done and found a recognition fix."""
    result = await db.scalar(
        select(TurnAnalysis.result).where(
            TurnAnalysis.turn_id == turn.id,
            TurnAnalysis.dimension == AnalysisDimension.GRAMMAR.value,
            TurnAnalysis.status == AnalysisStatus.DONE.value,
        )
    )
    if not result or not result.get("intended_text"):
        return None
    return {"text": result["intended_text"], "fixes": result.get("heard_fixes", [])}


async def _assess_pronunciation(
    db: AsyncSession, turn: Turn, provider: PronunciationProvider | None, intended: dict | None = None
) -> tuple[str, dict | None, str | None]:
    """(status, result, error) of the pronunciation analysis of one turn."""
    if not turn.user_audio_path or not Path(turn.user_audio_path).is_file():
        return AnalysisStatus.SKIPPED_NO_AUDIO.value, None, None  # no consent, or consent withdrawn
    if not turn.user_transcript.strip():
        return AnalysisStatus.DONE.value, empty_result(), None  # nothing said: nothing to send
    if provider is None:
        raise PronunciationNotConfiguredError("Azure Speech is not configured")

    plan = plan_assessment(
        turn.user_transcript, turn.word_timestamps, turn.user_audio_seconds, provider.max_audio_seconds, intended
    )
    if plan is None:
        raise PronunciationError("turn is too long and has no word timings to cut it", code="audio_too_long")
    if not await can_spend(db, plan.audio_seconds):
        logger.info("pronunciation_skipped_quota turn=%s seconds=%.1f", turn.id, plan.audio_seconds)
        return AnalysisStatus.SKIPPED_QUOTA.value, None, None

    sent: list[int] = []
    try:
        result = await run_in_threadpool(_score_with_backoff, provider, turn.user_audio_path, plan.reference_text, sent)
    finally:
        await record_usage(db, len(sent) * plan.audio_seconds)  # also when it failed after Azure took the audio
    return AnalysisStatus.DONE.value, stored_result(result, plan), None
