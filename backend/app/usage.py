"""Daily audio usage: how many seconds a user has talked today (learner + tutor audio)."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ConversationSession, Streak, Turn


def day_window_utc(now: datetime, tz_name: str) -> tuple[datetime, datetime]:
    """[start, end) of the user's current calendar day, expressed in UTC."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    today = now.astimezone(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


async def seconds_used_today(db: AsyncSession, user_id: int, *, now: datetime | None = None) -> float:
    """Audio seconds the user spent today. The day follows their last known time zone
    (the one the streak stores), so it rolls over at their midnight, not the server's."""
    streak = await db.get(Streak, user_id)
    start, end = day_window_utc(now or datetime.now(UTC), streak.timezone if streak else "UTC")
    total = await db.scalar(
        select(func.coalesce(func.sum(Turn.user_audio_seconds + Turn.reply_audio_seconds), 0.0))
        .join(ConversationSession, Turn.session_id == ConversationSession.id)
        .where(ConversationSession.user_id == user_id, Turn.created_at >= start, Turn.created_at < end)
    )
    return float(total or 0.0)
