"""PATCH /api/users/me/settings  { feedback_language } → updated user (requires login)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from pydantic import BaseModel

from app.db import User, get_user_db
from app.enums import FeedbackLanguage
from app.users import UserRead, current_active_user

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
