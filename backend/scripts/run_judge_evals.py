"""Does the judge agree with a person? Runs the 15 cases of evals/judges/cases.jsonl through the real judge.

Run from backend/:
    python -m scripts.run_judge_evals            # lists the cases and the estimated cost; sends NOTHING
    python -m scripts.run_judge_evals --yes      # calls the LLM (through the router, use "analysis")

The calls go through the same analysis chain the app uses, so they can spend the paid provider's budget (a few
cents at most: 15 short calls). Writes results/evals/judges-<run_id>.jsonl and prints, per dimension, how often the
judge gives exactly the expected score, within one point, and its average error and bias.

NO NUMBER IS INVENTED. A case whose call fails (no quota, provider out) is reported as such and left out of
the statistics; if no case could be judged, the report says "no quota today" and prints no figure at all. A case
the judge was not confident about is hidden in the app, so it is counted apart (``hidden``) and ALSO shown in the
agreement, labelled, so the cost of the honesty rule is visible.

The expected scores are only as good as the person who wrote them: while a case says ``"reviewed": false`` the
report is labelled as measured against UNREVIEWED expectations.
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.analysis.judge import MIN_JUDGE_CONFIDENCE, PROMPT_VERSION, judge_turn
from app.config import settings
from app.llm.errors import LLMError
from app.providers import chains
from app.providers.errors import LLMExhausted

BACKEND_DIR = Path(__file__).resolve().parents[1]
CASES = BACKEND_DIR / "evals" / "judges" / "cases.jsonl"
RESULTS_DIR = BACKEND_DIR / "results" / "evals"
DIMENSIONS = ("communication", "listening")


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def agreement(pairs: list[tuple[int, int, float | None]]) -> dict[str, Any] | None:
    """``pairs`` = (expected, given, judge confidence). None if there is nothing to compare."""
    if not pairs:
        return None
    n = len(pairs)
    diffs = [given - expected for expected, given, _ in pairs]
    right = [c for (e, g, c), d in zip(pairs, diffs, strict=True) if d == 0 and c is not None]
    wrong = [c for (e, g, c), d in zip(pairs, diffs, strict=True) if d != 0 and c is not None]
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


def judge_case(llm: Any, case: dict[str, Any]) -> dict[str, Any]:
    """The result of one case: the judge's scores, or why there is none (``no_quota`` / ``failed``)."""
    ctx = {
        "transcript": case["learner"],
        "tutor_prev": case["tutor"],
        "level": case["level"],
        "topic": case["topic"],
        "feedback_language": "es",
    }
    try:
        result = judge_turn(llm, ctx, want_listening=True)
    except LLMExhausted as exc:
        return {"status": "no_quota", "error": exc.code}
    except LLMError as exc:
        rate_limited = exc.code == "ai_busy"
        return {"status": "no_quota" if rate_limited else "failed", "error": exc.code}
    return {"status": "judged", **result}


def summarize(cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [(c, r) for c, r in zip(cases, results, strict=True) if r["status"] == "judged"]
    summary: dict[str, Any] = {
        "cases": len(cases),
        "judged": len(judged),
        "no_quota": sum(r["status"] == "no_quota" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "reviewed": all(c.get("reviewed") for c in cases),
        "min_judge_confidence": MIN_JUDGE_CONFIDENCE,
        "prompt_version": PROMPT_VERSION,  # to compare runs: the figures only mean something for one prompt
    }
    for dimension in DIMENSIONS:
        pairs: list[tuple[int, int, float | None]] = []
        hidden = repeat_ok = repeat_total = 0
        for case, result in judged:
            expected = case["expected"][dimension]
            given = result[dimension]
            if dimension == "listening":
                asked = bool(given and given.get("asked_to_repeat"))
                if expected is None or asked:  # the "asked to repeat" cases: agree if both say so
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="really call the LLM (without it nothing is sent)")
    args = parser.parse_args()
    cases = load_cases()
    unreviewed = sum(not c.get("reviewed") for c in cases)
    print(f"{len(cases)} cases ({unreviewed} with expectations not yet reviewed by a person).")
    price_in, price_out = settings.price_openai_llm_input_per_m, settings.price_openai_llm_output_per_m
    cost = len(cases) * (700 * price_in + 130 * price_out) / 1_000_000
    print(f"Estimated cost if the paid provider answers: about ${cost:.4f} (default prices, NOT verified).")
    if not args.yes:
        print("Nothing was sent. Run again with --yes to call the LLM.")
        return

    llm = chains.analysis_llm(settings)
    results = [judge_case(llm, case) for case in cases]
    summary = summarize(cases, results)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"judges-{run_id}.jsonl"
    lines = [{"run_id": run_id, "summary": summary}] + [{"id": c["id"], "expected": c["expected"], **r} for c, r in zip(cases, results, strict=True)]
    out.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")

    print(f"\njudge prompt v{PROMPT_VERSION} | judged {summary['judged']} of {summary['cases']} | no quota: {summary['no_quota']} | failed: {summary['failed']}")
    if summary["judged"] == 0:
        print("No quota today (or every call failed): no figure is reported. Run it again another day.")
        print(f"saved {out}")
        sys.exit(1)
    if summary["judged"] < summary["cases"]:
        print("PARTIAL: the figures below cover only the cases that could be judged.")
    if not summary["reviewed"]:
        print("NOTE: measured against expectations NOT yet reviewed by a person.")
    for dimension in DIMENSIONS:
        print(f"{dimension}: {summary[dimension]} (shown to the learner would hide {summary[dimension + '_hidden']})")
    print("asked-to-repeat agreement:", summary["asked_to_repeat_agreed"])
    print(f"saved {out}")


if __name__ == "__main__":
    main()
