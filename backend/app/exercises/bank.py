"""The exercise bank: ``exercises.txt``, one block per rule of the corpus (see the header of that file).

Loaded and validated once: a typo (unknown rule, a rule without exercises, a gap without ``___``) fails at load
time, never in front of a learner.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.rag.corpus import rules_by_id

BANK_FILE = Path(__file__).parent / "exercises.txt"
SEPARATOR = "==="
Kind = Literal["choice", "fill", "fix", "speak"]
_WRITTEN_KINDS = ("choice", "fill", "fix")
_VARIANT_SPLIT = " / "


class ExerciseError(ValueError):
    """The bank file is malformed."""


@dataclass(frozen=True)
class Exercise:
    id: str
    rule_id: str
    kind: Kind
    # choice: the question · fill: the sentence with ___ · fix: the sentence with the mistake · speak: what to say
    prompt: str
    options: tuple[str, ...] = ()  # choice only; the right one is FIRST here, the API shuffles them
    answers: tuple[str, ...] = ()  # accepted answers; for speak the first one is the sentence to say
    wrong: str = ""  # speak only: the sentence with the mistake, to tell it apart from the right one
    personal: bool = False  # made from the learner's own sentence (app/exercises/personal.py), not from the bank


def _fields(value: str) -> list[str]:
    return [part.strip() for part in value.split("|")]


def _parse_block(text: str, source: str) -> list[Exercise]:
    rule_id = ""
    pending: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ExerciseError(f"{source}: line without a field name: {line!r}")
        key, value = key.strip(), value.strip()
        if key == "rule":
            rule_id = value
        elif key in _WRITTEN_KINDS:
            pending.append((key, value))
        else:
            raise ExerciseError(f"{source}: unknown field {key!r}")
    if rule_id not in rules_by_id():
        raise ExerciseError(f"{source}: unknown rule {rule_id!r}")

    made: list[Exercise] = []
    counters = {kind: 0 for kind in _WRITTEN_KINDS}
    for kind, value in pending:
        counters[kind] += 1
        n = counters[kind]
        parts = _fields(value)
        where = f"{source} ({rule_id} {kind} {n})"
        if kind == "choice":
            if len(parts) != 4 or not all(parts) or len(set(parts[1:])) != 3:
                raise ExerciseError(f"{where}: choice = prompt | right | wrong | wrong (all different)")
            made.append(Exercise(f"{rule_id}:choice:{n}", rule_id, "choice", parts[0], options=tuple(parts[1:]), answers=(parts[1],)))
        elif kind == "fill":
            if len(parts) != 2 or "___" not in parts[0] or not parts[1]:
                raise ExerciseError(f"{where}: fill = sentence with ___ | answer")
            made.append(Exercise(f"{rule_id}:fill:{n}", rule_id, "fill", parts[0], answers=tuple(parts[1].split(_VARIANT_SPLIT))))
        else:  # fix: also gives a speaking exercise (say the corrected sentence)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ExerciseError(f"{where}: fix = wrong sentence | corrected sentence")
            answers = tuple(parts[1].split(_VARIANT_SPLIT))
            if parts[0] in answers:
                raise ExerciseError(f"{where}: the wrong sentence is also an accepted answer")
            made.append(Exercise(f"{rule_id}:fix:{n}", rule_id, "fix", parts[0], answers=answers))
            made.append(Exercise(f"{rule_id}:speak:{n}", rule_id, "speak", answers[0], answers=(answers[0],), wrong=parts[0]))
    for kind in ("choice", "fix"):
        if not counters[kind]:
            raise ExerciseError(f"{source}: rule {rule_id} has no {kind} exercise")
    return made


@lru_cache
def load_exercises() -> tuple[Exercise, ...]:
    text = BANK_FILE.read_text(encoding="utf-8")
    exercises: list[Exercise] = []
    seen_rules: set[str] = set()
    for i, block in enumerate(text.split(SEPARATOR), start=1):
        if not block.strip() or all(l.strip().startswith("#") or not l.strip() for l in block.splitlines()):
            continue
        parsed = _parse_block(block, f"{BANK_FILE.name} block {i}")
        rule_id = parsed[0].rule_id
        if rule_id in seen_rules:
            raise ExerciseError(f"{BANK_FILE.name}: rule {rule_id} appears twice")
        seen_rules.add(rule_id)
        exercises.extend(parsed)
    missing = set(rules_by_id()) - seen_rules
    if missing:
        raise ExerciseError(f"rules without exercises: {sorted(missing)}")
    return tuple(exercises)


@lru_cache
def exercises_by_id() -> dict[str, Exercise]:
    return {e.id: e for e in load_exercises()}
