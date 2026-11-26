"""Conversation endpoints.

POST /api/sessions                                    → create a session (level, topic)
GET  /api/sessions                                    → my conversations (sessions with at least one turn), newest first
POST /api/sessions/{id}/opening                      → Guako's first line, in the learner's chosen part (turn 0)
PATCH /api/sessions/{id}  {"ended"?: true, "audio_consent"?: bool} → end the session (idempotent) / change consent
POST /api/sessions/{id}/turns                         → one audio turn: audio in, tutor reply out
GET  /api/sessions/{id}/turns                         → the saved turns (transcripts) of the session
GET  /api/sessions/{id}/turns/{n}/reply-audio         → the tutor's audio for turn n
GET  /api/sessions/{id}/report                  → end-of-session report from the background analyses (409 until the session ends)
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import consents, observability
from app.analysis.runner import ensure_pending_rows, run_turn_analysis
from app.rag.memory import seen_before
from app.config import settings
from app.conversation.deps import get_pronunciation_provider, get_stt_provider, get_tts_provider
from app.conversation.graph import build_graph
from app.conversation.opening import OPENING_TURN, generate_opening
from app.conversation.state import ConversationState, Message
from app.db import ConversationSession, ReplyReport, Turn, TurnAnalysis, User, get_async_session
from app.enums import AnalysisDimension, AnalysisStatus
from app.llm.base import LLMProvider
from app.llm.factory import get_analysis_llm_provider, get_llm_provider
from app.practice import attach_practice
from app.providers.context import set_call_context
from app.pronunciation import PronunciationProvider
from app.reports import (
    FluencyReport,
    GrammarReport,
    JudgeReport,
    PronunciationReport,
    SessionReport,
    build_fluency_report,
    build_grammar_report,
    build_judge_report,
    build_pronunciation_report,
)
from app.stt import STTProvider
from app.stt.groq import SUPPORTED_EXTENSIONS
from app.tts import TTSProvider
from app.usage import seconds_used_today
from app.consents import user_with_terms
from app.safety.guard import check_scene
from app.users import current_active_user

logger = logging.getLogger("app.conversation")

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

Level = Literal["A1", "A2", "B1", "B2", "C1"]
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


Role = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class SessionCreate(BaseModel):
    level: Level
    topic: Topic
    # The part Guako plays, in the learner's own words. Optional; blank counts as none.
    role: Role | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    topic: str
    role: str | None
    audio_consent: bool
    created_at: datetime
    ended_at: datetime | None


class SessionUpdate(BaseModel):
    """Partial update; at least one field is required.

    ``ended`` only accepts ``true``: sessions are never reopened (``false`` is a 422).
    ``audio_consent`` can go both ways.
    """

    ended: Literal[True] | None = None
    audio_consent: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "SessionUpdate":
        if self.ended is None and self.audio_consent is None:
            raise ValueError("Provide 'ended' or 'audio_consent'.")
        return self


class SessionSummary(SessionRead):
    """A conversation as listed in the history: the session plus how much was said."""

    turns: int
    # Scores from the saved report; None until the report has been built (opening it builds it).
    grammar_score: int | None = None
    fluency_score: int | None = None
    # Learner + tutor audio, the same measure the daily limit uses.
    duration_seconds: float


class TurnRead(BaseModel):
    turn_number: int
    user_transcript: str
    reply_text: str
    reply_audio_url: str | None  # None: no audio (every voice provider was out): read reply_text aloud


class TurnSummary(TurnRead):
    """A saved turn, as listed for the review screen."""


def _reply_url(turn: Turn) -> str | None:
    if not turn.reply_audio_path:
        return None
    return f"/api/sessions/{turn.session_id}/turns/{turn.turn_number}/reply-audio"


async def _own_session(db: AsyncSession, session_id: int, user: User) -> ConversationSession:
    """The session if it belongs to ``user``; 404 otherwise (never reveals other users' sessions)."""
    session = await db.get(ConversationSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Sesión no encontrada."})
    return session


@router.post("", status_code=201, response_model=SessionRead)
async def create_session(
    body: SessionCreate,
    user: Annotated[User, Depends(user_with_terms)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> ConversationSession:
    # The scene and the part go into the tutor's instructions: no orders to the model, no harmful content.
    found = await run_in_threadpool(check_scene, body.topic, body.role)
    if found:
        consents.add_safety_events(db, found, user_id=user.id)
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsafe_scene",
                "message": "Describe solo la situación y el papel de Guako, sin instrucciones ni contenido ofensivo.",
            },
        )
    # The learner's answer to "keep my audio" (off until they say yes) applies to the new session.
    keep_audio = await consents.audio_granted(db, user.id) is True
    session = ConversationSession(
        user_id=user.id, level=body.level, topic=body.topic, role=body.role or None, audio_consent=keep_audio
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.patch("/{session_id}", response_model=SessionRead)
async def end_session(
    session_id: int,
    body: SessionUpdate,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> ConversationSession:
    session = await _own_session(db, session_id, user)

    if body.audio_consent is not None and body.audio_consent != session.audio_consent:
        # Granting consent after the end would retroactively legitimise nothing (no more
        # turns can be recorded), so it is refused. Withdrawing is always allowed.
        if body.audio_consent and session.ended_at is not None:
            raise HTTPException(status_code=409, detail={"code": "session_ended", "message": "Esta sesión ya terminó."})
        if body.audio_consent and await consents.audio_granted(db, user.id) is not True:
            # The proof of the authorisation lives in the consent log: grant it there first (POST /api/consents).
            raise HTTPException(
                status_code=409,
                detail={"code": "audio_consent_required", "message": "Activa \"Guardar mi audio\" en Ajustes primero."},
            )
        session.audio_consent = body.audio_consent
        if not body.audio_consent:
            await _discard_stored_audio(db, session_id)

    # Idempotent on purpose: the client may call this twice (the "finish" button and the
    # unmount/unload cleanup). A repeat call returns the session as is and keeps the
    # original ``ended_at``, so the end time is never overwritten.
    if body.ended and session.ended_at is None:
        session.ended_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(session)
    return session


async def _discard_stored_audio(db: AsyncSession, session_id: int) -> None:
    """Withdrawn consent: delete the learner's stored audio files and forget their paths."""
    turns = (await db.scalars(select(Turn).where(Turn.session_id == session_id, Turn.user_audio_path.is_not(None)))).all()
    for turn in turns:
        await run_in_threadpool(_remove, turn.user_audio_path)
        turn.user_audio_path = None


def _saved_score(session: ConversationSession, dimension: str) -> int | None:
    return ((session.report or {}).get(dimension) or {}).get("score")


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> list[SessionSummary]:
    # Sessions without turns (opened and abandoned, or whose first turn failed) are not conversations.
    rows = await db.execute(
        select(
            ConversationSession,
            func.count(Turn.id),
            func.coalesce(func.sum(Turn.user_audio_seconds + Turn.reply_audio_seconds), 0.0),
        )
        .join(Turn, (Turn.session_id == ConversationSession.id) & (Turn.turn_number != OPENING_TURN))
        .where(ConversationSession.user_id == user.id)
        .group_by(ConversationSession.id)
        .order_by(ConversationSession.created_at.desc(), ConversationSession.id.desc())
    )
    return [
        SessionSummary(
            **SessionRead.model_validate(s).model_dump(),
            turns=turns,
            duration_seconds=float(seconds),
            grammar_score=_saved_score(s, "grammar"),
            fluency_score=_saved_score(s, "fluency"),
        )
        for s, turns, seconds in rows.all()
    ]


async def _read_audio(upload: UploadFile) -> tuple[bytes, str]:
    """Validate the upload and return (bytes, extension). The client's file name is never used as a path."""
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail={"code": "audio_format", "message": "Formato de audio no soportado."},
        )
    data = await upload.read(settings.max_turn_audio_bytes + 1)
    if len(data) > settings.max_turn_audio_bytes:
        raise HTTPException(status_code=413, detail={"code": "audio_too_large", "message": "El audio es demasiado largo."})
    if not data:
        raise HTTPException(status_code=400, detail={"code": "audio_empty", "message": "El audio está vacío."})
    return data, extension


def _remove(path: Path | str | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


def _turn_read(turn: Turn) -> TurnRead:
    return TurnRead(
        turn_number=turn.turn_number,
        user_transcript=turn.user_transcript,
        reply_text=turn.reply_text,
        reply_audio_url=_reply_url(turn),
    )


@router.post("/{session_id}/opening", status_code=201, response_model=TurnRead)
async def create_opening(
    session_id: int,
    response: Response,
    user: Annotated[User, Depends(user_with_terms)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
    tts: Annotated[TTSProvider, Depends(get_tts_provider)],
) -> TurnRead:
    """Guako speaks first. Safe to call twice: the saved opening is returned (200) instead of a new one."""
    session = await _own_session(db, session_id, user)
    if session.ended_at is not None:
        raise HTTPException(status_code=409, detail={"code": "session_ended", "message": "Esta sesión ya terminó."})

    set_call_context(session_id=session_id)
    existing = await db.scalar(select(Turn).where(Turn.session_id == session_id, Turn.turn_number == OPENING_TURN))
    if existing is not None:
        response.status_code = 200
        return _turn_read(existing)
    if await db.scalar(select(func.count(Turn.id)).where(Turn.session_id == session_id)):
        # The learner already spoke first: an opening now would come out of order.
        raise HTTPException(status_code=409, detail={"code": "session_started", "message": "La conversación ya empezó."})

    if await seconds_used_today(db, user.id) >= settings.daily_limit_minutes * 60:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "daily_limit_reached",
                "message": f"Alcanzaste tu límite de {settings.daily_limit_minutes} minutos de hoy. Vuelve mañana.",
            },
        )

    with observability.trace(
        "apertura", session_id=session_id, user_id=user.id, tags=["conversacion"], metadata={"level": session.level}
    ):
        opening = await run_in_threadpool(
            lambda: generate_opening(
                llm,
                tts,
                session_id=session_id,
                level=session.level,
                topic=session.topic,
                role=session.role,
                audio_dir=settings.sessions_audio_dir,
            )
        )
    turn = Turn(
        session_id=session_id,
        turn_number=OPENING_TURN,
        user_transcript="",
        reply_text=opening.reply_text,
        reply_audio_path=opening.reply_audio_path or None,
        reply_audio_seconds=opening.reply_audio_seconds,
    )
    db.add(turn)
    consents.add_safety_events(db, opening.safety_events, user_id=user.id, session_id=session_id, turn_number=OPENING_TURN)
    try:
        await db.commit()
    except IntegrityError:
        # Two requests opened the same session at once: keep the one that got saved first.
        await db.rollback()
        saved = await db.scalar(select(Turn).where(Turn.session_id == session_id, Turn.turn_number == OPENING_TURN))
        if saved is None:
            raise
        response.status_code = 200
        return _turn_read(saved)
    return _turn_read(turn)


@router.post("/{session_id}/turns", status_code=201, response_model=TurnRead)
async def create_turn(
    session_id: int,
    audio: UploadFile,
    background: BackgroundTasks,
    user: Annotated[User, Depends(user_with_terms)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    stt: Annotated[STTProvider, Depends(get_stt_provider)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
    tts: Annotated[TTSProvider, Depends(get_tts_provider)],
    analysis_llm: Annotated[LLMProvider, Depends(get_analysis_llm_provider)],
    pronunciation: Annotated[PronunciationProvider | None, Depends(get_pronunciation_provider)],
) -> TurnRead:
    session = await _own_session(db, session_id, user)
    if session.ended_at is not None:
        raise HTTPException(status_code=409, detail={"code": "session_ended", "message": "Esta sesión ya terminó."})

    set_call_context(session_id=session_id)

    # Soft limit: checked before spending any STT/LLM/TTS call. The turn that crosses
    # the limit is still allowed to finish; the next one is refused.
    limit_seconds = settings.daily_limit_minutes * 60
    if await seconds_used_today(db, user.id) >= limit_seconds:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "daily_limit_reached",
                "message": f"Alcanzaste tu límite de {settings.daily_limit_minutes} minutos de hoy. Vuelve mañana.",
            },
        )

    data, extension = await _read_audio(audio)

    # The turns table is the source of truth for the history; the graph checkpointer is
    # only a cache, so a restart (or a failed turn) never loses or corrupts the context.
    previous = (await db.scalars(select(Turn).where(Turn.session_id == session_id).order_by(Turn.turn_number))).all()
    messages: list[Message] = []
    for turn in previous:
        if turn.turn_number != OPENING_TURN:  # Guako's opening has no learner message
            messages.append({"role": "user", "content": turn.user_transcript})
        messages.append({"role": "assistant", "content": turn.reply_text})
    completed = previous[-1].turn_number if previous else 0

    user_audio = (
        Path(settings.sessions_audio_dir)
        / str(session_id)
        / f"turn_{completed + 1:03d}_user_{uuid.uuid4().hex[:8]}{extension}"
    )
    user_audio.parent.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(user_audio.write_bytes, data)

    initial: ConversationState = {
        "session_id": session_id,
        "level": session.level,
        "topic": session.topic,
        "role": session.role or "",
        "turn_number": completed,
        "messages": messages,
        "user_audio_path": str(user_audio),
    }
    graph = build_graph(stt, llm, tts)
    try:
        # The trace covers what the learner waits for (STT -> LLM -> TTS): its time is the turn's latency.
        with observability.trace(
            "turno",
            session_id=session_id,
            user_id=user.id,
            tags=["conversacion"],
            metadata={"turn_number": completed + 1, "level": session.level},
        ):
            result = await graph.ainvoke(initial, {"configurable": {"thread_id": str(session_id)}})
    except BaseException:
        _remove(user_audio)  # nothing is stored for a failed turn
        raise

    # Without consent the learner's audio is used for transcription and then discarded.
    kept_audio: str | None = str(user_audio) if session.audio_consent else None
    if kept_audio is None:
        _remove(user_audio)

    turn = Turn(
        session_id=session_id,
        turn_number=result["turn_number"],
        user_transcript=result["user_transcript"],
        reply_text=result["reply_text"],
        user_audio_path=kept_audio,
        reply_audio_path=result["reply_audio_path"] or None,
        user_audio_seconds=result["user_audio_seconds"],
        reply_audio_seconds=result["reply_audio_seconds"],
        word_timestamps=result.get("user_words"),
        stt_confidence=result.get("user_stt_confidence"),
        stt_no_speech_prob=result.get("user_no_speech_prob"),
    )
    db.add(turn)
    consents.add_safety_events(
        db, result.get("safety_events") or [], user_id=user.id, session_id=session_id, turn_number=result["turn_number"]
    )
    try:
        # The analysis rows are saved with the turn, so a saved turn is always queued for analysis.
        await db.flush()
        await ensure_pending_rows(db, [turn.id])
        await db.commit()
    except IntegrityError as exc:
        # Two turns of the same session arrived at once and both got the same number.
        await db.rollback()
        _remove(kept_audio)
        logger.warning("turn_conflict session=%s turn=%s", session_id, result["turn_number"])
        raise HTTPException(
            status_code=409,
            detail={"code": "turn_in_progress", "message": "Ya hay un turno en curso. Espera la respuesta e inténtalo de nuevo."},
        ) from exc

    # Runs after the response (and its voice reply) has been sent: the analysis adds no latency.
    background.add_task(
        run_turn_analysis, turn.id, analysis_llm, async_sessionmaker(db.bind, expire_on_commit=False), pronunciation
    )
    return TurnRead(
        turn_number=turn.turn_number,
        user_transcript=turn.user_transcript,
        reply_text=turn.reply_text,
        reply_audio_url=_reply_url(turn),
    )


@router.get("/{session_id}/turns", response_model=list[TurnSummary])
async def list_turns(
    session_id: int,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> list[TurnSummary]:
    await _own_session(db, session_id, user)
    turns = (await db.scalars(select(Turn).where(Turn.session_id == session_id).order_by(Turn.turn_number))).all()
    return [
        TurnSummary(
            turn_number=t.turn_number,
            user_transcript=t.user_transcript,
            reply_text=t.reply_text,
            reply_audio_url=_reply_url(t),
        )
        for t in turns
    ]


@router.get("/{session_id}/turns/{turn_number}/reply-audio")
async def get_reply_audio(
    session_id: int,
    turn_number: int,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> FileResponse:
    await _own_session(db, session_id, user)
    turn = await db.scalar(select(Turn).where(Turn.session_id == session_id, Turn.turn_number == turn_number))
    if turn is None or not turn.reply_audio_path or not Path(turn.reply_audio_path).is_file():
        raise HTTPException(status_code=404, detail={"code": "audio_not_found", "message": "Audio no encontrado."})
    return FileResponse(turn.reply_audio_path, media_type="audio/wav")


class ReplyReportCreate(BaseModel):
    reason: Literal["offensive", "harmful", "wrong", "other"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


@router.post("/{session_id}/turns/{turn_number}/flag", status_code=201)
async def flag_reply(
    session_id: int,
    turn_number: int,
    body: ReplyReportCreate,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict:
    """Report one of Guako's replies (offensive, harmful, wrong). Reporting the same reply again updates it."""
    await _own_session(db, session_id, user)
    turn = await db.scalar(select(Turn.id).where(Turn.session_id == session_id, Turn.turn_number == turn_number))
    if turn is None:
        raise HTTPException(status_code=404, detail={"code": "turn_not_found", "message": "Turno no encontrado."})
    report = await db.scalar(
        select(ReplyReport).where(
            ReplyReport.session_id == session_id, ReplyReport.turn_number == turn_number, ReplyReport.user_id == user.id
        )
    )
    if report is None:
        report = ReplyReport(user_id=user.id, session_id=session_id, turn_number=turn_number)
        db.add(report)
    report.reason = body.reason
    report.comment = body.comment or None
    await db.commit()
    logger.warning("reply_reported session=%s turn=%s reason=%s", session_id, turn_number, body.reason)
    return {"reported": True}


@router.get("/{session_id}/report", response_model=SessionReport)
async def get_report(
    session_id: int,
    background: BackgroundTasks,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    llm: Annotated[LLMProvider, Depends(get_analysis_llm_provider)],
    pronunciation: Annotated[PronunciationProvider | None, Depends(get_pronunciation_provider)],
) -> SessionReport:
    """The report plus, on each hard word, where the learner is in "now you say it" (not saved with it)."""
    report = await _build_report(session_id, background, user, db, llm, pronunciation)
    await attach_practice(db, report)
    return report


async def _add_memory(db: AsyncSession, session: ConversationSession, grammar: GrammarReport) -> None:
    """RAG 2: on each mistake, in how many earlier sessions of this learner it had already appeared (PostgreSQL only)."""
    if not grammar.errors or db.bind.dialect.name != "postgresql":
        return
    try:
        counts = await seen_before(db, session)
    except Exception:  # the memory is an extra: the report is complete without it
        logger.exception("memory_failed session=%s", session.id)
        return
    for error in grammar.errors:
        error.seen_before = counts.get((error.turn_number, error.original), 0)


async def _build_report(
    session_id: int,
    background: BackgroundTasks,
    user: User,
    db: AsyncSession,
    llm: LLMProvider,
    pronunciation: PronunciationProvider | None,
) -> SessionReport:
    """Built from the per-turn analyses (``turn_analyses``); it never calls the LLM while answering."""
    session = await _own_session(db, session_id, user)
    if session.ended_at is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "session_not_ended", "message": "El informe estará listo cuando termines la sesión."},
        )

    # A report saved before a dimension existed still says "pending" for it: rebuild it once.
    saved = session.report or {}
    placeholder = any((saved.get(d) or {}).get("status") == "pending" for d in ("pronunciation", "communication", "listening"))
    if session.report is not None and not placeholder:
        return SessionReport.model_validate(session.report)

    turns = (
        await db.scalars(
            select(Turn).where(Turn.session_id == session_id, Turn.turn_number != OPENING_TURN).order_by(Turn.turn_number)
        )
    ).all()
    if not turns:
        return SessionReport(
            session_id=session_id,
            user_turns=0,
            grammar=GrammarReport(status="empty", score=None, errors=[], turns_analyzed=0, turns_failed=0),
            fluency=FluencyReport(
                status="empty", score=None, words_per_minute=None, long_pauses=0, filler_words=0, total_words=0
            ),
            pronunciation=PronunciationReport(status="empty"),
            communication=JudgeReport(status="empty"),
            listening=JudgeReport(status="empty"),
        )

    # Turns saved before the analysis existed have no rows: queue them now (they show as pending until done).
    queued = await ensure_pending_rows(db, [t.id for t in turns])
    if queued:
        await db.commit()
        maker = async_sessionmaker(db.bind, expire_on_commit=False)
        for turn_id in queued:
            background.add_task(run_turn_analysis, turn_id, llm, maker, pronunciation)

    rows = (await db.scalars(select(TurnAnalysis).where(TurnAnalysis.turn_id.in_([t.id for t in turns])))).all()
    by_key = {(r.turn_id, r.dimension): r for r in rows}
    grammar_rows = {t.turn_number: by_key.get((t.id, AnalysisDimension.GRAMMAR.value)) for t in turns}
    fluency_results = []
    for t in turns:
        row = by_key.get((t.id, AnalysisDimension.FLUENCY.value))
        fluency_results.append(row.result if row is not None and row.status == AnalysisStatus.DONE.value else None)

    grammar = build_grammar_report(
        [(t.turn_number, t.user_transcript) for t in turns], grammar_rows
    )
    await _add_memory(db, session, grammar)
    fluency = build_fluency_report(fluency_results)
    pronunciation_report = build_pronunciation_report(
        [(t.turn_number, by_key.get((t.id, AnalysisDimension.PRONUNCIATION.value))) for t in turns]
    )
    communication, listening = (
        build_judge_report([(t.turn_number, by_key.get((t.id, dimension.value))) for t in turns])
        for dimension in (AnalysisDimension.COMMUNICATION, AnalysisDimension.LISTENING)
    )
    report = SessionReport(
        session_id=session_id,
        user_turns=len(turns),
        grammar=grammar,
        fluency=fluency,
        pronunciation=pronunciation_report,
        communication=communication,
        listening=listening,
    )
    # Only a complete report is saved: an "incomplete" one is rebuilt on the next request. Pronunciation
    # only has to be settled (nothing pending): a skipped or failed turn will not change by waiting.
    settled = pronunciation_report.turns_pending == 0 and communication.turns_pending == 0 and listening.turns_pending == 0
    if grammar.status == "ok" and fluency.status in ("ok", "empty") and settled:
        session.report = report.model_dump(mode="json")
        await db.commit()
    return report
