from collections.abc import AsyncGenerator
from datetime import date, datetime

from fastapi import Depends
from fastapi_users.db import SQLAlchemyBaseUserTable, SQLAlchemyUserDatabase
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings
from app.enums import AnalysisStatus, FeedbackLanguage


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTable[int], Base):
    """Usuario: id, email, hashed_password, is_active, is_superuser, is_verified + username."""

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    feedback_language: Mapped[FeedbackLanguage] = mapped_column(
        Enum(
            FeedbackLanguage,
            name="feedback_language",
            native_enum=False,  # VARCHAR instead of a Postgres ENUM type: easier to evolve
            length=2,
            values_callable=lambda enum: [member.value for member in enum],  # store "es"/"en", not "ES"/"EN"
        ),
        default=FeedbackLanguage.ES,
        server_default=FeedbackLanguage.ES.value,
    )


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


class ConversationSession(Base):
    """One tutoring conversation. ``audio_consent`` must be true before user audio is kept."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(2))
    topic: Mapped[str] = mapped_column(String(200))
    # The part Guako plays (e.g. "my mom, I ask her for money"); None = plain friendly tutor.
    role: Mapped[str | None] = mapped_column(String(200), default=None)
    audio_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The finished report (SessionReport as JSON), saved the first time it is complete so it is
    # never rebuilt (each build costs one LLM call per turn) and scores can be tracked over time.
    report: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Turn(Base):
    """One learner message and the tutor's reply."""

    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("session_id", "turn_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    turn_number: Mapped[int]
    user_transcript: Mapped[str] = mapped_column(Text)
    reply_text: Mapped[str] = mapped_column(Text)
    # None when the session has no audio consent (the upload is deleted after transcribing).
    user_audio_path: Mapped[str | None] = mapped_column(String(500), default=None)
    reply_audio_path: Mapped[str] = mapped_column(String(500))
    # Audio length in seconds; learner + tutor seconds count toward the daily limit.
    user_audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    reply_audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # JSONB on Postgres, plain JSON on SQLite (development and tests).
    word_timestamps: Mapped[list[dict] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TurnAnalysis(Base):
    """Background analysis of one turn: one row per (turn, dimension), written after the turn is saved.

    ``result`` holds the finished analysis (``status == "done"``); ``error`` is a short code when the
    analysis was given up (``status == "failed"``). A turn is never analysed twice: only ``pending``
    rows are picked up.
    """

    __tablename__ = "turn_analyses"
    __table_args__ = (UniqueConstraint("turn_id", "dimension"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"), index=True)
    dimension: Mapped[str] = mapped_column(String(10))  # AnalysisDimension value
    status: Mapped[str] = mapped_column(String(10), default=AnalysisStatus.PENDING.value)  # AnalysisStatus value
    result: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=None)
    error: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


engine = create_async_engine(settings.database_url)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, int], None]:
    yield SQLAlchemyUserDatabase(session, User)
