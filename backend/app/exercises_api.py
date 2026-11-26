"""The personalised practice: exercises built from the rules the learner got wrong.

  GET  /api/practice/exercises   -> a mixed session of exercises (no answers inside)
  POST /api/practice/check       -> is a written answer right? (choice, fill, fix)
  POST /api/practice/speak       -> is what the learner said the sentence asked for? (speak)

Nothing is stored from the answers: it is practice, not an evaluation (see app/exercises). The only thing kept is
WHICH exercises each learner already answered (id and date), so the next rounds bring ones they have not seen. The
audio of the speaking exercises is only used to transcribe it, in a temporary folder deleted right after.
"""

import random
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.deps import get_stt_provider
from app.config import settings
from app.db import ErrorEvent, ExerciseSeen, GeneratedExercise, Turn, User, async_session_maker, get_async_session
from app.exercises import build_plan, check_text, exercises_by_id, load_exercises, speech_matches
from app.exercises import generated, personal
from app.exercises.bank import Exercise
from app.practice import measure_seconds
from app.providers import chains
from app.rag.corpus import rules_by_id
from app.reports import ReportRule
from app.stt import STTProvider
from app.stt.errors import NoSpeechError, STTError
from app.stt.groq import SUPPORTED_EXTENSIONS
from app.users import current_active_user
from app.consents import user_with_terms

router = APIRouter(prefix="/api/practice", tags=["exercises"])

# A sentence is a few seconds: longer audio is refused (the app stops recording at 12 s).
SPEAK_MAX_SECONDS = 15.0
SPEAK_MAX_AUDIO_BYTES = 1_200_000
RANKED_RULES_LIMIT = 12
PERSONAL_LIMIT = 60  # the most recent mistakes that become exercises of the learner's own sentences
SEEN_LIMIT = 3000


class ExerciseOut(BaseModel):
    id: str
    kind: Literal["choice", "fill", "fix", "speak"]
    rule_id: str | None  # None: a mistake of the learner that no rule of the corpus explains
    rule_title: str | None
    prompt: str
    options: list[str] = []
    personal: bool = False  # made from the learner's own sentence


class Focus(BaseModel):
    rule_id: str
    title: str
    count: int  # times the learner made this mistake (0 when the rule was asked for by hand)


class ExercisesOut(BaseModel):
    exercises: list[ExerciseOut]
    focus: list[Focus]


class CheckIn(BaseModel):
    exercise_id: str
    answer: str


class AnswerOut(BaseModel):
    correct: bool
    expected: str  # the sentence or word that was asked for (the first accepted answer)
    rule: ReportRule | None  # None for the learner's own mistakes that have no rule


class SpeakOut(AnswerOut):
    heard: str


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _rule_card(rule_id: str) -> ReportRule | None:
    rule = rules_by_id().get(rule_id)
    if rule is None:
        return None
    return ReportRule(id=rule.id, title=rule.title, level=rule.level, rule=rule.rule, rule_es=rule.rule_es)


async def _exercise(db: AsyncSession, user: User, exercise_id: str) -> Exercise:
    """A bank exercise, or one of the learner's own (only ever its owner's)."""
    mine = personal.parse_id(exercise_id)
    if mine is not None:
        event_id, kind = mine
        row = (
            await db.execute(
                select(ErrorEvent, Turn.user_transcript)
                .join(Turn, Turn.id == ErrorEvent.turn_id)
                .where(ErrorEvent.id == event_id, ErrorEvent.user_id == user.id)
            )
        ).first()
        if row is not None:
            event, transcript = row
            made = personal.exercises_for(event.id, event.rule_id, transcript, event.original, event.correction)
            found = next((e for e in made if e.kind == kind), None)
            if found is not None:
                return found
    elif generated.parse_id(exercise_id) is not None:
        row = await db.get(GeneratedExercise, generated.parse_id(exercise_id)[0])
        found = next((e for e in generated.to_exercises(row) if e.id == exercise_id), None) if row else None
        if found is not None:
            return found
    elif exercise_id in exercises_by_id():
        return exercises_by_id()[exercise_id]
    raise _error(404, "exercise_not_found", "Ese ejercicio no existe.")


def _public(exercise: Exercise) -> ExerciseOut:
    options = list(exercise.options)
    random.shuffle(options)
    rule = rules_by_id().get(exercise.rule_id)
    return ExerciseOut(
        id=exercise.id,
        kind=exercise.kind,
        rule_id=rule.id if rule else None,
        rule_title=rule.title if rule else None,
        prompt=exercise.prompt,
        options=options,
        personal=exercise.personal,
    )


async def _own_exercises(db: AsyncSession, user: User, only_rule: str | None) -> list[Exercise]:
    """The learner's recent mistakes as "fix" and "speak" exercises, built with the sentence they said."""
    rows = (
        await db.execute(
            select(ErrorEvent, Turn.user_transcript)
            .join(Turn, Turn.id == ErrorEvent.turn_id)
            .where(ErrorEvent.user_id == user.id)
            .order_by(ErrorEvent.created_at.desc(), ErrorEvent.id.desc())
            .limit(PERSONAL_LIMIT)
        )
    ).all()
    made: list[Exercise] = []
    sentences: set[str] = set()
    for event, transcript in rows:
        if only_rule is not None and event.rule_id != only_rule:
            continue
        pair = personal.exercises_for(event.id, event.rule_id, transcript, event.original, event.correction)
        if not pair or pair[0].answers[0] in sentences:  # nothing buildable, or the same sentence from another turn
            continue
        sentences.add(pair[0].answers[0])
        made.extend(pair)
    return made


async def _last_seen(db: AsyncSession, user: User) -> dict[str, float]:
    rows = await db.execute(
        select(ExerciseSeen.exercise_id, ExerciseSeen.last_seen_at)
        .where(ExerciseSeen.user_id == user.id)
        .order_by(ExerciseSeen.last_seen_at.desc())
        .limit(SEEN_LIMIT)
    )
    return {r.exercise_id: r.last_seen_at.timestamp() for r in rows}


async def _mark_seen(db: AsyncSession, user: User, exercise_id: str) -> None:
    """Remember that this learner answered this exercise (id and date only)."""
    try:
        row = await db.get(ExerciseSeen, (user.id, exercise_id))
        if row is None:
            db.add(ExerciseSeen(user_id=user.id, exercise_id=exercise_id))
        else:
            row.times += 1
            row.last_seen_at = datetime.now(UTC)
        await db.commit()
    except IntegrityError:  # two answers at once created the row first: nothing to do
        await db.rollback()


async def _my_rules(db: AsyncSession, user: User) -> list[tuple[str, int]]:
    """The rules of the learner's mistakes, most frequent first (ties: the most recent first)."""
    rows = await db.execute(
        select(ErrorEvent.rule_id, func.count().label("n"), func.max(ErrorEvent.created_at).label("last"))
        .where(ErrorEvent.user_id == user.id, ErrorEvent.rule_id.is_not(None))
        .group_by(ErrorEvent.rule_id)
        .order_by(func.count().desc(), func.max(ErrorEvent.created_at).desc())
        .limit(RANKED_RULES_LIMIT)
    )
    return [(r.rule_id, int(r.n)) for r in rows if r.rule_id in rules_by_id()]


async def _replenish(rule_id: str) -> None:
    """Background: write more exercises for a rule whose pool is running low (see app/exercises/generated.py)."""
    await generated.replenish(async_session_maker, chains.analysis_llm(settings), rule_id)


def _running_low(rule_ids: list[str], pool: list[Exercise], seen: dict[str, float]) -> list[str]:
    """The rules with fewer unseen exercises than ``exercises_low_water``, in the order they were given."""
    low = []
    for rule_id in rule_ids:
        unseen = [e for e in [*load_exercises(), *pool] if e.rule_id == rule_id and e.id not in seen]
        if len(unseen) < settings.exercises_low_water:
            low.append(rule_id)
    return low


@router.get("/exercises", response_model=ExercisesOut)
async def get_exercises(
    background: BackgroundTasks,
    user: Annotated[User, Depends(user_with_terms)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    size: Annotated[int, Query(ge=1, le=20)] = 8,
    rule: Annotated[str | None, Query(max_length=80)] = None,
) -> ExercisesOut:
    """A session of ``size`` exercises. With ``rule`` it practises that one rule; without, the learner's own."""
    if rule is not None:
        if rule not in rules_by_id():
            raise _error(404, "rule_not_found", "Esa regla no existe.")
        ranked = [(rule, 0)]
    else:
        ranked = await _my_rules(db, user)
    ranked_ids = [r for r, _ in ranked]
    pool = await generated.pool_for(db, ranked_ids)
    seen = await _last_seen(db, user)
    plan = build_plan(ranked_ids, size, personal=await _own_exercises(db, user, rule), extra=pool, last_seen=seen)
    if settings.exercises_generation_enabled and settings.background_tasks_enabled:
        for rule_id in _running_low(ranked_ids[:3], pool, seen):  # only the rules this learner is working on
            background.add_task(_replenish, rule_id)
    counts = dict(ranked)
    focus = [
        Focus(rule_id=r, title=rules_by_id()[r].title, count=counts.get(r, 0))
        for r in dict.fromkeys(e.rule_id for e in plan)
        if r in rules_by_id()
    ]
    return ExercisesOut(exercises=[_public(e) for e in plan], focus=focus)


@router.post("/check", response_model=AnswerOut)
async def check_answer(
    body: CheckIn,
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> AnswerOut:
    exercise = await _exercise(db, user, body.exercise_id)
    if exercise.kind == "speak":
        raise _error(400, "use_speak", "Este ejercicio se contesta hablando.")
    if len(body.answer) > 300:
        raise _error(422, "answer_too_long", "La respuesta es demasiado larga.")
    await _mark_seen(db, user, exercise.id)
    return AnswerOut(correct=check_text(exercise, body.answer), expected=exercise.answers[0], rule=_rule_card(exercise.rule_id))


@router.post("/speak", response_model=SpeakOut)
async def check_speech(
    exercise_id: Annotated[str, Form(max_length=120)],
    audio: UploadFile,
    user: Annotated[User, Depends(user_with_terms)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
    stt: Annotated[STTProvider, Depends(get_stt_provider)],
) -> SpeakOut:
    exercise = await _exercise(db, user, exercise_id)
    if exercise.kind != "speak":
        raise _error(400, "use_check", "Este ejercicio no se contesta hablando.")
    extension = Path(audio.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise _error(415, "audio_format", "Formato de audio no soportado.")
    data = await audio.read(SPEAK_MAX_AUDIO_BYTES + 1)
    if not data:
        raise _error(400, "audio_empty", "El audio está vacío.")
    if len(data) > SPEAK_MAX_AUDIO_BYTES:
        raise _error(413, "audio_too_long", "El audio es demasiado largo para una frase.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"say{extension}"
        await run_in_threadpool(path.write_bytes, data)
        seconds = await run_in_threadpool(measure_seconds, path)
        if seconds is not None and seconds > SPEAK_MAX_SECONDS:
            raise _error(413, "audio_too_long", "El audio es demasiado largo para una frase.")
        try:
            # No context here on purpose: the recognizer must not be nudged towards the sentence we want to hear.
            heard = (await run_in_threadpool(stt.transcribe, str(path))).text.strip()
        except NoSpeechError:
            heard = ""
        except STTError as exc:
            raise _error(503, "service_busy", "El servicio de voz está ocupado. Inténtalo en un momento.") from exc
    await _mark_seen(db, user, exercise.id)
    return SpeakOut(
        correct=speech_matches(exercise, heard),
        expected=exercise.answers[0],
        heard=heard,
        rule=_rule_card(exercise.rule_id),
    )
