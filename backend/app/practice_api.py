"""POST /api/sessions/{id}/practice: the learner says one of the hard words, the server scores it.

The audio is only used for this scoring: it is written to a temporary folder and deleted right after.
"""

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis import runner
from app.conversation.deps import get_pronunciation_provider, get_stt_provider
from app.db import User, WordPractice, get_async_session
from app.practice import (
    PRACTICE_MAX_ATTEMPTS,
    PRACTICE_MAX_AUDIO_BYTES,
    PRACTICE_MAX_SECONDS,
    PRACTICE_PASS_SCORE,
    PRACTICE_RETRY_WAITS_SECONDS,
    heard_word,
    measure_seconds,
    normalize_word,
    practice_state,
    pronunciation_report,
)
from app.pronunciation import PronunciationProvider
from app.pronunciation.errors import (
    PronunciationAudioError,
    PronunciationError,
    PronunciationNoSpeechError,
    PronunciationProviderError,
    PronunciationRateLimitError,
    PronunciationTimeoutError,
)
from app.pronunciation.quota import can_spend, record_usage
from app.reports import HardSound, PracticeState
from app.sessions_api import _own_session
from app.stt import STTProvider
from app.stt.errors import NoSpeechError, STTError
from app.stt.groq import SUPPORTED_EXTENSIONS
from app.users import current_active_user

logger = logging.getLogger("app.practice")

router = APIRouter(prefix="/api/sessions", tags=["practice"])

# (session, word) pairs being scored right now: two requests for the same word never overlap.
_IN_FLIGHT: set[tuple[int, str]] = set()


class PracticeResult(BaseModel):
    # passed: lo lograste · retry: todavía cuesta, quedan intentos · locked: sin intentos · no_speech: no se oyó voz
    status: Literal["passed", "retry", "locked", "no_speech"]
    score: int | None
    ipa: str
    heard: str = ""  # what the speech-to-text heard, to tell the learner ("sheep" instead of "ship")
    heard_ok: bool = True
    sounds: list[HardSound]
    weakest_sound: int | None
    practice: PracticeState


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@router.post("/{session_id}/practice", response_model=PracticeResult)
async def practice_word(
    session_id: int,
    word: Annotated[str, Form(max_length=64)],
    audio: UploadFile,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    provider: Annotated[PronunciationProvider | None, Depends(get_pronunciation_provider)],
    stt: Annotated[STTProvider, Depends(get_stt_provider)],
) -> PracticeResult:
    session = await _own_session(db, session_id, user)
    if session.ended_at is None:
        raise _error(409, "session_not_ended", "Practica las palabras cuando termines la sesión.")
    if not session.audio_consent:
        raise _error(403, "audio_consent_required", "Activa \"Guardar mi audio\" en Ajustes para practicar tus palabras.")
    key = normalize_word(word)
    hard = {normalize_word(w.word): w for w in (await pronunciation_report(db, session_id)).hard_words}
    if key not in hard:
        raise _error(404, "word_not_found", "Esa palabra no está en tu lista.")
    if provider is None:
        raise _error(503, "practice_failed", "La práctica no está disponible ahora.")

    row = await db.scalar(select(WordPractice).where(WordPractice.session_id == session_id, WordPractice.word == key))
    if practice_state(row).locked:
        raise _error(409, "practice_locked", "Esta palabra ya no admite más intentos.")

    extension = Path(audio.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise _error(415, "audio_format", "Formato de audio no soportado.")
    data = await audio.read(PRACTICE_MAX_AUDIO_BYTES + 1)
    if not data:
        raise _error(400, "audio_empty", "El audio está vacío.")
    if len(data) > PRACTICE_MAX_AUDIO_BYTES:
        raise _error(413, "audio_too_long", "El audio es demasiado largo para una palabra.")

    if (session_id, key) in _IN_FLIGHT:
        raise _error(409, "practice_in_progress", "Ya se está evaluando esta palabra.")
    _IN_FLIGHT.add((session_id, key))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"word{extension}"
            await run_in_threadpool(path.write_bytes, data)
            seconds = await run_in_threadpool(measure_seconds, path)
            if seconds is None:
                seconds = PRACTICE_MAX_SECONDS  # unknown length: count the most that is accepted
            elif seconds > PRACTICE_MAX_SECONDS:
                raise _error(413, "audio_too_long", "El audio es demasiado largo para una palabra.")
            if not await can_spend(db, seconds):
                raise _error(503, "quota_exhausted", "El servicio de voz alcanzó su límite gratuito de este mes.")
            return await _score(db, session_id, key, row, path, seconds, provider, stt)
    finally:
        _IN_FLIGHT.discard((session_id, key))


async def _score(
    db: AsyncSession,
    session_id: int,
    key: str,
    row: WordPractice | None,
    path: Path,
    seconds: float,
    provider: PronunciationProvider,
    stt: STTProvider,
) -> PracticeResult:
    if row is None:
        row = WordPractice(session_id=session_id, word=key)
        db.add(row)
        await db.flush()

    sent: list[int] = []
    try:
        result = await run_in_threadpool(
            runner._score_with_backoff, provider, str(path), key, sent, PRACTICE_RETRY_WAITS_SECONDS
        )
    except PronunciationNoSpeechError:
        # Nothing to assess: the call is counted, the attempt is not.
        row.calls += 1
        await db.commit()
        return PracticeResult(status="no_speech", score=None, ipa="", sounds=[], weakest_sound=None, practice=practice_state(row))
    except (PronunciationRateLimitError, PronunciationProviderError, PronunciationTimeoutError) as exc:
        await db.rollback()
        raise _error(503, "service_busy", "El servicio de voz está ocupado. Inténtalo en un momento.") from exc
    except PronunciationAudioError as exc:
        await db.rollback()
        code = "audio_format" if exc.code == "bad_audio" else "practice_failed"
        raise _error(422 if code == "audio_format" else 503, code, "No pudimos leer ese audio.") from exc
    except PronunciationError as exc:
        await db.rollback()
        logger.warning("practice_failed session=%s error=%s", session_id, exc.code)
        raise _error(502, "practice_failed", "No pudimos evaluar tu pronunciación ahora.") from exc
    finally:
        await record_usage(db, len(sent) * seconds)

    # Second opinion: Azure alone is generous. The word only counts if Whisper heard it too.
    try:
        heard = (await run_in_threadpool(stt.transcribe, str(path))).text.strip()
    except NoSpeechError:
        heard = ""
    except STTError as exc:
        row.calls += 1  # Azure already took the audio: the call counts, the attempt does not
        await db.commit()
        raise _error(503, "service_busy", "El servicio de voz está ocupado. Inténtalo en un momento.") from exc
    heard_ok = heard_word(heard, key)

    match = next((w for w in result.words if normalize_word(w.word) == key), None)
    if match is None and len(result.words) == 1:
        match = result.words[0]
    score = match.accuracy if match is not None else (result.accuracy_score or 0.0)

    row.calls += 1
    row.attempts += 1
    row.best_score = max(score, row.best_score or 0.0)
    row.passed = score >= PRACTICE_PASS_SCORE and heard_ok
    await db.commit()

    sounds = [HardSound(ipa=p.ipa or p.phoneme, score=round(p.accuracy)) for p in (match.phonemes if match else [])]
    weakest = min(range(len(sounds)), key=lambda i: sounds[i].score) if sounds else None
    state = practice_state(row)
    status = "passed" if row.passed else ("locked" if row.attempts >= PRACTICE_MAX_ATTEMPTS else "retry")
    return PracticeResult(
        status=status,
        score=round(score),
        ipa="".join(s.ipa for s in sounds),
        heard=heard,
        heard_ok=heard_ok,
        sounds=sounds,
        weakest_sound=weakest,
        practice=state,
    )
