"""Human review: show one real turn at a time with what the system said, and record whether a person agrees.

The MVP criteria ask for 100 turns reviewed by hand, per dimension. Turns and their finished analyses are read
from the app's database (``DATABASE_URL``); the answers are appended to results/reviews/human_review.jsonl as they
are given, so quitting loses nothing and the next session resumes where it stopped (a (turn, dimension) pair
already answered is not asked again).

For every dimension of the turn the question is "do you agree with what the system said?":
- y = yes, n = no, s = skip this one (not saved), q = quit (what was answered is already saved).
- On "n" for a scored dimension (communication, listening) it asks for YOUR score (1-5, Enter = none), so the
  report can also give the distance between the system and the person, not only "agree or not".
- Optionally a short note on every "n".

``summarize`` gives, per dimension, how many were reviewed, the share where the person agreed, and for scored
dimensions the mean distance when the person gave a score.
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.reports import HARD_WORD_THRESHOLD
from scripts.evals.common import REVIEWS_DIR, now_iso

REVIEW_FILE = REVIEWS_DIR / "human_review.jsonl"
TARGET_TURNS = 100
DIMENSIONS = ("grammar", "fluency", "pronunciation", "communication", "listening")
SCORED = {"communication", "listening"}


# --- loading the turns -----------------------------------------------------------------------------------------


async def _load_from_db() -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db import Turn, TurnAnalysis, async_session_maker

    async with async_session_maker() as db:
        turns = (await db.execute(select(Turn).order_by(Turn.session_id, Turn.turn_number))).scalars().all()
        analyses = (await db.execute(select(TurnAnalysis).where(TurnAnalysis.status == "done"))).scalars().all()
    by_turn: dict[int, dict[str, Any]] = {}
    for a in analyses:
        by_turn.setdefault(a.turn_id, {})[a.dimension] = a.result
    out: list[dict[str, Any]] = []
    previous_reply: dict[int, str] = {}
    for t in turns:
        tutor = previous_reply.get(t.session_id, "")
        previous_reply[t.session_id] = t.reply_text
        if t.id in by_turn and t.user_transcript.strip():
            out.append({"turn_id": t.id, "session_id": t.session_id, "turn_number": t.turn_number, "tutor": tutor,
                        "learner": t.user_transcript, "analyses": by_turn[t.id]})  # fmt: skip
    return out


def load_turns() -> list[dict[str, Any]]:
    return asyncio.run(_load_from_db())


# --- what the system said, as text -----------------------------------------------------------------------------


def system_view(dimension: str, result: dict[str, Any] | None) -> tuple[str, int | None]:
    """(what to show, the system's score if the dimension has one)."""
    if not result:
        return "(no result)", None
    if dimension == "grammar":
        errors = result.get("errors") or []
        if not errors:
            return "no errors flagged", None
        return "\n".join(f"    - '{e['original']}' -> '{e['correction']}' ({e['error_type']}, conf {e['confidence']})" for e in errors), None
    if dimension == "fluency":
        m = result.get("metrics") or {}
        return ", ".join(f"{k}={v.get('value')} [{v.get('status')}]" for k, v in m.items()) or "(no metrics)", None
    if dimension == "pronunciation":
        hard = [f"{w['word']} {w['accuracy']:.0f}" for w in result.get("words") or [] if w.get("accuracy") is not None and w["accuracy"] < HARD_WORD_THRESHOLD]
        return f"pron_score={result.get('pron_score')}; words below {HARD_WORD_THRESHOLD:.0f}: {', '.join(hard) or 'none'}", None
    if result.get("asked_to_repeat"):
        return "learner asked to repeat (no score)", None
    hidden = " [HIDDEN from the learner: low confidence]" if result.get("hidden") else ""
    return f"score {result.get('score')}/5{hidden}, confidence {result.get('confidence')}\n    {result.get('rationale')}", result.get("score")


# --- the annotations --------------------------------------------------------------------------------------------


def load_reviews(path: Path = REVIEW_FILE) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_review(entry: dict[str, Any], path: Path = REVIEW_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def latest_per_pair(reviews: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    """The last answer for each (turn, dimension): a later answer replaces an earlier one."""
    return {(r["turn_id"], r["dimension"]): r for r in reviews}


def _ask(prompt: str, valid: set[str], ask: Callable[[str], str]) -> str:
    while True:
        answer = ask(prompt).strip().lower()
        if answer in valid:
            return answer


def review(turns: list[dict[str, Any]], *, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
           path: Path = REVIEW_FILE, dimensions: tuple[str, ...] = DIMENSIONS) -> int:  # fmt: skip
    """Interactive loop. Returns how many answers were saved in this session."""
    done = latest_per_pair(load_reviews(path))
    saved = 0
    pending = [t for t in turns if any(d in t["analyses"] and (t["turn_id"], d) not in done for d in dimensions)]
    say(f"{len(pending)} turns with something left to review ({len({k[0] for k in done})} turns already reviewed, target {TARGET_TURNS}).")
    for index, turn in enumerate(pending, start=1):
        say(f"\n=== turn {turn['turn_id']} (session {turn['session_id']}, #{turn['turn_number']}) - {index}/{len(pending)} ===")
        say(f"  Guako said:   {turn['tutor'] or '(nothing before: first turn)'}")
        say(f"  Learner said: {turn['learner']}")
        for dimension in dimensions:
            if dimension not in turn["analyses"] or (turn["turn_id"], dimension) in done:
                continue
            shown, system_score = system_view(dimension, turn["analyses"][dimension])
            say(f"\n  [{dimension}]\n    {shown}")
            answer = _ask("  Agree? [y]es / [n]o / [s]kip / [q]uit: ", {"y", "n", "s", "q"}, ask)
            if answer == "q":
                say(f"Saved {saved} answers in this session.")
                return saved
            if answer == "s":
                continue
            human_score = None
            note = ""
            if answer == "n":
                if dimension in SCORED and system_score is not None:
                    raw = _ask("  Your score 1-5 (Enter = none): ", {"", "1", "2", "3", "4", "5"}, ask)
                    human_score = int(raw) if raw else None
                note = ask("  Note (optional): ").strip()
            save_review(
                {"turn_id": turn["turn_id"], "dimension": dimension, "agree": answer == "y", "system_score": system_score,
                 "human_score": system_score if answer == "y" else human_score, "note": note, "reviewed_at": now_iso()},
                path,
            )  # fmt: skip
            saved += 1
    say(f"\nNothing left to review. Saved {saved} answers in this session.")
    return saved


def summarize(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Agreement between the system and the person, per dimension."""
    latest = list(latest_per_pair(reviews).values())
    out: dict[str, Any] = {"turns_reviewed": len({r["turn_id"] for r in latest}), "target_turns": TARGET_TURNS, "dimensions": {}}
    for dimension in DIMENSIONS:
        rows = [r for r in latest if r["dimension"] == dimension]
        if not rows:
            out["dimensions"][dimension] = None
            continue
        entry: dict[str, Any] = {"reviewed": len(rows), "agreement": round(sum(r["agree"] for r in rows) / len(rows), 3)}
        if dimension in SCORED:
            scored = [r for r in rows if r.get("system_score") is not None and r.get("human_score") is not None]
            if scored:
                diffs = [r["system_score"] - r["human_score"] for r in scored]
                entry.update(
                    with_scores=len(scored),
                    exact=round(sum(d == 0 for d in diffs) / len(diffs), 3),
                    within_one=round(sum(abs(d) <= 1 for d in diffs) / len(diffs), 3),
                    bias=round(sum(diffs) / len(diffs), 3),  # positive: the system is more generous than the person
                )
        out["dimensions"][dimension] = entry
    return out


def describe(summary: dict[str, Any]) -> list[str]:
    lines = [f"turns reviewed by a person: {summary['turns_reviewed']} of the {summary['target_turns']} the MVP asks for"]
    for dimension, entry in summary["dimensions"].items():
        if entry is None:
            lines.append(f"  {dimension}: NOT MEASURED (no turn reviewed)")
            continue
        extra = f", exact score {entry['exact']:.0%}, within one {entry['within_one']:.0%}, bias {entry['bias']:+}" if "exact" in entry else ""
        lines.append(f"  {dimension}: {entry['reviewed']} reviewed, agreement {entry['agreement']:.0%}{extra}")
    return lines
