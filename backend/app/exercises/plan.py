"""Which exercises to give.

The rules come ranked (the ones the learner got wrong most often first). Each slot of the session takes the next
rule and the next kind of a fixed rotation, so the session mixes choice, gap, correction and speaking instead of
four of the same. When a rule has no exercise of the wanted kind (some have no gap), it gives another kind; when
the learner has fewer rules than slots, the rules come back with exercises they have not seen in this plan.

Freshness: inside a rule, exercises the learner has never answered come first and, once they have answered them
all, the one answered LONGEST AGO comes back first. So a round never runs out and it varies as long as there is
anything they have not seen. Their own sentences (``personal``) go before the bank's when both are equally fresh.
"""

from collections.abc import Mapping, Sequence

from app.exercises.bank import Exercise, Kind, load_exercises

# Easy to hard: recognise it, write one word, rewrite the sentence, say it out loud.
KIND_ROTATION: tuple[Kind, ...] = ("choice", "fill", "fix", "speak")
MAX_SIZE = 20
NO_RULE = ""  # the key of the learner's own mistakes that no rule explains: they go after the ranked rules
_NEVER = -1.0


def build_plan(
    ranked_rules: list[str],
    size: int,
    *,
    personal: Sequence[Exercise] = (),
    extra: Sequence[Exercise] = (),
    last_seen: Mapping[str, float] | None = None,
) -> list[Exercise]:
    """Up to ``size`` different exercises.

    ``ranked_rules``: rule ids, most frequent first. ``personal``: exercises made from the learner's own sentences.
    ``extra``: exercises the LLM wrote and the analyser accepted (they come after the bank's when equally fresh).
    ``last_seen``: exercise id -> when it was last answered (a timestamp); missing = never.
    """
    size = max(1, min(size, MAX_SIZE))
    seen = last_seen or {}
    by_rule: dict[str, list[Exercise]] = {}
    for exercise in [*personal, *load_exercises(), *extra]:  # in this order when equally fresh: the sort is stable
        by_rule.setdefault(exercise.rule_id, []).append(exercise)
    for options in by_rule.values():
        options.sort(key=lambda e: seen.get(e.id, _NEVER))
    ranked = [r for r in dict.fromkeys(ranked_rules) if r in by_rule]
    if NO_RULE in by_rule and NO_RULE not in ranked:
        ranked.append(NO_RULE)

    plan: list[Exercise] = []
    used: set[str] = set()
    while ranked and len(plan) < size:
        before = len(plan)
        for rule_id in ranked:
            if len(plan) >= size:
                break
            wanted = KIND_ROTATION[len(plan) % len(KIND_ROTATION)]
            options = [e for e in by_rule[rule_id] if e.id not in used]
            fresh = [e for e in options if e.id not in seen]
            tier = fresh or options  # never-seen ones first; when all were seen, the oldest first (options is sorted)
            pick = next((e for e in tier if e.kind == wanted), tier[0] if tier else None)
            if pick is not None:
                plan.append(pick)
                used.add(pick.id)
        if len(plan) == before:  # every exercise of every ranked rule is already in the plan
            break
    return plan
