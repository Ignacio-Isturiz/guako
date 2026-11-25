"""Exercises written by the LLM, accepted only if the grammar analyser agrees (layer 2 of the personalised practice).

The hand-written bank is finite: a learner who gets many exercises of one rule eventually has seen them all. When
the exercises a learner has not seen for a rule run low, the LLM writes a new batch (one choice, one gap and one
correction) in the background. An LLM writing "the correct sentence" can be wrong, so nothing it writes is trusted:
every sentence goes through the grammar analyser the project already uses (and evaluates), and an exercise is
stored only when
- every sentence that must be correct gets NO error, and
- every sentence that must be wrong gets at least one error, and
- it is not too similar to an exercise the rule already has.
Anything else is dropped (never stored, never shown). The analyser is the same kind of model, so this lowers the
chance of a wrong exercise a lot but does not make it zero: the CLI (scripts/generate_exercises.py) prints what
was accepted so a person can review it.

It never raises into a request: it runs after the response, and a failure only means "no new exercises today".
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.grammar import analyze_grammar
from app.config import settings
from app.db import GeneratedExercise
from app.exercises.bank import Exercise, load_exercises
from app.exercises.check import normalize
from app.llm.base import LLMProvider
from app.prompts import load_prompt
from app.rag.corpus import Rule, rules_by_id

logger = logging.getLogger("app.exercises")

CHOICE_PROMPT = "Which sentence is correct?"
GAP = "___"
# Two sentences sharing this much of their words are "the same exercise" for the learner.
DUPLICATE_JACCARD = 0.7
SPEAK_SUFFIX = ":speak"
PREFIX = "gen:"


# ── what the LLM returns ────────────────────────────────────────────────────

class GenChoice(BaseModel):
    right: str
    wrong: list[str] = Field(min_length=2, max_length=2)


class GenFill(BaseModel):
    sentence: str
    answer: str
    wrong_answer: str
    hint: str = ""  # shown in brackets: makes the answer the only one that fits


class GenFix(BaseModel):
    wrong: str
    right: str


class GenBatch(BaseModel):
    choice: GenChoice
    fill: GenFill
    fix: GenFix


@dataclass
class Candidate:
    """One exercise to verify: the row to store and the sentences the analyser must judge."""

    kind: str
    prompt: str
    options: list[str]
    answers: list[str]
    must_be_correct: list[str]
    must_have_error: list[str]

    @property
    def signature(self) -> str:
        """What identifies the exercise to the learner: a choice always asks the same question, so its sentence."""
        return self.answers[0] if self.kind == "choice" else self.prompt


@dataclass
class Report:
    rule_id: str
    accepted: list[GeneratedExercise] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)  # kind -> why
    skipped: str = ""  # why nothing was tried (caps, cooldown…)


# ── turning the LLM output into candidates ──────────────────────────────────

def _words(text: str) -> set[str]:
    return set(normalize(text).split())


def too_similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= DUPLICATE_JACCARD


def candidates_from(batch: GenBatch) -> tuple[list[Candidate], dict[str, str]]:
    """The structurally valid candidates of a batch, and why the others are not."""
    made: list[Candidate] = []
    rejected: dict[str, str] = {}

    sentences = [batch.choice.right, *batch.choice.wrong]
    if any(not s.strip() for s in sentences) or len({normalize(s) for s in sentences}) != 3:
        rejected["choice"] = "the three sentences are not three different ones"
    else:
        made.append(Candidate("choice", CHOICE_PROMPT, sentences, [sentences[0]], sentences[:1], sentences[1:]))

    fill = batch.fill
    answer, wrong_answer = fill.answer.strip(), fill.wrong_answer.strip()
    hint = fill.hint.strip().strip("()")
    if fill.sentence.count(GAP) != 1 or not answer or not wrong_answer or normalize(answer) == normalize(wrong_answer):
        rejected["fill"] = "the gap or its answers are malformed"
    elif not hint:
        rejected["fill"] = "no hint: other words could also fit the gap"
    elif len(answer.split()) > 3:
        rejected["fill"] = "the answer is too long to be one gap"
    else:
        made.append(
            Candidate(
                "fill", f"{fill.sentence.strip()} ({hint})", [], [answer],
                [fill.sentence.replace(GAP, answer)], [fill.sentence.replace(GAP, wrong_answer)],
            )
        )

    fix = batch.fix
    if not fix.wrong.strip() or not fix.right.strip() or normalize(fix.wrong) == normalize(fix.right):
        rejected["fix"] = "the wrong and the right sentence are the same"
    else:
        made.append(Candidate("fix", fix.wrong.strip(), [], [fix.right.strip()], [fix.right], [fix.wrong]))
    return made, rejected


def verify(llm: LLMProvider, candidate: Candidate, existing: list[str]) -> str | None:
    """None when the candidate is accepted, else the reason. Stops at the first failed check (each one is an LLM call)."""
    if any(too_similar(candidate.signature, other) for other in existing):
        return "too similar to an existing exercise"
    for sentence in candidate.must_be_correct:
        if analyze_grammar(llm, sentence)["errors"]:
            return f"the analyser finds an error in what should be correct: {sentence!r}"
    for sentence in candidate.must_have_error:
        if not analyze_grammar(llm, sentence)["errors"]:
            return f"the analyser finds no error in what should be wrong: {sentence!r}"
    return None


def _prompt_for(rule: Rule, avoid: list[str]) -> str:
    return load_prompt(
        "exercise_gen",
        1,
        rule_title=rule.title,
        rule=rule.rule,
        examples="\n".join(f"- {e.replace('->', '=>')}" for e in rule.examples),
        avoid="\n".join(f"- {a}" for a in avoid[:12]) or "(none)",
    )


def write_and_check(llm: LLMProvider, rule: Rule, existing: list[str]) -> tuple[list[Candidate], dict[str, str]]:
    """One batch from the LLM, verified. Synchronous (several LLM calls): run it in a thread."""
    batch = llm.generate(_prompt_for(rule, existing), GenBatch)
    assert isinstance(batch, GenBatch)
    candidates, rejected = candidates_from(batch)
    accepted: list[Candidate] = []
    seen = list(existing)
    for candidate in candidates:
        reason = verify(llm, candidate, seen)
        if reason is None:
            accepted.append(candidate)
            seen.append(candidate.signature)
        else:
            rejected[candidate.kind] = reason
    return accepted, rejected


# ── the pool of a rule ──────────────────────────────────────────────────────

def to_exercises(row: GeneratedExercise) -> list[Exercise]:
    """The exercises a stored row gives: itself, plus a speaking one when it is a correction."""
    base = f"{PREFIX}{row.id}"
    options, answers = tuple(row.options or ()), tuple(row.answers or ())
    exercise = Exercise(base, row.rule_id, row.kind, row.prompt, options=options, answers=answers)  # type: ignore[arg-type]
    if row.kind != "fix":
        return [exercise]
    speak = Exercise(base + SPEAK_SUFFIX, row.rule_id, "speak", answers[0], answers=(answers[0],), wrong=row.prompt)
    return [exercise, speak]


def parse_id(exercise_id: str) -> tuple[int, str] | None:
    """``gen:12`` -> (12, kind of the row's exercise) / ``gen:12:speak`` -> (12, "speak"); None if not generated."""
    if not exercise_id.startswith(PREFIX):
        return None
    rest = exercise_id[len(PREFIX):]
    number, _, tail = rest.partition(":")
    if not number.isdigit() or tail not in ("", "speak"):
        return None
    return int(number), "speak" if tail else "row"


async def pool_for(db: AsyncSession, rule_ids: list[str]) -> list[Exercise]:
    rows = (await db.scalars(select(GeneratedExercise).where(GeneratedExercise.rule_id.in_(rule_ids)))).all()
    return [e for row in rows for e in to_exercises(row)]


def signature_of(exercise: Exercise) -> str:
    return exercise.answers[0] if exercise.kind == "choice" else exercise.prompt


def bank_signatures(rule_id: str) -> list[str]:
    """What the bank already has for a rule, to avoid writing the same exercise again."""
    return [signature_of(e) for e in load_exercises() if e.rule_id == rule_id and e.kind != "speak"]


# ── replenishing in the background ──────────────────────────────────────────

_IN_FLIGHT: set[str] = set()
_LAST_TRY: dict[str, float] = {}


async def replenish(maker: async_sessionmaker[AsyncSession], llm: LLMProvider, rule_id: str) -> Report:
    """Write, check and store one batch for a rule, unless a cap says to wait. Never raises."""
    report = Report(rule_id)
    rule = rules_by_id().get(rule_id)
    if rule is None:
        report.skipped = "unknown rule"
        return report
    if rule_id in _IN_FLIGHT:
        report.skipped = "already being written"
        return report
    if time.monotonic() - _LAST_TRY.get(rule_id, -1e9) < settings.exercises_generation_cooldown_seconds:
        report.skipped = "tried a moment ago"
        return report
    _IN_FLIGHT.add(rule_id)
    _LAST_TRY[rule_id] = time.monotonic()
    try:
        async with maker() as db:
            stored = list((await db.scalars(select(GeneratedExercise).where(GeneratedExercise.rule_id == rule_id))).all())
            if len(stored) >= settings.exercises_max_generated_per_rule:
                report.skipped = "the pool of this rule is full"
                return report
            since = datetime.now(UTC) - timedelta(days=1)
            today = await db.scalar(select(func.count()).select_from(GeneratedExercise).where(GeneratedExercise.created_at >= since))
            if (today or 0) >= settings.exercises_daily_generation_limit:
                report.skipped = "the daily limit was reached"
                return report
            existing = bank_signatures(rule_id) + [signature_of(e) for r in stored for e in to_exercises(r)[:1]]
            accepted, report.rejected = await run_in_threadpool(write_and_check, llm, rule, existing)
            for candidate in accepted:
                row = GeneratedExercise(
                    rule_id=rule_id, kind=candidate.kind, prompt=candidate.prompt,
                    options=candidate.options, answers=candidate.answers,
                )
                db.add(row)
                report.accepted.append(row)
            await db.commit()
        logger.info("exercises_generated rule=%s accepted=%d rejected=%s", rule_id, len(report.accepted), report.rejected)
    except Exception:  # LLM down or out of quota, invalid output…: no new exercises this time
        logger.exception("exercises_generation_failed rule=%s", rule_id)
        report.skipped = "failed"
    finally:
        _IN_FLIGHT.discard(rule_id)
    return report
