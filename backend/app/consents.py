"""Consents (Law 1581: prior, express and informed, with proof kept) and the safety events log.

The ``consents`` table is append-only: every grant or withdrawal is a new row with the date, the version of the
legal texts, the IP and the browser, and the newest row of a (user, kind) is the current state.

- "terms": the Terms of Use and the Privacy Policy. Given at sign-up; a new ``legal_version`` asks for it again.
  Without it the AI features (conversations, practice) are refused with 403 ``terms_required``.
- "audio": keep the learner's recordings to assess pronunciation. OFF until the learner says yes (no row = not
  asked yet). It is copied into each new session, and withdrawing it also withdraws it from open sessions.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import Consent, SafetyEvent, User, get_async_session
from app.users import current_active_user

TERMS = "terms"
AUDIO = "audio"


async def latest(db: AsyncSession, user_id: int, kind: str) -> Consent | None:
    return await db.scalar(
        select(Consent).where(Consent.user_id == user_id, Consent.kind == kind).order_by(Consent.id.desc()).limit(1)
    )


def terms_up_to_date(row: Consent | None) -> bool:
    return row is not None and row.granted and row.version == settings.legal_version


async def require_terms(db: AsyncSession, user_id: int) -> None:
    """403 unless the user accepted the CURRENT Terms and Privacy Policy."""
    if not terms_up_to_date(await latest(db, user_id, TERMS)):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "terms_required",
                "message": "Acepta los Términos y la Política de privacidad vigentes para continuar.",
            },
        )


async def user_with_terms(
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> User:
    """Dependency for the endpoints that send the learner's data to the AI providers."""
    await require_terms(db, user.id)
    return user


async def audio_granted(db: AsyncSession, user_id: int) -> bool | None:
    """True / False as the learner answered; None when they were never asked."""
    row = await latest(db, user_id, AUDIO)
    return None if row is None else row.granted


def record(
    db: AsyncSession, user_id: int, kind: str, granted: bool, *, version: str | None = None, request: Request | None = None
) -> Consent:
    """Adds the row (the caller commits)."""
    ip = request.client.host if request is not None and request.client else None
    agent = request.headers.get("user-agent", "")[:200] if request is not None else None
    row = Consent(user_id=user_id, kind=kind, granted=granted, version=version, ip=ip, user_agent=agent or None)
    db.add(row)
    return row


def add_safety_events(
    db: AsyncSession,
    events: list[dict],
    *,
    user_id: int | None,
    session_id: int | None = None,
    turn_number: int | None = None,
) -> None:
    """Adds what the safety guard found (the caller commits)."""
    for event in events:
        db.add(
            SafetyEvent(
                user_id=user_id,
                session_id=session_id,
                turn_number=turn_number,
                kind=event["kind"],
                source=event["source"],
                categories=list(event.get("categories") or []),
                replaced=bool(event.get("replaced")),
            )
        )
