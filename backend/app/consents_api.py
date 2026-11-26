"""The learner's authorisations.

GET  /api/consents/me                                   → state of "terms" and "audio"
POST /api/consents  {kind: "terms"|"audio", granted, version?}  → records a grant or a withdrawal
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import consents
from app.config import settings
from app.db import ConversationSession, User, get_async_session
from app.sessions_api import _discard_stored_audio
from app.users import current_active_user

router = APIRouter(prefix="/api/consents", tags=["consents"])


class TermsState(BaseModel):
    accepted_version: str | None
    current_version: str
    up_to_date: bool
    at: datetime | None


class AudioState(BaseModel):
    granted: bool | None  # None: never asked
    at: datetime | None


class ConsentsRead(BaseModel):
    terms: TermsState
    audio: AudioState


class ConsentChange(BaseModel):
    kind: Literal["terms", "audio"]
    granted: bool
    # Terms only: the version the learner read (the date shown by the frontend).
    version: str | None = None


async def _state(db: AsyncSession, user_id: int) -> ConsentsRead:
    terms = await consents.latest(db, user_id, consents.TERMS)
    audio = await consents.latest(db, user_id, consents.AUDIO)
    return ConsentsRead(
        terms=TermsState(
            accepted_version=terms.version if terms and terms.granted else None,
            current_version=settings.legal_version,
            up_to_date=consents.terms_up_to_date(terms),
            at=terms.created_at if terms else None,
        ),
        audio=AudioState(granted=audio.granted if audio else None, at=audio.created_at if audio else None),
    )


@router.get("/me", response_model=ConsentsRead)
async def my_consents(
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> ConsentsRead:
    return await _state(db, user.id)


@router.post("", response_model=ConsentsRead)
async def change_consent(
    body: ConsentChange,
    request: Request,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> ConsentsRead:
    if body.kind == consents.TERMS and body.granted and body.version != settings.legal_version:
        # The learner read another version (an old tab): they must read the current one.
        raise HTTPException(
            status_code=409,
            detail={"code": "terms_outdated", "message": "Los documentos cambiaron. Vuelve a leerlos para aceptarlos."},
        )
    version = settings.legal_version if body.kind == consents.TERMS else None
    consents.record(db, user.id, body.kind, body.granted, version=version, request=request)

    if body.kind == consents.AUDIO and not body.granted:
        # Withdrawn: the sessions still open stop keeping audio, and what they kept is deleted now.
        open_sessions = (
            await db.scalars(
                select(ConversationSession).where(
                    ConversationSession.user_id == user.id,
                    ConversationSession.ended_at.is_(None),
                    ConversationSession.audio_consent.is_(True),
                )
            )
        ).all()
        for session in open_sessions:
            session.audio_consent = False
            await _discard_stored_audio(db, session.id)

    await db.commit()
    return await _state(db, user.id)
