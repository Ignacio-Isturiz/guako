"""Conversation endpoints.

POST /api/sessions                                    → create a session (level, topic)
POST /api/sessions/{id}/turns                         → one audio turn: audio in, tutor reply out
GET  /api/sessions/{id}/turns/{n}/reply-audio         → the tutor's audio for turn n
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.conversation.deps import get_stt_provider, get_tts_provider
from app.conversation.graph import build_graph
from app.conversation.state import ConversationState, Message
from app.db import ConversationSession, Turn, User, get_async_session
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.stt import STTProvider
from app.stt.groq import SUPPORTED_EXTENSIONS
from app.tts import TTSProvider
from app.usage import seconds_used_today
from app.users import current_active_user

logger = logging.getLogger("app.conversation")

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

Level = Literal["A1", "A2", "B1", "B2", "C1"]
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SessionCreate(BaseModel):
    level: Level
    topic: Topic


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    topic: str
    audio_consent: bool
    created_at: datetime


class TurnRead(BaseModel):
    turn_number: int
    reply_text: str
    reply_audio_url: str


def _reply_audio_url(session_id: int, turn_number: int) -> str:
    return f"/api/sessions/{session_id}/turns/{turn_number}/reply-audio"


async def _own_session(db: AsyncSession, session_id: int, user: User) -> ConversationSession:
    """The session if it belongs to ``user``; 404 otherwise (never reveals other users' sessions)."""
    session = await db.get(ConversationSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Sesión no encontrada."})
    return session


@router.post("", status_code=201, response_model=SessionRead)
async def create_session(
    body: SessionCreate,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> ConversationSession:
    session = ConversationSession(user_id=user.id, level=body.level, topic=body.topic)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


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


@router.post("/{session_id}/turns", status_code=201, response_model=TurnRead)
async def create_turn(
    session_id: int,
    audio: UploadFile,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    stt: Annotated[STTProvider, Depends(get_stt_provider)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
    tts: Annotated[TTSProvider, Depends(get_tts_provider)],
) -> TurnRead:
    session = await _own_session(db, session_id, user)
    if session.ended_at is not None:
        raise HTTPException(status_code=409, detail={"code": "session_ended", "message": "Esta sesión ya terminó."})

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
        "turn_number": completed,
        "messages": messages,
        "user_audio_path": str(user_audio),
    }
    graph = build_graph(stt, llm, tts)
    try:
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
        reply_audio_path=result["reply_audio_path"],
        user_audio_seconds=result["user_audio_seconds"],
        reply_audio_seconds=result["reply_audio_seconds"],
        word_timestamps=result.get("user_words"),
    )
    db.add(turn)
    try:
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

    return TurnRead(
        turn_number=turn.turn_number,
        reply_text=turn.reply_text,
        reply_audio_url=_reply_audio_url(session_id, turn.turn_number),
    )


@router.get("/{session_id}/turns/{turn_number}/reply-audio")
async def get_reply_audio(
    session_id: int,
    turn_number: int,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> FileResponse:
    await _own_session(db, session_id, user)
    turn = await db.scalar(select(Turn).where(Turn.session_id == session_id, Turn.turn_number == turn_number))
    if turn is None or not Path(turn.reply_audio_path).is_file():
        raise HTTPException(status_code=404, detail={"code": "audio_not_found", "message": "Audio no encontrado."})
    return FileResponse(turn.reply_audio_path, media_type="audio/wav")
