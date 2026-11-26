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
from pgvector.sqlalchemy import Vector
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


class PushSubscription(Base):
    """A browser where the learner gets the daily streak reminder by Web Push (the installed web app).

    The native app schedules local notifications instead and never lands here. One row per browser
    (`endpoint` is unique: the same browser signing in with another account moves to that account).
    `hour`, `timezone` and `lang` are what the reminder needs; `last_sent_day` (in that zone) keeps it to
    one a day. A push service answering 404/410 means the browser dropped it: the row is deleted.
    Goes away with the account.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    hour: Mapped[int] = mapped_column(default=19)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    lang: Mapped[str] = mapped_column(String(2), default="es")
    last_sent_day: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


engine = create_async_engine(settings.database_url)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, int], None]:
    yield SQLAlchemyUserDatabase(session, User)


class GrammarRuleEmbedding(Base):
    """Embedding of one rule of the grammar corpus (the text itself lives in app/rag/rules, not here).

    ``content_hash`` is the hash of the embedded text: when a rule changes, its hash changes and the indexer
    re-embeds only that rule. The vector column only exists in PostgreSQL (pgvector); in SQLite it is JSON so the
    tables can still be created, but nothing searches there: the RAG is switched off outside PostgreSQL.
    """

    __tablename__ = "grammar_rules"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    error_type: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(2))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dimensions).with_variant(JSON(), "sqlite")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ErrorEvent(Base):
    """One grammar mistake a learner made in one turn: the memory of the RAG (app/rag/memory.py).

    It is what lets the report say "this already happened to you in 2 earlier sessions". ``rule_id`` is the rule of
    the corpus that explains it (NULL when none was close enough): counting by rule is plain SQL; the vector is
    for the mistakes that have no rule and for finding similar ones later (the practice built from what was hard).
    It belongs to the learner: it goes away with the account, the session or the turn.
    """

    __tablename__ = "error_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"), index=True)
    error_type: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[str | None] = mapped_column(String(80), default=None)
    original: Mapped[str] = mapped_column(Text)
    correction: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dimensions).with_variant(JSON(), "sqlite")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExerciseSeen(Base):
    """An exercise a learner already answered, so the next rounds give ones they have not seen (app/exercises).

    Only the exercise id and when: never the answer. It goes away with the account.
    """

    __tablename__ = "exercise_seen"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    exercise_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    times: Mapped[int] = mapped_column(default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedExercise(Base):
    """An exercise written by the LLM and accepted by the grammar analyser (app/exercises/generated.py).

    ``kind`` is choice, fill or fix; a fix also gives a speaking exercise when it is served. Rejected exercises are
    never stored: this table only holds ones that passed the checks.
    """

    __tablename__ = "generated_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text)  # choice: the question · fill: the sentence with ___ · fix: the wrong one
    options: Mapped[list] = mapped_column(JSON, default=list)  # choice only, the right one FIRST
    answers: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class SafetyEvent(Base):
    """Something the safety guard found (app.safety.guard): a moderation flag, an injection attempt, a leak.

    Keeps WHAT was found (kind, who, categories), never the text itself: the turn already has the transcript and
    the reply, and an attempt does not need to be stored twice. Used to review abuse and tune the guard.
    """

    __tablename__ = "safety_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True, default=None)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), default=None)
    turn_number: Mapped[int | None] = mapped_column(default=None)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # moderation, injection_attempt, instruction_leak...
    source: Mapped[str] = mapped_column(String(16))  # learner, tutor, scene, service
    categories: Mapped[list] = mapped_column(JSON, default=list)
    replaced: Mapped[bool] = mapped_column(Boolean, default=False)  # the reply was swapped for a safe line
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Consent(Base):
    """Each time a user grants or withdraws an authorisation: the proof Law 1581 asks to keep.

    Append-only: the newest row of a (user, kind) is the current state. ``kind`` is "terms" (Terms of Use and
    Privacy Policy, with the ``version`` accepted) or "audio" (keep recordings to assess pronunciation).
    """

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    granted: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[str | None] = mapped_column(String(32), default=None)
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReplyReport(Base):
    """A learner reported one of Guako's replies (offensive, harmful, wrong...).

    Google Play asks apps with generative AI to let people report offensive output from inside the app, and the
    App Store reviews it too. One report per reply and learner (reporting again updates it). The reply text is
    read from the turn when reviewing, not copied here. Goes away with the account.
    """

    __tablename__ = "reply_reports"
    __table_args__ = (UniqueConstraint("session_id", "turn_number", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    turn_number: Mapped[int]
    reason: Mapped[str] = mapped_column(String(16))  # offensive, harmful, wrong, other
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

