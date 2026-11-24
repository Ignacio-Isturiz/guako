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
    # None when every voice provider was out: the browser reads the reply aloud (see providers/).
    reply_audio_path: Mapped[str | None] = mapped_column(String(500), default=None)
    # Audio length in seconds; learner + tutor seconds count toward the daily limit.
    user_audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    reply_audio_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # How much to trust the transcription (None for old turns or if the provider sent nothing): the judges use it.
    stt_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    stt_no_speech_prob: Mapped[float | None] = mapped_column(Float, default=None)
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
    # Enum values stored as plain strings; 32 leaves room for the longest ("skipped_no_audio" = 16).
    dimension: Mapped[str] = mapped_column(String(32))  # AnalysisDimension value
    status: Mapped[str] = mapped_column(String(32), default=AnalysisStatus.PENDING.value)  # AnalysisStatus value
    result: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=None)
    error: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WordPractice(Base):
    """"Now you say it" exercise on a hard word: one row per (session, word), enforced by the server.

    ``attempts`` = scored tries (limit in app/practice.py), ``calls`` = every Azure call (silence too),
    ``passed`` = reached the pass score, after which the word is locked.
    """

    __tablename__ = "word_practice"
    __table_args__ = (UniqueConstraint("session_id", "word"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    word: Mapped[str] = mapped_column(String(64))  # normalised (lowercase, no punctuation)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    calls: Mapped[int] = mapped_column(default=0, server_default="0")
    passed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    best_score: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AzureSpeechUsage(Base):
    """Seconds of audio sent to Azure Speech per calendar month (UTC), for the whole app.

    The free F0 plan gives a fixed number of audio seconds per month, shared by every user, so
    this is one counter per month (``month`` = "YYYY-MM"), not one per user.
    """

    __tablename__ = "azure_speech_usage"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProviderUsage(Base):
    """Calls to one provider for one capability and use on one UTC day, with what they consumed and cost.

    ``cost_usd`` is our estimate (see app/providers/pricing.py), not an invoice.
    """

    __tablename__ = "provider_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)  # groq, gemini, openai
    capability: Mapped[str] = mapped_column(String(8), primary_key=True)  # llm, stt, tts
    use: Mapped[str] = mapped_column(String(16), primary_key=True)  # conversation, analysis
    requests: Mapped[int] = mapped_column(default=0, server_default="0")
    successes: Mapped[int] = mapped_column(default=0, server_default="0")
    failures: Mapped[int] = mapped_column(default=0, server_default="0")
    rate_limited: Mapped[int] = mapped_column(default=0, server_default="0")
    as_fallback: Mapped[int] = mapped_column(default=0, server_default="0")  # answered after another one failed
    prompt_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    audio_seconds_in: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    audio_seconds_out: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    chars: Mapped[int] = mapped_column(default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProviderCall(Base):
    """One call that reached a provider (never its prompt, text or audio), kept 30 days to explain what served what."""

    __tablename__ = "provider_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    capability: Mapped[str] = mapped_column(String(8))
    use: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24))  # ok, rate_limited, unavailable, timeout, auth, bad_output
    latency_ms: Mapped[int]
    prompt_tokens: Mapped[int | None] = mapped_column(default=None)
    completion_tokens: Mapped[int | None] = mapped_column(default=None)
    audio_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    chars: Mapped[int | None] = mapped_column(default=None)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    fallback_from: Mapped[str | None] = mapped_column(String(16), default=None)  # the provider that failed first
    # Plain ids, not foreign keys: the log outlives a deleted session.
    session_id: Mapped[int | None] = mapped_column(default=None)
    turn_id: Mapped[int | None] = mapped_column(default=None, index=True)


engine = create_async_engine(settings.database_url)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, int], None]:
    yield SQLAlchemyUserDatabase(session, User)
