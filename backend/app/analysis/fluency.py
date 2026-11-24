"""Fluency of one turn, computed from the per-word timings with plain code (no LLM).

Per turn
    speaking time  = first word start → last word end (pauses inside the turn count)
    wpm            = words / speaking minutes
    long pause     = a gap between two consecutive words >= LONG_PAUSE_SECONDS
    filler         = a word in FILLER_WORDS (case and punctuation ignored)

A metric that cannot be measured (no word timings) is ``{"status": "unavailable"}``: it is never
guessed from the transcript or defaulted to 0.

Session score (0-100), from the totals of the turns that have timings
    rate_part   = min(1, wpm / TARGET_WPM)
    pause_part  = max(0, 1 - long_pauses_per_minute / MAX_LONG_PAUSES_PER_MINUTE)
    filler_part = max(0, 1 - fillers / words / MAX_FILLER_RATIO)
    score       = round(100 * (0.5 * rate_part + 0.3 * pause_part + 0.2 * filler_part))
    e.g. 108 wpm, 1 pause in 5 s of speech (12/min), 1 filler in 9 words → 0.9, 0, 0 → score 45
"""

import re
from collections.abc import Sequence

from app.stt import WordTiming

LONG_PAUSE_SECONDS = 1.0
FILLER_WORDS = frozenset({"uh", "um", "eh"})
TARGET_WPM = 120.0
MAX_LONG_PAUSES_PER_MINUTE = 6.0
MAX_FILLER_RATIO = 0.10
RATE_WEIGHT, PAUSE_WEIGHT, FILLER_WEIGHT = 0.5, 0.3, 0.2

METRICS = ("words_per_minute", "long_pauses", "filler_words")
UNAVAILABLE = {"status": "unavailable"}


def _normalize(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def _ok(value: float | int) -> dict:
    return {"status": "ok", "value": value}


def analyze_fluency(words: Sequence[WordTiming] | None) -> dict:
    """The JSON stored in ``turn_analyses.result`` for the fluency dimension."""
    span = words[-1].end - words[0].start if words else 0.0
    if not words or span <= 0:
        return {"total_words": len(words or []), "speaking_seconds": None, "metrics": {m: dict(UNAVAILABLE) for m in METRICS}}
    pauses = sum(1 for prev, nxt in zip(words, words[1:]) if nxt.start - prev.end >= LONG_PAUSE_SECONDS)
    fillers = sum(1 for w in words if _normalize(w.word) in FILLER_WORDS)
    return {
        "total_words": len(words),
        "speaking_seconds": round(span, 3),
        "metrics": {
            "words_per_minute": _ok(round(len(words) / (span / 60), 1)),
            "long_pauses": _ok(pauses),
            "filler_words": _ok(fillers),
        },
    }


def fluency_score(wpm: float, long_pauses_per_minute: float, filler_ratio: float) -> int:
    rate_part = min(1.0, wpm / TARGET_WPM)
    pause_part = max(0.0, 1 - long_pauses_per_minute / MAX_LONG_PAUSES_PER_MINUTE)
    filler_part = max(0.0, 1 - filler_ratio / MAX_FILLER_RATIO)
    return round(100 * (RATE_WEIGHT * rate_part + PAUSE_WEIGHT * pause_part + FILLER_WEIGHT * filler_part))
