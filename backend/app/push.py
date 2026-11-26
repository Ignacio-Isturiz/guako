"""Recordatorio diario de racha por Web Push (la web instalada en el celular).

La app nativa programa notificaciones locales en el teléfono. La web instalada no puede programarlas, así
que el backend las envía: el navegador se suscribe (app/push_api.py) con su hora, zona horaria e idioma, y
cada pocos minutos `send_due` busca a quién le toca:

- ya es su hora en su zona (y no han pasado más de REMINDER_WINDOW_HOURS: si el servidor estuvo dormido,
  no se avisa de madrugada lo que tocaba en la tarde),
- hoy no se le ha enviado,
- hoy no ha practicado (la racha ya cuenta hoy → no se le molesta).

Si el servicio de push responde 404/410, el navegador ya no tiene la suscripción: se borra la fila.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, settings
from app.db import PushSubscription, Streak

logger = logging.getLogger("app.push")

REMINDER_WINDOW_HOURS = 3
TTL_SECONDS = 4 * 3600  # si el teléfono está apagado, el servicio guarda el aviso hasta 4 h
OPEN_URL = "/app/inicio"

# Los mismos textos que el recordatorio de la app nativa (frontend: app.reminder)
MESSAGES = {
    "es": ("¿Practicamos un poco?", "Cinco minutos con Guako y tu racha sigue viva."),
    "en": ("Shall we practice a little?", "Five minutes with Guako keeps your streak alive."),
}

# Solo se envía a servicios de push conocidos: el endpoint lo manda el navegador y el servidor le hace un
# POST, así que sin esta lista cualquiera podría hacer que el backend llame a una URL suya (SSRF).
PUSH_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge y Samsung en Android
    "push.apple.com",  # Safari (iPhone con la web en la pantalla de inicio)
    "push.services.mozilla.com",  # Firefox
    "notify.windows.com",  # Edge en Windows
)


def allowed_endpoint(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith(f".{h}") for h in PUSH_HOSTS)


def due_day(hour: int, tz: str, last_sent_day: date | None, practiced_day: date | None, now: datetime) -> date | None:
    """El día local en que toca avisar ahora, o None si no toca. `now` lleva zona horaria."""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    local = now.astimezone(zone)
    today = local.date()
    if not hour <= local.hour < hour + REMINDER_WINDOW_HOURS:
        return None
    if last_sent_day == today or practiced_day == today:
        return None
    return today


class PushGone(Exception):
    """El servicio de push dice que la suscripción ya no existe (404/410)."""


Sender = Callable[[PushSubscription, str, Settings], None]


def webpush_sender(sub: PushSubscription, payload: str, config: Settings) -> None:
    """Envía un aviso con pywebpush (bloqueante: se llama en un hilo)."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=payload,
            vapid_private_key=config.vapid_private_key.get_secret_value() if config.vapid_private_key else "",
            vapid_claims={"sub": config.vapid_subject},
            ttl=TTL_SECONDS,
            timeout=10,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            raise PushGone from exc
        raise


def payload_for(lang: str) -> str:
    title, body = MESSAGES.get(lang, MESSAGES["es"])
    return json.dumps({"title": title, "body": body, "url": OPEN_URL}, ensure_ascii=False)


async def send_due(
    maker: async_sessionmaker[AsyncSession],
    config: Settings = settings,
    sender: Sender = webpush_sender,
    now: datetime | None = None,
) -> int:
    """Envía los recordatorios que tocan ahora. Devuelve cuántos salieron."""
    if not config.push_enabled:
        return 0
    now = now or datetime.now(timezone.utc)
    sent = 0
    async with maker() as db:
        rows = await db.execute(
            select(PushSubscription, Streak.last_day).outerjoin(Streak, Streak.user_id == PushSubscription.user_id)
        )
        for sub, practiced_day in rows.all():
            day = due_day(sub.hour, sub.timezone, sub.last_sent_day, practiced_day, now)
            if day is None:
                continue
            try:
                await asyncio.to_thread(sender, sub, payload_for(sub.lang), config)
            except PushGone:
                await db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
                continue
            except Exception:
                logger.warning("push_send_failed subscription=%s", sub.id, exc_info=True)
                continue
            sub.last_sent_day = day
            sent += 1
        await db.commit()
    return sent


async def run_push_scheduler(maker: async_sessionmaker[AsyncSession], config: Settings = settings) -> None:
    """Bucle del servidor: busca recordatorios pendientes cada `push_check_seconds`."""
    while True:
        try:
            await send_due(maker, config)
        except Exception:
            logger.exception("push_scheduler_failed: retrying on the next round")
        await asyncio.sleep(config.push_check_seconds)
