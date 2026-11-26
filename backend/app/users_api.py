"""The learner's own account.

PATCH  /api/users/me/settings  { feedback_language } → updated user (requires login)
DELETE /api/users/me                                 → 204, the account and everything of it is gone (requires login)
"""

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from fastapi.concurrency import run_in_threadpool
from fastapi_users.db import SQLAlchemyUserDatabase
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import observability
from app.config import settings
from app.db import (
    ActivityDay,
    Consent,
    ConversationSession,
    ErrorEvent,
    ExerciseSeen,
    PushSubscription,
    ReplyReport,
    SafetyEvent,
    Streak,
    Turn,
    TurnAnalysis,
    User,
    WordPractice,
    get_async_session,
    get_user_db,
)
from app.enums import FeedbackLanguage
from app.users import UserRead, cookie_transport, current_active_user

router = APIRouter(prefix="/api/users", tags=["users"])


class SettingsUpdate(BaseModel):
    feedback_language: FeedbackLanguage


@router.patch("/me/settings", response_model=UserRead)
async def update_my_settings(
    body: SettingsUpdate,
    user: Annotated[User, Depends(current_active_user)],
    user_db: Annotated[SQLAlchemyUserDatabase[User, int], Depends(get_user_db)],
) -> User:
    # The user comes from the session cookie, so only one's own settings can change.
    return await user_db.update(user, {"feedback_language": body.feedback_language})


@router.delete("/me", status_code=204)
async def delete_my_account(
    background: BackgroundTasks,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    user_db: Annotated[SQLAlchemyUserDatabase[User, int], Depends(get_user_db)],
) -> Response:
    """Delete the account and all its data (Law 1581 "supresión"; required by Google Play and the App Store).

    Rows are deleted explicitly, children first, instead of trusting ON DELETE CASCADE: SQLite only enforces
    foreign keys when asked to, and this must work on every database. Kept on purpose: provider_calls and
    provider_usage (costs and latency, plain ids, no text or audio of the learner). The learner's Langfuse traces
    are deleted after the response, in the background (network calls, and they must not block the deletion).
    """
    session_ids = select(ConversationSession.id).where(ConversationSession.user_id == user.id)
    turn_ids = select(Turn.id).where(Turn.session_id.in_(session_ids))
    sessions = (await db.scalars(session_ids)).all()

    await db.execute(delete(TurnAnalysis).where(TurnAnalysis.turn_id.in_(turn_ids)))
    await db.execute(delete(ErrorEvent).where(ErrorEvent.user_id == user.id))
    await db.execute(
        delete(SafetyEvent).where(or_(SafetyEvent.user_id == user.id, SafetyEvent.session_id.in_(session_ids)))
    )
    await db.execute(delete(WordPractice).where(WordPractice.session_id.in_(session_ids)))
    await db.execute(delete(Turn).where(Turn.session_id.in_(session_ids)))
    await db.execute(delete(ConversationSession).where(ConversationSession.user_id == user.id))
    for table in (Streak, ActivityDay, ExerciseSeen, Consent, ReplyReport, PushSubscription):
        await db.execute(delete(table).where(table.user_id == user.id))
    await db.commit()
    user_id = user.id
    await user_db.delete(user)
    background.add_task(observability.forget_user, user_id)

    # Recordings and Guako's replies live in <sessions_audio_dir>/<session id>/
    for session_id in sessions:
        folder = Path(settings.sessions_audio_dir) / str(session_id)
        await run_in_threadpool(shutil.rmtree, folder, ignore_errors=True)

    # The session cookie is useless now; tell the browser to drop it.
    response = Response(status_code=204)
    response.delete_cookie(
        cookie_transport.cookie_name,
        path=cookie_transport.cookie_path,
        domain=cookie_transport.cookie_domain,
        secure=cookie_transport.cookie_secure,
        httponly=cookie_transport.cookie_httponly,
        samesite=cookie_transport.cookie_samesite,
    )
    return response
