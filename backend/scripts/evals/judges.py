"""Judge eval: does the judge ("darse a entender" and "listening") agree with a person? evals/judges/cases.jsonl.

Each case goes through ``judge_turn`` with the router's "analysis" use, as in the app. Per dimension it reports how
often the judge gives exactly the expected score, within one point, its mean error and its bias (positive = more
generous than the person). A score the judge was not confident about is hidden in the app: it is still compared,
and counted apart (``hidden``), so the cost of the honesty rule is visible.

The expected scores are only as good as the person who wrote them: while a case says ``"reviewed": false`` the
report says the agreement was measured against UNREVIEWED expectations.
"""

import statistics
from typing import Any

from app.analysis.judge import MIN_JUDGE_CONFIDENCE, PROMPT_VERSION, build_prompt, judge_turn
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

CASES = EVALS_DIR / "judges" / "cases.jsonl"
DIMENSIONS = ("communication", "listening")
COMPLETION_TOKENS_ESTIMATE = 300


def load_cases() -> list[dict[str, Any]]:
    return load_jsonl(CASES)


def context(case: dict[str, Any]) -> dict[str, Any]:
    return {"transcript": case["learner"], "tutor_prev": case["tutor"], "level": case["level"], "topic": case["topic"], "feedback_language": "es"}


def agreement(pairs: list[tuple[int, int, float | None]]) -> dict[str, Any] | None:
    """``pairs`` = (expected, given, judge confidence). None when there is nothing to compare."""
    if not pairs:
        return None
    n = len(pairs)
    diffs = [given - expected for expected, given, _ in pairs]
    right = [c for (_, _, c), d in zip(pairs, diffs, strict=True) if d == 0 and c is not None]
    wrong = [c for (_, _, c), d in zip(pairs, diffs, strict=True) if d != 0 and c is not None]
    return {
        "cases": n,
        "exact": round(sum(d == 0 for d in diffs) / n, 3),
        "within_one": round(sum(abs(d) <= 1 for d in diffs) / n, 3),
        "mean_abs_error": round(sum(abs(d) for d in diffs) / n, 3),
        "bias": round(sum(diffs) / n, 3),  # positive: the judge is more generous than the person
        # Is the judge's confidence worth anything? It should be lower when it is wrong.
        "confidence_when_exact": round(sum(right) / len(right), 3) if right else None,
        "confidence_when_off": round(sum(wrong) / len(wrong), 3) if wrong else None,
    }


def summarize(cases: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Agreement per dimension over the cases that were judged; ``rows`` line up with ``cases``."""
    judged = [(c, r) for c, r in zip(cases, rows, strict=True) if not r.get("failure")]
    summary: dict[str, Any] = {"judged": len(judged), "reviewed": all(c.get("reviewed") for c in cases)}
    for dimension in DIMENSIONS:
        pairs: list[tuple[int, int, float | None]] = []
        hidden = repeat_ok = repeat_total = 0
        for case, row in judged:
            expected = case["expected"][dimension]
            given = row["judgement"][dimension]
            if dimension == "listening":
                asked = bool(given and given.get("asked_to_repeat"))
                if expected is None or asked:  # "asked to repeat": they agree only if both say so
                    repeat_total += 1
                    repeat_ok += expected is None and asked
                    continue
            if given is None or given.get("score") is None or expected is None:
                continue
            hidden += bool(given.get("hidden"))
            pairs.append((expected, given["score"], given.get("confidence")))
        summary[dimension] = agreement(pairs)
        summary[f"{dimension}_hidden"] = hidden
        if dimension == "listening":
            summary["asked_to_repeat_agreed"] = f"{repeat_ok}/{repeat_total}"
    return summary


def plan(cfg: Any, repeats: int = 1, limit: int | None = None) -> Plan:
    cases = load_cases()[:limit] if limit else load_cases()
    per_round = sum(llm_call_cost(cfg, len(build_prompt(context(c), True, None)), COMPLETION_TOKENS_ESTIMATE) for c in cases)
    unreviewed = sum(not c.get("reviewed") for c in cases)
    return Plan(
        "judges",
        calls=len(cases) * repeats,
        estimated_cost_usd=per_round * repeats,
        notes=[
            f"{len(cases)} cases x {repeats} repetitions, judge prompt v{PROMPT_VERSION}, router use 'analysis'",
            f"{unreviewed} of {len(cases)} cases have expectations NOT yet reviewed by a person",
        ],
    )


def run(tracker: Tracker, the_plan: Plan, repeats: int = 1, limit: int | None = None, log=print) -> dict[str, Any]:  # noqa: ANN001
    cases = load_cases()[:limit] if limit else load_cases()
    llm = chains.build_llm("analysis", tracker.cfg, tracker.state)
    run_id, started = new_run_id(), now_iso()
    rows: list[dict[str, Any]] = []
    per_repeat: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        round_rows = []
        for case in cases:
            attempt = with_retries(lambda c=case: judge_turn(llm, context(c), want_listening=True), classify_llm_failure)
            row: dict[str, Any] = {"repeat": repeat, "id": case["id"], "expected": case["expected"], "attempts": attempt.attempts, "served_by": served_by(tracker.collect())}
            if attempt.ok:
                row["judgement"] = attempt.value
            else:
                row.update(failure=attempt.failure, error=attempt.error)
            round_rows.append(row)
            log(f"  r{repeat} {case['id']} " + ("judged" if attempt.ok else f"FAILED ({attempt.failure})"))
        per_repeat.append(summarize(cases, round_rows))
        rows.extend(round_rows)

    return base_result(
        "judges", run_id, started, the_plan, rows,
        prompt_version=PROMPT_VERSION,
        min_judge_confidence=MIN_JUDGE_CONFIDENCE,
        repeats=repeats,
        unique_cases=len(cases),
        expectations_reviewed=all(c.get("reviewed") for c in cases),
        per_repeat=per_repeat,
        metrics=_median_of(per_repeat),
        **tracker.summary(),
    )  # fmt: skip


def _median_of(per_repeat: list[dict[str, Any]]) -> dict[str, Any]:
    """Per dimension, the median (and range) of exact agreement, within-one and bias across repetitions."""
    out: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        runs = [p[dimension] for p in per_repeat if p.get(dimension)]
        if not runs:
            out[dimension] = None
            continue
        out[dimension] = {
            key: {"median": round(statistics.median(r[key] for r in runs), 3), "min": min(r[key] for r in runs), "max": max(r[key] for r in runs)}
            for key in ("exact", "within_one", "mean_abs_error", "bias")
        }
        out[dimension]["cases"] = runs[-1]["cases"]
    return out


def describe(result: dict[str, Any]) -> list[str]:
    lines = [f"judge prompt v{result['prompt_version']}, {result['repeats']} repetition(s) of {result['unique_cases']} cases"]
    if not result["expectations_reviewed"]:
        lines.append("  NOTE: measured against expectations NOT yet reviewed by a person.")
    for dimension in DIMENSIONS:
        m = result["metrics"][dimension]
        if m is None:
            lines.append(f"  {dimension}: NOT MEASURED (no case was judged)")
            continue
        fmt = lambda k: f"{m[k]['median']}" + (f" ({m[k]['min']}..{m[k]['max']})" if m[k]["min"] != m[k]["max"] else "")  # noqa: E731
        lines.append(f"  {dimension} ({m['cases']} cases): exact {fmt('exact')}, within one {fmt('within_one')}, mean error {fmt('mean_abs_error')}, bias {fmt('bias')}")
    last = result["per_repeat"][-1] if result["per_repeat"] else {}
    if last:
        lines.append(f"  asked-to-repeat agreement (last repetition): {last.get('asked_to_repeat_agreed')}; hidden scores: communication {last.get('communication_hidden')}, listening {last.get('listening_hidden')}")
    return lines
