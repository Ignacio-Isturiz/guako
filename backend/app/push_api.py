"""Endpoints del recordatorio por Web Push (web instalada en el celular). Ver app/push.py.

GET    /api/push/key           → {"public_key": "..."} (null si el push no está configurado)
PUT    /api/push/subscription  → guarda o actualiza la suscripción de este navegador (hora, zona, idioma)
DELETE /api/push/subscription  → la quita (p. ej. al cerrar sesión)
POST   /api/push/run           → envía los pendientes ya (para un cron externo; header X-Cron-Token)
"""

import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import PushSubscription, User, async_session_maker, get_async_session
from app.push import allowed_endpoint, send_due
from app.streak_api import resolve_tz
from app.users import current_active_user

router = APIRouter(prefix="/api/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: PushKeys
    hour: int = Field(default=19, ge=0, le=23)
    tz: str = Field(default="UTC", max_length=64)
    lang: Literal["es", "en"] = "es"


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.get("/key")
def public_key() -> dict[str, str | None]:
    return {"public_key": settings.vapid_public_key.strip() if settings.push_enabled else None}


@router.put("/subscription", status_code=204)
async def save_subscription(
    body: SubscriptionIn,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> Response:
    if not allowed_endpoint(body.endpoint):
        raise HTTPException(422, "unknown_push_service")
    row = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if row is None:
        row = PushSubscription(endpoint=body.endpoint)
        db.add(row)
    elif row.user_id != user.id:
        row.last_sent_day = None  # otra cuenta en el mismo navegador: empieza de cero
    row.user_id = user.id
    row.p256dh, row.auth = body.keys.p256dh, body.keys.auth
    row.hour, row.timezone, row.lang = body.hour, resolve_tz(body.tz), body.lang
    await db.commit()
    return Response(status_code=204)


@router.delete("/subscription", status_code=204)
async def remove_subscription(
    body: EndpointIn,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> Response:
    await db.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id)
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/run")
async def run_now(x_cron_token: Annotated[str, Header()] = "") -> dict[str, int]:
    token = settings.push_cron_token.get_secret_value() if settings.push_cron_token else ""
    if not token or not secrets.compare_digest(x_cron_token.encode(), token.encode()):
        raise HTTPException(404)
    return {"sent": await send_due(async_session_maker)}
