"""Word practice ("now you say it"): rules, and the state that the report shows next to each hard word.

The learner says one of the words that were hard; Azure scores it; the server decides:
  - score >= PRACTICE_PASS_SCORE  -> passed, and the word is locked for good in that session;
  - otherwise it uses one of PRACTICE_MAX_ATTEMPTS scored attempts; with none left the word is locked.
Silence or noise that Azure could not recognise does not use an attempt, but every call is counted
(PRACTICE_MAX_CALLS) so nobody can loop on the free quota.

Fairness: the messages and the status names say "passed" / "still hard", never that something is
"wrong" or that the accent is bad (see the rule in app/reports.py).
"""

import re
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.opening import OPENING_TURN
from app.db import Turn, TurnAnalysis, WordPractice
from app.enums import AnalysisDimension
from app.reports import PracticeState, PronunciationReport, SessionReport, build_pronunciation_report

# Strict on purpose: with 75 most real words passed at the first try (the median word scores 94 in a
# sentence). Passing also needs Whisper to hear the word (see ``heard_word``).
PRACTICE_PASS_SCORE = 90.0
PRACTICE_MAX_ATTEMPTS = 2
PRACTICE_MAX_CALLS = 4
# One word is a second or two; the app stops recording at 5 s. Longer audio is refused.
PRACTICE_MAX_SECONDS = 7.0
PRACTICE_MAX_AUDIO_BYTES = 500_000
# Someone is waiting for the answer: fewer retries than the background analysis.
PRACTICE_RETRY_WAITS_SECONDS = (1.0, 3.0)


def normalize_word(word: str) -> str:
    """Key of a word: lowercase, without punctuation ("Beach," and "beach" are the same word)."""
    return re.sub(r"[^\w']", "", word.lower())[:64]


def heard_word(transcript: str, key: str) -> bool:
    """Did the speech-to-text hear the target word? Azure scores the sounds against the word it is given,
    so it can be generous with a different word that sounds alike; Whisper, hearing one word with no
    context, writes what was actually said ("sheep" for "ship")."""
    return key in [normalize_word(token) for token in transcript.split()]


def practice_state(row: WordPractice | None) -> PracticeState:
    attempts = row.attempts if row else 0
    calls = row.calls if row else 0
    passed = bool(row and row.passed)
    locked = passed or attempts >= PRACTICE_MAX_ATTEMPTS or calls >= PRACTICE_MAX_CALLS
    best = row.best_score if row is not None else None
    return PracticeState(
        attempts_used=attempts,
        attempts_left=0 if locked else PRACTICE_MAX_ATTEMPTS - attempts,
        passed=passed,
        locked=locked,
        best_score=None if best is None else round(best),
    )


async def pronunciation_report(db: AsyncSession, session_id: int) -> PronunciationReport:
    """The pronunciation part of the report, built from the stored analyses (also gives the hard words)."""
    turns = (
        await db.scalars(
            select(Turn).where(Turn.session_id == session_id, Turn.turn_number != OPENING_TURN).order_by(Turn.turn_number)
        )
    ).all()
    rows = (
        await db.scalars(
            select(TurnAnalysis).where(
                TurnAnalysis.turn_id.in_([t.id for t in turns]),
                TurnAnalysis.dimension == AnalysisDimension.PRONUNCIATION.value,
            )
        )
    ).all()
    by_turn = {r.turn_id: r for r in rows}
    return build_pronunciation_report([(t.turn_number, by_turn.get(t.id)) for t in turns])


async def attach_practice(db: AsyncSession, report: SessionReport) -> None:
    """Add the practice state to each hard word. Done after the report is saved: it changes with every try."""
    words = report.pronunciation.hard_words
    if not words:
        return
    rows = (
        await db.scalars(
            select(WordPractice).where(
                WordPractice.session_id == report.session_id,
                WordPractice.word.in_([normalize_word(w.word) for w in words]),
            )
        )
    ).all()
    by_word = {r.word: r for r in rows}
    for w in words:
        w.practice = practice_state(by_word.get(normalize_word(w.word)))


def measure_seconds(path: Path) -> float | None:
    """Length of an audio file by decoding it (browser webm has no duration in its header). None if unknown."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    try:
        out = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-stats", "-i", str(path), "-f", "null", "-"],
            capture_output=True,
            timeout=15,
            text=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
    if not times:
        return None
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)
