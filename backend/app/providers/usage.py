"""Usage persistence: flush the in-memory counters to the database, restore them at startup, prune the log.

The router records every call in memory (thread-safe, see state.py); these coroutines move it to
``provider_usage`` (daily totals) and ``provider_calls`` (one row per call, 30 days).
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import ProviderCall, ProviderUsage
from app.providers.state import ProviderState

logger = logging.getLogger("app.providers")

FLUSH_INTERVAL_SECONDS = 10.0
CALL_LOG_RETENTION_DAYS = 30
_PRUNE_EVERY_FLUSHES = 360  # about hourly


async def flush_usage(maker: async_sessionmaker[AsyncSession], state: ProviderState) -> int:
    """Write what was recorded since the last flush; on failure keep it for the next one. Returns the calls written."""
    agg, calls = state.drain()
    if not agg and not calls:
        return 0
    try:
        async with maker() as db:
            for (day, provider, capability, use), v in agg.items():
                row = await db.get(ProviderUsage, (day, provider, capability, use))
                if row is None:
                    db.add(ProviderUsage(day=day, provider=provider, capability=capability, use=use, **v))
                    continue
                for name, value in v.items():
                    setattr(row, name, getattr(row, name) + value)
            db.add_all(ProviderCall(**c) for c in calls)
            await db.commit()
    except Exception:  # never break the app over bookkeeping
        state.put_back(agg, calls)
        logger.exception("usage_flush_failed calls=%d", len(calls))
        return 0
    return len(calls)


async def load_baseline(maker: async_sessionmaker[AsyncSession], state: ProviderState) -> None:
    """Today's request counters (for the daily caps) and the period's spending (for the budget)."""
    async with maker() as db:
        rows = (
            await db.execute(
                select(ProviderUsage.provider, ProviderUsage.capability, func.sum(ProviderUsage.requests))
                .where(ProviderUsage.day == state.today())
                .group_by(ProviderUsage.provider, ProviderUsage.capability)
            )
        ).all()
        spent_query = select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0.0))
        start = state.budget.period_start()
        if start is not None:
            spent_query = spent_query.where(ProviderUsage.day >= start)
        spent = float(await db.scalar(spent_query) or 0.0)
    state.load_baseline({(p, c): int(n or 0) for p, c, n in rows}, spent)
    logger.info("usage_baseline spent_usd=%.4f period=%s counters=%d", spent, state.budget.period, len(rows))


async def prune_calls(maker: async_sessionmaker[AsyncSession], days: int = CALL_LOG_RETENTION_DAYS) -> None:
    async with maker() as db:
        await db.execute(delete(ProviderCall).where(ProviderCall.created_at < datetime.now(UTC) - timedelta(days=days)))
        await db.commit()


async def run_flusher(maker: async_sessionmaker[AsyncSession], state: ProviderState, interval: float = FLUSH_INTERVAL_SECONDS) -> None:
    """Background loop of the API process: flush every few seconds, prune the call log about once an hour."""
    ticks = 0
    while True:
        await asyncio.sleep(interval)
        await flush_usage(maker, state)
        ticks += 1
        if ticks % _PRUNE_EVERY_FLUSHES == 0:
            try:
                await prune_calls(maker)
            except Exception:
                logger.exception("provider_calls_prune_failed")


async def usage_for_day(db: AsyncSession, day: date) -> list[dict]:
    """The rows of provider_usage for one day, ready for the admin endpoint."""
    rows = (
        await db.scalars(
            select(ProviderUsage)
            .where(ProviderUsage.day == day)
            .order_by(ProviderUsage.capability, ProviderUsage.use, ProviderUsage.provider)
        )
    ).all()
    return [
        {
            "provider": r.provider, "capability": r.capability, "use": r.use, "requests": r.requests,
            "successes": r.successes, "failures": r.failures, "rate_limited": r.rate_limited,
            "as_fallback": r.as_fallback, "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
            "audio_seconds_in": round(r.audio_seconds_in, 1), "audio_seconds_out": round(r.audio_seconds_out, 1),
            "chars": r.chars, "cost_usd": round(r.cost_usd, 6),
        }
        for r in rows
    ]  # fmt: skip
