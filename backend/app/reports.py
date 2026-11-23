"""End-of-session report: schemas and the scoring code (no I/O, no LLM calls here).

Grammar score
    score = round(100 * max(0, 1 - errors / words)), over the turns that were analysed.
    One error per 10 words → 90; one per 2 words → 50; one per word or worse → 0.

Fluency score (computed from per-word timings, 0-100)
    wpm            = total words / total speaking minutes
    speaking time  = per turn, first word start → last word end (pauses inside a turn count)
    long pause     = a gap between two consecutive words of the same turn >= LONG_PAUSE_SECONDS
    filler         = a word in FILLER_WORDS (case and punctuation ignored)

    rate_part   = min(1, wpm / TARGET_WPM)
    pause_part  = max(0, 1 - long_pauses_per_minute / MAX_LONG_PAUSES_PER_MINUTE)
    filler_part = max(0, 1 - fillers / words / MAX_FILLER_RATIO)
    score       = round(100 * (0.5 * rate_part + 0.3 * pause_part + 0.2 * filler_part))

Pronunciation, communication and listening are not measured yet: status "pending", score null.
"""

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from app.stt import WordTiming

LONG_PAUSE_SECONDS = 1.0
FILLER_WORDS = frozenset({"uh", "um", "eh"})
TARGET_WPM = 120.0
MAX_LONG_PAUSES_PER_MINUTE = 6.0
MAX_FILLER_RATIO = 0.10
RATE_WEIGHT, PAUSE_WEIGHT, FILLER_WEIGHT = 0.5, 0.3, 0.2

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


class FluencyReport(BaseModel):
    status: Status
    score: int | None
    words_per_minute: float | None
    long_pauses: int
    filler_words: int
    total_words: int


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


def _normalize(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def compute_fluency(turns_words: Sequence[Sequence[WordTiming]]) -> FluencyReport:
    """Fluency from the word timings of each user turn. Turns without timings are skipped."""
    total_words = long_pauses = fillers = 0
    speaking_seconds = 0.0
    for words in turns_words:
        if not words:
            continue
        span = words[-1].end - words[0].start
        if span <= 0:
            continue
        speaking_seconds += span
        total_words += len(words)
        fillers += sum(1 for w in words if _normalize(w.word) in FILLER_WORDS)
        long_pauses += sum(1 for prev, nxt in zip(words, words[1:]) if nxt.start - prev.end >= LONG_PAUSE_SECONDS)

    if total_words == 0:
        return FluencyReport(
            status="empty", score=None, words_per_minute=None, long_pauses=0, filler_words=0, total_words=0
        )

    minutes = speaking_seconds / 60
    wpm = total_words / minutes
    rate_part = min(1.0, wpm / TARGET_WPM)
    pause_part = max(0.0, 1 - (long_pauses / minutes) / MAX_LONG_PAUSES_PER_MINUTE)
    filler_part = max(0.0, 1 - (fillers / total_words) / MAX_FILLER_RATIO)
    score = round(100 * (RATE_WEIGHT * rate_part + PAUSE_WEIGHT * pause_part + FILLER_WEIGHT * filler_part))
    return FluencyReport(
        status="ok",
        score=score,
        words_per_minute=round(wpm, 1),
        long_pauses=long_pauses,
        filler_words=fillers,
        total_words=total_words,
    )
