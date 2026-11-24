"""Retry of analyses left ``pending`` because every provider was out (breaker open, quota, budget).

Nobody else re-runs a pending row: the report only queues rows that did not exist. This loop, started with
the API process, picks the pending ones up again every few minutes. A row still pending after
EXPIRE_AFTER is given up as ``failed`` (error ``expired``) so it does not wait for ever.

Limit: one process. Two workers would both try the same rows (the in-flight guard of the runner is per
process); harmless but wasteful.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.runner import run_turn_analysis
from app.db import TurnAnalysis
from app.enums import AnalysisStatus
from app.llm.base import LLMProvider
from app.pronunciation import PronunciationProvider

logger = logging.getLogger("app.analysis")

RETRY_INTERVAL_SECONDS = 300.0
# Do not touch a row that was just queued: its own background task is probably still running.
MIN_AGE_SECONDS = 120.0
BATCH_SIZE = 20
EXPIRE_AFTER = timedelta(hours=24)


async def retry_pending_once(
    maker: async_sessionmaker[AsyncSession],
    llm: LLMProvider,
    pronunciation: PronunciationProvider | None,
    *,
    now: datetime | None = None,
) -> int:
    """One pass: expire the very old rows, re-run the oldest pending turns. Returns how many turns were retried."""
    now = now or datetime.now(UTC)
    async with maker() as db:
        await db.execute(
            update(TurnAnalysis)
            .where(TurnAnalysis.status == AnalysisStatus.PENDING.value, TurnAnalysis.created_at < now - EXPIRE_AFTER)
            .values(status=AnalysisStatus.FAILED.value, error="expired")
        )
        await db.commit()
        turn_ids = (
            await db.scalars(
                select(TurnAnalysis.turn_id)
                .where(TurnAnalysis.status == AnalysisStatus.PENDING.value, TurnAnalysis.created_at < now - timedelta(seconds=MIN_AGE_SECONDS))
                .group_by(TurnAnalysis.turn_id)
                .order_by(func.min(TurnAnalysis.created_at))
                .limit(BATCH_SIZE)
            )
        ).all()
    for turn_id in turn_ids:
        await run_turn_analysis(turn_id, llm, maker, pronunciation)
    if turn_ids:
        logger.info("analysis_retry turns=%d", len(turn_ids))
    return len(turn_ids)


async def run_retrier(maker: async_sessionmaker[AsyncSession], get_llm, get_pronunciation, interval: float = RETRY_INTERVAL_SECONDS) -> None:
    """Background loop of the API process. ``get_llm`` / ``get_pronunciation`` build the providers on each pass."""
    while True:
        await asyncio.sleep(interval)
        try:
            await retry_pending_once(maker, get_llm(), get_pronunciation())
        except Exception:
            logger.exception("analysis_retry_failed")
