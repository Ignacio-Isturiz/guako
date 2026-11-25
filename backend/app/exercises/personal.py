"""Exercises made from the learner's OWN mistakes: the sentence they said, with the correction already known.

Every mistake the analysis finds is kept (``error_events``) with the fragment that was wrong and its fix. Put back
into the sentence of the transcript where it was said, that is a correction exercise ("fix") and a speaking one
("speak") that never run out and are about exactly what that person got wrong. They are private: only their owner
ever gets them.

The correction is the one the analysis already showed in the report, so it can be as wrong as that one; the
fragment must be found inside a sentence of the transcript or no exercise is made.
"""

import re

from app.exercises.bank import Exercise

PREFIX = "mine:"
MIN_WORDS = 3  # shorter than this is not a sentence worth rewriting or saying
MAX_WORDS = 25


def exercise_id(event_id: int, kind: str) -> str:
    return f"{PREFIX}{event_id}:{kind}"


def parse_id(exercise_id_: str) -> tuple[int, str] | None:
    """``mine:12:fix`` -> (12, "fix"); None when it is not a personal exercise id."""
    match = re.fullmatch(rf"{PREFIX}(\d+):(fix|speak)", exercise_id_)
    return (int(match.group(1)), match.group(2)) if match else None


def _sentences(transcript: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if s.strip()]


def fix_sentence(transcript: str, original: str, correction: str) -> tuple[str, str] | None:
    """(the sentence as said, the same sentence corrected) or None when it cannot be built reliably."""
    original, correction = original.strip(), correction.strip()
    if not original or not correction or original.lower() == correction.lower():
        return None
    pattern = re.compile(re.escape(original), re.IGNORECASE)
    for sentence in _sentences(transcript):
        if not pattern.search(sentence):
            continue
        corrected = pattern.sub(lambda _: correction, sentence, count=1)
        if MIN_WORDS <= len(sentence.split()) <= MAX_WORDS and corrected != sentence:
            return sentence, corrected
    return None


def exercises_for(event_id: int, rule_id: str | None, transcript: str, original: str, correction: str) -> list[Exercise]:
    """The "fix" and "speak" exercises of one mistake (empty when its sentence cannot be built)."""
    pair = fix_sentence(transcript, original, correction)
    if pair is None:
        return []
    said, corrected = pair
    rule = rule_id or ""
    return [
        Exercise(exercise_id(event_id, "fix"), rule, "fix", said, answers=(corrected,), personal=True),
        Exercise(exercise_id(event_id, "speak"), rule, "speak", corrected, answers=(corrected,), wrong=said, personal=True),
    ]
