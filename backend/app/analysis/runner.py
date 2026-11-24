"""Background analysis of saved turns (grammar with the LLM, fluency with code).

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

from app.analysis.fluency import analyze_fluency
from app.analysis.grammar import analyze_grammar
from app.analysis.pronunciation import empty_result, plan_assessment, stored_result
from app.db import Turn, TurnAnalysis
from app.enums import AnalysisDimension, AnalysisStatus
from app.llm.base import LLMProvider
from app.llm.errors import LLMError, LLMProviderError, LLMRateLimitError, LLMTimeoutError
from app.pronunciation import PronunciationError, PronunciationProvider, PronunciationResult
from app.pronunciation.errors import (
    PronunciationNotConfiguredError,
    PronunciationProviderError,
    PronunciationRateLimitError,
    PronunciationTimeoutError,
)
from app.pronunciation.quota import can_spend, record_usage
from app.stt import WordTiming

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


def _generate_with_backoff(llm: LLMProvider, transcript: str) -> dict:
    """Runs in a worker thread (the providers are blocking)."""
    for attempt, wait in enumerate((*RETRY_WAITS_SECONDS, None), start=1):
        try:
            with _LLM_SLOT:
                return analyze_grammar(llm, transcript)
        except RETRYABLE as exc:
            if wait is None:
                raise
            logger.warning("analysis_retry attempt=%d wait_s=%.0f error=%s", attempt, wait, type(exc).__name__)
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

    ``pronunciation`` is None when Azure is not configured: that dimension then fails with ``not_configured``.
    """
    if turn_id in _IN_FLIGHT:
        return
    _IN_FLIGHT.add(turn_id)
    try:
        async with maker() as db:
            turn = await db.get(Turn, turn_id)
            rows = (
                await db.scalars(
                    select(TurnAnalysis).where(
                        TurnAnalysis.turn_id == turn_id, TurnAnalysis.status == AnalysisStatus.PENDING.value
                    )
                )
            ).all()
            if turn is None:
                return
            # Fluency first: it is instant and does not depend on any service.
            order = {AnalysisDimension.FLUENCY.value: 0, AnalysisDimension.PRONUNCIATION.value: 1}
            for row in sorted(rows, key=lambda r: order.get(r.dimension, 2)):
                await _finish(db, row, turn, llm, pronunciation)
    except Exception:  # background task: nothing may escape
        logger.exception("analysis_crashed turn=%s", turn_id)
    finally:
        _IN_FLIGHT.discard(turn_id)


async def _finish(
    db: AsyncSession, row: TurnAnalysis, turn: Turn, llm: LLMProvider, pronunciation: PronunciationProvider | None
) -> None:
    try:
        if row.dimension == AnalysisDimension.PRONUNCIATION.value:
            row.status, row.result, row.error = await _assess_pronunciation(db, turn, pronunciation)
        else:
            if row.dimension == AnalysisDimension.FLUENCY.value:
                words = [WordTiming.model_validate(w) for w in (turn.word_timestamps or [])]
                row.result = analyze_fluency(words)
            elif not turn.user_transcript.strip():
                row.result = {"errors": [], "discarded_low_confidence": 0}  # nothing said, nothing to ask the LLM
            else:
                row.result = await run_in_threadpool(_generate_with_backoff, llm, turn.user_transcript)
            row.status, row.error = AnalysisStatus.DONE.value, None
    except Exception as exc:
        code = exc.code if isinstance(exc, (LLMError, PronunciationError)) else type(exc).__name__
        logger.warning("analysis_failed turn=%s dimension=%s error=%s", turn.id, row.dimension, code)
        row.status, row.result, row.error = AnalysisStatus.FAILED.value, None, str(code)[:200]
    await db.commit()


async def _assess_pronunciation(
    db: AsyncSession, turn: Turn, provider: PronunciationProvider | None
) -> tuple[str, dict | None, str | None]:
    """(status, result, error) of the pronunciation analysis of one turn."""
    if not turn.user_audio_path or not Path(turn.user_audio_path).is_file():
        return AnalysisStatus.SKIPPED_NO_AUDIO.value, None, None  # no consent, or consent withdrawn
    if not turn.user_transcript.strip():
        return AnalysisStatus.DONE.value, empty_result(), None  # nothing said: nothing to send
    if provider is None:
        raise PronunciationNotConfiguredError("Azure Speech is not configured")

    plan = plan_assessment(turn.user_transcript, turn.word_timestamps, turn.user_audio_seconds, provider.max_audio_seconds)
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
