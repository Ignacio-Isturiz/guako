"""Background analysis of saved turns (grammar with the LLM, fluency with code).

Runs after the turn is saved and the voice reply has been sent, so it adds no latency to the reply.
It never raises: a failed analysis is stored as ``failed`` and the session carries on.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterable

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.fluency import analyze_fluency
from app.analysis.grammar import analyze_grammar
from app.db import Turn, TurnAnalysis
from app.enums import AnalysisDimension, AnalysisStatus
from app.llm.base import LLMProvider
from app.llm.errors import LLMError, LLMProviderError, LLMRateLimitError, LLMTimeoutError
from app.stt import WordTiming

logger = logging.getLogger("app.analysis")

# Rate limit (429), overload (503 and other 5xx) and timeouts are worth waiting for; a bad key or an
# unusable answer is not. Waits grow ×3 between attempts: 4 attempts in total.
RETRYABLE = (LLMRateLimitError, LLMProviderError, LLMTimeoutError)
RETRY_WAITS_SECONDS = (2.0, 6.0, 18.0)

# One LLM call at a time for the whole process: the free quotas are tiny and analyses must not
# compete with the tutor's own replies. Held per attempt, not while waiting to retry.
_LLM_SLOT = threading.Semaphore(1)

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


async def run_turn_analysis(turn_id: int, llm: LLMProvider, maker: async_sessionmaker[AsyncSession]) -> None:
    """Analyse one turn: every ``pending`` row is finished as ``done`` or ``failed``; others are left alone."""
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
            # Fluency first: it is instant and does not depend on the LLM.
            for row in sorted(rows, key=lambda r: r.dimension != AnalysisDimension.FLUENCY.value):
                await _finish(db, row, turn, llm)
    except Exception:  # background task: nothing may escape
        logger.exception("analysis_crashed turn=%s", turn_id)
    finally:
        _IN_FLIGHT.discard(turn_id)


async def _finish(db: AsyncSession, row: TurnAnalysis, turn: Turn, llm: LLMProvider) -> None:
    try:
        if row.dimension == AnalysisDimension.FLUENCY.value:
            words = [WordTiming.model_validate(w) for w in (turn.word_timestamps or [])]
            row.result = analyze_fluency(words)
        elif not turn.user_transcript.strip():
            row.result = {"errors": [], "discarded_low_confidence": 0}  # nothing said, nothing to ask the LLM
        else:
            row.result = await run_in_threadpool(_generate_with_backoff, llm, turn.user_transcript)
        row.status, row.error = AnalysisStatus.DONE.value, None
    except Exception as exc:
        code = exc.code if isinstance(exc, LLMError) else type(exc).__name__
        logger.warning("analysis_failed turn=%s dimension=%s error=%s", turn.id, row.dimension, code)
        row.status, row.result, row.error = AnalysisStatus.FAILED.value, None, str(code)[:200]
    await db.commit()
