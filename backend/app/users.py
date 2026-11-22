import re

from fastapi import Depends, HTTPException, Request
from fastapi_users import BaseUserManager, FastAPIUsers, IntegerIDMixin, InvalidPasswordException, schemas
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from pydantic import Field
from sqlalchemy import select

from app.config import settings
from app.db import User, get_user_db

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


# ---------- Esquemas (lo que entra y sale por la API) ----------
class UserRead(schemas.BaseUser[int]):
    username: str


class UserCreate(schemas.BaseUserCreate):
    username: str = Field(min_length=3, max_length=30)


class UserUpdate(schemas.BaseUserUpdate):
    pass


# ---------- Lógica de usuarios ----------
class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    reset_password_token_secret = settings.secret
    verification_token_secret = settings.secret

    async def validate_password(self, password: str, user) -> None:
        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            raise InvalidPasswordException(reason="weak")

    async def create(self, user_create, safe: bool = False, request: Request | None = None):
        username = user_create.username
        if not USERNAME_RE.match(username):
            raise HTTPException(status_code=400, detail={"code": "usernameInvalid"})
        # Sin distinguir mayúsculas: "Ana" y "ana" cuentan como el mismo usuario
        taken = await self.user_db.session.execute(select(User.id).where(User.username.ilike(username)))
        if taken.first():
            raise HTTPException(status_code=400, detail={"code": "usernameTaken"})
        return await super().create(user_create, safe, request)


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


# ---------- Autenticación: JWT guardado en una cookie httpOnly ----------
cookie_transport = CookieTransport(
    cookie_name="guako_session",
    cookie_max_age=settings.session_seconds,
    cookie_secure=settings.cookie_secure,
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.secret, lifetime_seconds=settings.session_seconds)


auth_backend = AuthenticationBackend(name="cookie", transport=cookie_transport, get_strategy=get_jwt_strategy)

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])
current_active_user = fastapi_users.current_user(active=True)
