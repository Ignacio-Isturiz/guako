"""Helpers for the background-analysis tests: a scripted LLM and a way to run the analyses by hand."""

import asyncio
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.analysis.runner import ensure_pending_rows, run_turn_analysis
from app.db import Turn
from app.llm.errors import LLMRateLimitError


class ScriptedGrammarLLM:
    """Answers each grammar call with the next scripted item: a list of errors or an exception."""

    def __init__(self) -> None:
        self.script: list[object] = []
        self.prompts: list[str] = []

    def generate(self, prompt: str, response_model: type[BaseModel], *, system: str | None = None) -> BaseModel:
        self.prompts.append(prompt)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
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


def run_analyses(db_path: Path, llm: ScriptedGrammarLLM) -> None:
    """Queue and run the analysis of every saved turn, as the background task would."""

    async def _run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            ids = list((await db.scalars(select(Turn.id).order_by(Turn.id))).all())
            await ensure_pending_rows(db, ids)
            await db.commit()
        for turn_id in ids:
            await run_turn_analysis(turn_id, llm, maker)
        await engine.dispose()

    asyncio.run(_run())
