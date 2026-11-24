"""Helpers for the background-analysis tests: a scripted LLM and a way to run the analyses by hand."""

import asyncio
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.analysis.runner import ensure_pending_rows, run_turn_analysis
from app.db import Turn
from app.llm.errors import LLMRateLimitError
from app.pronunciation import PronunciationProvider, PronunciationResult
from app.pronunciation.errors import PronunciationRateLimitError


def judgement(*, communication: int = 4, listening: int | None = 5, confidence: float = 0.9, asked_to_repeat: bool = False) -> dict:
    """A judge answer as the model would write it."""
    return {
        "communication": {"score": communication, "rationale": "Clear enough.", "confidence": confidence},
        "listening": None if listening is None else {"score": listening, "rationale": "On topic.", "confidence": confidence},
        "asked_to_repeat": asked_to_repeat,
    }


DEFAULT_JUDGEMENT = judgement()


def is_judge(response_model: type) -> bool:
    return "communication" in response_model.model_fields


class ScriptedGrammarLLM:
    """Answers each grammar call with the next scripted item: a list of errors or an exception.

    The judge has its own script (``judgements``: dicts or exceptions) and its own prompt list; by default it
    answers with a clear, confident judgement. Grammar tests never see the judge's calls.
    """

    def __init__(self) -> None:
        self.script: list[object] = []
        self.prompts: list[str] = []
        self.judgements: list[object] = []
        self.judge_prompts: list[str] = []

    def generate(self, prompt: str, response_model: type[BaseModel], *, system: str | None = None) -> BaseModel:
        if is_judge(response_model):
            self.judge_prompts.append(prompt)
            item = self.judgements.pop(0) if self.judgements else DEFAULT_JUDGEMENT
            if isinstance(item, Exception):
                raise item
            return response_model.model_validate(item)
        self.prompts.append(prompt)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):  # a full answer: {"errors": [...], "intended_text": "..."}
            return response_model(**item)
        return response_model(errors=item)


def err(original: str, correction: str, confidence: float = 0.95, error_type: str = "verb_tense") -> dict:
    return {
        "original": original,
        "correction": correction,
        "error_type": error_type,
        "explanation": "Use the past.",
        "confidence": confidence,
    }


def rate_limited(times: int = 4) -> list[Exception]:
    """A 429 on every attempt of one analysis (the first try plus the three retries)."""
    return [LLMRateLimitError("429") for _ in range(times)]


class ScriptedPronunciation(PronunciationProvider):
    """Answers each call with the next scripted item (a result or an exception). Never touches Azure."""

    max_audio_seconds = 28.0

    def __init__(self, script: list[object] | None = None) -> None:
        self.script: list[object] = script or []
        self.calls: list[tuple[str, str]] = []  # (audio_path, reference_text)

    def score_turn(self, audio_path: str, reference_text: str) -> PronunciationResult:
        self.calls.append((audio_path, reference_text))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]


def busy(times: int = 4) -> list[Exception]:
    """A 429 on every attempt of one analysis (the first try plus the three retries)."""
    return [PronunciationRateLimitError("429") for _ in range(times)]


def run_analyses(db_path: Path, llm: ScriptedGrammarLLM, pronunciation: PronunciationProvider | None = None) -> None:
    """Queue and run the analysis of every saved turn, as the background task would."""

    async def _run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            ids = list((await db.scalars(select(Turn.id).order_by(Turn.id))).all())
            await ensure_pending_rows(db, ids)
            await db.commit()
        for turn_id in ids:
            await run_turn_analysis(turn_id, llm, maker, pronunciation)
        await engine.dispose()

    asyncio.run(_run())
