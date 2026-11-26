"""Grammar eval: evals/grammar/cases.jsonl through the app's own analysis (prompt, router, confidence filter).

Each case is analysed with ``analyze_grammar`` exactly as a turn is in the app (use "analysis" of the router,
grammar prompt ``PROMPT_VERSION``, only errors at or above ``MIN_CONFIDENCE`` are kept). The cases have no
tutor message, so the analysis gets the same "first answer" context a first turn gets.

WHAT COUNTS AS A HIT
An expected error and a flagged error MATCH when they point at the same place: after lower-casing and dropping
punctuation, one fragment contains the other ("goed" matches "I goed"). Each flagged error can match one expected
error at most, and vice versa.

- precision = matched flagged errors / all flagged errors (the 6 correct sentences included)
- recall    = matched expected errors / all expected errors

The headline precision and recall count the LOCATION only; the correction is scored apart as ``fix_accuracy``
(of the matched errors, how many have the expected fix) and in the STRICT variant (a hit needs the same place AND
the same fix). Why location first: the question "did it notice the mistake, and did it invent any?" is what a
learner needs to trust the report, and a correction can be right and still differ from the one written in the
case ("doesn't" / "does not", "went" / "I went", "a" / "the" when both fit). Requiring the exact fix would count
those as misses AND as false alarms at once, which would understate both metrics. The strict figures are kept so
that a model that finds the mistakes but fixes them wrongly is still visible.

VARIANCE. The model does not answer the same twice, so the set runs ``--repeats`` times (3 by default) and the
report gives, per metric, the median and the range (min-max) of the runs, never a single number.
"""

import re
import statistics
from typing import Any

from app.analysis.grammar import MIN_CONFIDENCE, PROMPT_VERSION, analyze_grammar
from app.prompts import load_prompt
from app.providers import chains
from scripts.evals.common import (
    EVALS_DIR,
    Plan,
    Tracker,
    base_result,
    classify_llm_failure,
    llm_call_cost,
    load_jsonl,
    new_run_id,
    now_iso,
    served_by,
    with_retries,
)

CASES = EVALS_DIR / "grammar" / "cases.jsonl"
DEFAULT_REPEATS = 3
# Completion tokens of one analysis on the paid model (JSON with an explanation per error); generous on purpose.
COMPLETION_TOKENS_ESTIMATE = 500
FIRST_TURN_CONTEXT = ""  # analyze_grammar turns "" into "(none: this is the first answer)"
METRICS = ("precision", "recall", "strict_precision", "strict_recall", "fix_accuracy", "false_positive_rate")


def load_cases() -> list[dict[str, Any]]:
    return load_jsonl(CASES)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def same_place(expected: str, flagged: str) -> bool:
    a, b = _norm(expected), _norm(flagged)
    return bool(a) and bool(b) and (a in b or b in a)


def same_fix(expected: str, flagged: str) -> bool:
    return same_place(expected, flagged)  # the same containment rule, applied to the corrections


def score_case(expected: list[dict[str, Any]], flagged: list[dict[str, Any]]) -> dict[str, int]:
    """One-to-one matching by place, in order; counts for precision, recall and the strict variant."""
    used: set[int] = set()
    matched = matched_fix = 0
    for exp in expected:
        for i, pred in enumerate(flagged):
            if i not in used and same_place(exp["original"], pred["original"]):
                used.add(i)
                matched += 1
                matched_fix += same_fix(exp["correction"], pred["correction"])
                break
    return {"expected": len(expected), "flagged": len(flagged), "matched": matched, "matched_fix": matched_fix}


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics of ONE repetition, over the cases that got an answer (failed cases are counted, not scored)."""
    scored = [r for r in rows if not r.get("failure")]
    expected = sum(r["score"]["expected"] for r in scored)
    flagged = sum(r["score"]["flagged"] for r in scored)
    matched = sum(r["score"]["matched"] for r in scored)
    matched_fix = sum(r["score"]["matched_fix"] for r in scored)
    correct = [r for r in scored if r["score"]["expected"] == 0]
    flagged_correct = [r for r in correct if r["score"]["flagged"] > 0]
    return {
        "cases_scored": len(scored),
        "cases_failed": len(rows) - len(scored),
        "precision": _ratio(matched, flagged),
        "recall": _ratio(matched, expected),
        "strict_precision": _ratio(matched_fix, flagged),
        "strict_recall": _ratio(matched_fix, expected),
        "fix_accuracy": _ratio(matched_fix, matched),
        # The correct sentences, apart: how many got at least one invented error, and how many errors in total.
        "correct_sentences": len(correct),
        "correct_sentences_flagged": len(flagged_correct),
        "false_positive_rate": _ratio(len(flagged_correct), len(correct)),
        "errors_invented_on_correct": sum(r["score"]["flagged"] for r in correct),
        "flagged_errors_unmatched": flagged - matched,
    }


def spread(per_repeat: list[dict[str, Any]]) -> dict[str, Any]:
    """Median and range of each metric across the repetitions (only those that produced it)."""
    out: dict[str, Any] = {}
    for name in METRICS:
        values = [m[name] for m in per_repeat if m.get(name) is not None]
        out[name] = (
            {"median": round(statistics.median(values), 4), "min": min(values), "max": max(values), "values": values}
            if values
            else None
        )
    return out


def plan(cfg: Any, repeats: int, limit: int | None = None) -> Plan:
    cases = load_cases()[:limit] if limit else load_cases()
    per_round = sum(
        llm_call_cost(cfg, len(load_prompt("grammar", PROMPT_VERSION, text=c["text"], context="(none: this is the first answer)")), COMPLETION_TOKENS_ESTIMATE)
        for c in cases
    )  # fmt: skip
    return Plan(
        "grammar",
        calls=len(cases) * repeats,
        estimated_cost_usd=per_round * repeats,
        notes=[
            f"{len(cases)} cases x {repeats} repetitions, grammar prompt v{PROMPT_VERSION}, router use 'analysis'",
            f"assumes every call is answered by OpenAI {cfg.openai_llm_model} (the analysis order is '{cfg.llm_analysis_order}')",
        ],
    )


def run(tracker: Tracker, the_plan: Plan, repeats: int, limit: int | None = None, log=print) -> dict[str, Any]:  # noqa: ANN001
    cases = load_cases()[:limit] if limit else load_cases()
    llm = chains.build_llm("analysis", tracker.cfg, tracker.state)
    run_id, started = new_run_id(), now_iso()
    rows: list[dict[str, Any]] = []
    per_repeat: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        round_rows = []
        for case in cases:
            attempt = with_retries(lambda c=case: analyze_grammar(llm, c["text"], FIRST_TURN_CONTEXT), classify_llm_failure)
            calls = tracker.collect()
            row: dict[str, Any] = {"repeat": repeat, "id": case["id"], "attempts": attempt.attempts, "served_by": served_by(calls)}
            if attempt.ok:
                flagged = attempt.value["errors"]
                row.update(flagged=flagged, discarded_low_confidence=attempt.value["discarded_low_confidence"], score=score_case(case["expected_errors"], flagged))
            else:
                row.update(failure=attempt.failure, error=attempt.error)
            round_rows.append(row)
            log(f"  r{repeat} {case['id']} " + (f"{row['score']['matched']}/{row['score']['expected']} flagged={row['score']['flagged']}" if attempt.ok else f"FAILED ({attempt.failure})"))
        per_repeat.append(metrics(round_rows))
        rows.extend(round_rows)

    return base_result(
        "grammar", run_id, started, the_plan, rows,
        prompt_version=PROMPT_VERSION,
        min_confidence=MIN_CONFIDENCE,
        repeats=repeats,
        unique_cases=len(cases),
        per_repeat=per_repeat,
        metrics=spread(per_repeat),
        **tracker.summary(),
    )  # fmt: skip


def describe(result: dict[str, Any]) -> list[str]:
    m = result["metrics"]
    lines = [f"grammar prompt v{result['prompt_version']}, {result['repeats']} repetitions of {result['unique_cases']} cases"]
    if all(v is None for v in m.values()):
        return [*lines, "NOT MEASURED: no case got an answer."]
    for name in METRICS:
        v = m[name]
        lines.append(f"  {name:<20} " + ("n/a" if v is None else f"median {v['median']:.0%}  range {v['min']:.0%}-{v['max']:.0%}"))
    last = result["per_repeat"]
    lines.append(
        "  correct sentences flagged per repetition: "
        + ", ".join(f"{p['correct_sentences_flagged']}/{p['correct_sentences']}" for p in last)
    )
    return lines
