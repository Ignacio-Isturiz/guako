"""Personalised practice (RAG 3): varied exercises built from the rules the learner got wrong.

- ``bank``: the exercises, plain text (``exercises.txt``), one block per rule of the grammar corpus.
- ``plan``: picks which exercises to give: the learner's most frequent rules (from ``error_events``) first,
  and the four kinds (choice, fill, fix, speak) mixed so the session is not repetitive.
- ``check``: decides if an answer is right (text) or if what was said is the sentence asked for (speech).

HONESTY RULE (same as the memory): doing an exercise right is NOT reported as "you improved" and nothing is
stored from the answers; it is practice, not an evaluation.
"""

from app.exercises.bank import Exercise, ExerciseError, exercises_by_id, load_exercises
from app.exercises.check import check_text, speech_matches
from app.exercises.plan import build_plan

__all__ = [
    "Exercise",
    "ExerciseError",
    "build_plan",
    "check_text",
    "exercises_by_id",
    "load_exercises",
    "speech_matches",
]
