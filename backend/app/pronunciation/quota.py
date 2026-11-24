"""Monthly audio quota of the free Azure Speech plan (F0), kept in the database.

The F0 plan gives 5 hours of audio per month, shared with speech recognition, and unused time does
not carry over. We count the seconds we send; before a call, if sending this audio would cross the
limit minus a safety margin, the call is not made and the analysis is stored as ``skipped_quota``.
The margin covers what the counter cannot see: audio sent outside the app (smoke tests, other
tools) and rounding on Azure's side.
"""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AzureSpeechUsage

F0_MONTHLY_AUDIO_SECONDS = 5 * 60 * 60
# Stop this much before the real limit (30 minutes).
QUOTA_SAFETY_MARGIN_SECONDS = 30 * 60
USABLE_MONTHLY_SECONDS = F0_MONTHLY_AUDIO_SECONDS - QUOTA_SAFETY_MARGIN_SECONDS


def month_key(now: datetime | None = None) -> str:
    """Calendar month in UTC, "YYYY-MM"."""
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m")


async def seconds_used(db: AsyncSession, now: datetime | None = None) -> float:
    row = await db.get(AzureSpeechUsage, month_key(now))
    return float(row.seconds) if row is not None else 0.0


async def can_spend(db: AsyncSession, seconds: float, now: datetime | None = None) -> bool:
    """True if sending ``seconds`` more audio stays within the usable part of the monthly quota."""
    return await seconds_used(db, now) + seconds <= USABLE_MONTHLY_SECONDS


async def record_usage(db: AsyncSession, seconds: float, now: datetime | None = None) -> None:
    """Add ``seconds`` to this month's counter (atomic increment) and commit."""
    if seconds <= 0:
        return
    key = month_key(now)
    increment = update(AzureSpeechUsage).where(AzureSpeechUsage.month == key).values(seconds=AzureSpeechUsage.seconds + seconds)
    if (await db.execute(increment)).rowcount == 0:
        db.add(AzureSpeechUsage(month=key, seconds=seconds))
        try:
            await db.flush()
        except IntegrityError:  # another task created this month's row first
            await db.rollback()
            await db.execute(increment)
    await db.commit()
