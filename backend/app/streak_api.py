"""Endpoints de la racha.

GET  /api/streak            → estado de hoy (racha, oportunidades, semana)
POST /api/streak/activity   → registra una acción clave (terminar una conversación)

Ambos aceptan ?tz=America/Bogota (zona IANA del navegador). El día cambia a medianoche
en la zona del usuario, así que alguien en España y otro en Colombia no comparten "hoy".
"""

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ActivityDay, Streak, User, get_async_session
from app.streaks import MAX_RECOVERIES, StreakData, current_count, recoveries_left, register_activity, status
from app.users import current_active_user

router = APIRouter(prefix="/api/streak", tags=["streak"])

DEFAULT_TZ = "UTC"


class WeekDay(BaseModel):
    date: date
    done: bool
    recovered: bool
    is_today: bool


class StreakRead(BaseModel):
    count: int  # racha que se muestra hoy
    best: int
    status: Literal["none", "done", "pending", "recoverable"]
    recoveries_left: int  # oportunidades que quedan este mes
    recoveries_max: int
    recovered_today: bool  # esta petición gastó una oportunidad
    today: date
    week: list[WeekDay]  # los últimos 7 días, el último es hoy


def resolve_tz(tz: str | None, fallback: str = DEFAULT_TZ) -> str:
    """Nombre de zona válido: el pedido, si no la guardada, si no UTC."""
    for name in (tz, fallback, DEFAULT_TZ):
        if not name:
            continue
        try:
            ZoneInfo(name)
            return name
        except (ZoneInfoNotFoundError, ValueError, OSError):
            continue
    return DEFAULT_TZ


def today_in(tz: str, now: datetime | None = None) -> date:
    """Fecha de hoy en esa zona. `now` (con zona) solo se pasa en las pruebas."""
    zone = ZoneInfo(tz)
    return (now.astimezone(zone) if now else datetime.now(zone)).date()


async def _get_streak(session: AsyncSession, user: User) -> Streak:
    row = await session.get(Streak, user.id)
    if row is None:
        row = Streak(user_id=user.id, current=0, best=0, recoveries_used=0, recoveries_month="", timezone=DEFAULT_TZ)
        session.add(row)
    return row


def _data(row: Streak) -> StreakData:
    return StreakData(row.current, row.best, row.last_day, row.recoveries_used, row.recoveries_month)


async def _build(session: AsyncSession, user: User, row: Streak, today: date, recovered_today: bool) -> StreakRead:
    data = _data(row)
    start = today - timedelta(days=6)
    rows = await session.execute(
        select(ActivityDay).where(ActivityDay.user_id == user.id, ActivityDay.day >= start, ActivityDay.day <= today)
    )
    days = {r.day: r for r in rows.scalars()}
    week = [
        WeekDay(
            date=d,
            done=d in days,
            recovered=bool(days[d].recovered) if d in days else False,
            is_today=d == today,
        )
        for d in (start + timedelta(days=i) for i in range(7))
    ]
    return StreakRead(
        count=current_count(data, today),
        best=data.best,
        status=status(data, today),
        recoveries_left=recoveries_left(data, today),
        recoveries_max=MAX_RECOVERIES,
        recovered_today=recovered_today,
        today=today,
        week=week,
    )


@router.get("", response_model=StreakRead)
async def get_streak(
    tz: str | None = Query(default=None, max_length=64),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> StreakRead:
    row = await _get_streak(session, user)
    zone = resolve_tz(tz, row.timezone or DEFAULT_TZ)
    return await _build(session, user, row, today_in(zone), recovered_today=False)


@router.post("/activity", response_model=StreakRead)
async def post_activity(
    tz: str | None = Query(default=None, max_length=64),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> StreakRead:
    row = await _get_streak(session, user)
    zone = resolve_tz(tz, row.timezone or DEFAULT_TZ)
    today = today_in(zone)

    data = _data(row)
    already = data.last_day == today
    recovered = register_activity(data, today)

    row.current, row.best, row.last_day = data.current, data.best, data.last_day
    row.recoveries_used, row.recoveries_month, row.timezone = data.recoveries_used, data.recoveries_month, zone
    if not already and await session.get(ActivityDay, (user.id, today)) is None:
        session.add(ActivityDay(user_id=user.id, day=today, recovered=recovered))
    await session.commit()
    return await _build(session, user, row, today, recovered_today=recovered)
