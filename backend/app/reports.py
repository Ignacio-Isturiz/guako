"""End-of-session report: schemas and the aggregation of the per-turn analyses (no I/O, no LLM here).

The analyses themselves are made in the background after each turn (app/analysis) and stored in
``turn_analyses``; the report only reads them.

Grammar score
    score = round(100 * max(0, 1 - errors / words)), over the turns whose analysis is done.
    One error per 10 words → 90; one per 2 words → 50; one per word or worse → 0.
    Only errors above the confidence threshold count (see app/analysis/grammar.py).

Fluency score: formula in app/analysis/fluency.py, computed from the totals of the turns with timings.

Status of a dimension: ``ok`` every turn analysed · ``incomplete`` some turns pending, failed or never
queued (the figures cover the rest) · ``empty`` nothing to measure.

Pronunciation, communication and listening are not measured yet: status "pending", score null.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel

from app.analysis.fluency import LONG_PAUSE_SECONDS, analyze_fluency, fluency_score
from app.enums import AnalysisStatus
from app.stt import WordTiming

__all__ = ["LONG_PAUSE_SECONDS"]

# empty: nothing to measure · incomplete: some turns could not be analysed · pending: not built yet
Status = Literal["ok", "incomplete", "empty", "pending"]


class ReportGrammarError(BaseModel):
    turn_number: int
    original: str
    correction: str
    error_type: str
    explanation: str


class GrammarReport(BaseModel):
    status: Status
    score: int | None
    errors: list[ReportGrammarError]
    turns_analyzed: int
    turns_failed: int
    turns_pending: int = 0  # queued, still running, or never queued (old sessions)


class FluencyReport(BaseModel):
    status: Status
    score: int | None
    words_per_minute: float | None
    long_pauses: int
    filler_words: int
    total_words: int
    # Metrics no turn could provide (e.g. no word timings): their value above is a placeholder, not data.
    unavailable: list[str] = []
    turns_without_timings: int = 0


class PendingDimension(BaseModel):
    status: Literal["pending"] = "pending"
    score: None = None


class SessionReport(BaseModel):
    session_id: int
    user_turns: int
    grammar: GrammarReport
    fluency: FluencyReport
    pronunciation: PendingDimension = PendingDimension()
    communication: PendingDimension = PendingDimension()
    listening: PendingDimension = PendingDimension()


def count_words(text: str) -> int:
    return len(text.split())


def grammar_score(errors: int, words: int) -> int | None:
    if words <= 0:
        return None
    return round(100 * max(0.0, 1 - errors / words))


def _turn_status(row: object | None) -> str:
    """Status of an analysis row; a turn that was never queued counts as pending."""
    return getattr(row, "status", AnalysisStatus.PENDING.value)


def build_grammar_report(turns: Sequence[tuple[int, str]], rows: Mapping[int, object | None]) -> GrammarReport:
    """``turns`` = (turn_number, transcript); ``rows`` = the grammar analysis row of each turn_number."""
    errors: list[ReportGrammarError] = []
    analyzed = failed = pending = analyzed_words = 0
    for number, transcript in turns:
        row = rows.get(number)
        status = _turn_status(row)
        if status == AnalysisStatus.DONE.value:
            analyzed += 1
            analyzed_words += count_words(transcript)
            errors.extend(
                ReportGrammarError(turn_number=number, **{k: e[k] for k in ("original", "correction", "error_type", "explanation")})
                for e in (row.result or {}).get("errors", [])  # type: ignore[union-attr]
            )
        elif status == AnalysisStatus.FAILED.value:
            failed += 1
        else:
            pending += 1
    return GrammarReport(
        status="incomplete" if failed or pending else "ok",
        score=grammar_score(len(errors), analyzed_words) if analyzed else None,
        errors=errors,
        turns_analyzed=analyzed,
        turns_failed=failed,
        turns_pending=pending,
    )


def build_fluency_report(results: Sequence[dict | None]) -> FluencyReport:
    """``results`` = the stored result of each user turn's fluency analysis (None = not done)."""
    done = [r for r in results if r is not None]
    timed = [r for r in done if r["metrics"]["words_per_minute"]["status"] == "ok"]
    total_words = sum(r["total_words"] for r in timed)
    seconds = sum(r["speaking_seconds"] for r in timed)
    pauses = sum(r["metrics"]["long_pauses"]["value"] for r in timed)
    fillers = sum(r["metrics"]["filler_words"]["value"] for r in timed)
    unavailable = [] if timed else ["words_per_minute", "long_pauses", "filler_words"]
    missing = len(results) - len(done)

    if not timed:
        return FluencyReport(
            status="incomplete" if missing else "empty",
            score=None,
            words_per_minute=None,
            long_pauses=0,
            filler_words=0,
            total_words=0,
            unavailable=unavailable,
            turns_without_timings=len(done),
        )
    minutes = seconds / 60
    wpm = total_words / minutes
    return FluencyReport(
        status="incomplete" if missing else "ok",
        score=fluency_score(wpm, pauses / minutes, fillers / total_words),
        words_per_minute=round(wpm, 1),
        long_pauses=pauses,
        filler_words=fillers,
        total_words=total_words,
        turns_without_timings=len(done) - len(timed),
    )


def compute_fluency(turns_words: Sequence[Sequence[WordTiming]]) -> FluencyReport:
    """Fluency straight from word timings (analyse each turn, then aggregate)."""
    return build_fluency_report([analyze_fluency(words) for words in turns_words])
