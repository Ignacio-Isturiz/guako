from collections.abc import AsyncGenerator
from datetime import date

from fastapi import Depends
from fastapi_users.db import SQLAlchemyBaseUserTable, SQLAlchemyUserDatabase
from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTable[int], Base):
    """Usuario: id, email, hashed_password, is_active, is_superuser, is_verified + username."""

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)


class Streak(Base):
    """Estado de la racha de cada usuario (ver app/streaks.py para las reglas)."""

    __tablename__ = "streaks"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    current: Mapped[int] = mapped_column(default=0)
    best: Mapped[int] = mapped_column(default=0)
    last_day: Mapped[date | None] = mapped_column(Date, default=None)
    recoveries_used: Mapped[int] = mapped_column(default=0)
    recoveries_month: Mapped[str] = mapped_column(String(7), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")  # última zona horaria conocida


class ActivityDay(Base):
    """Un día en el que el usuario completó una acción clave (para pintar la semana)."""

    __tablename__ = "activity_days"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    recovered: Mapped[bool] = mapped_column(default=False)  # ese día gastó una oportunidad


engine = create_async_engine(settings.database_url)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, int], None]:
    yield SQLAlchemyUserDatabase(session, User)
