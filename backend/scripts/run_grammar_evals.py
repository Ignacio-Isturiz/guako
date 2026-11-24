"""Run the grammar eval cases against the configured LLM (REAL calls, uses free quota).

Run from backend/:  python -m scripts.run_grammar_evals [--limit N] [--pause-s S]
Writes results/evals/<run_id>.jsonl (one line per case) and prints a summary.
"""

import argparse
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.llm.errors import LLMProviderError, LLMRateLimitError
from app.llm.factory import get_llm_provider
from app.analysis.grammar import MIN_CONFIDENCE, TurnGrammarAnalysis, TurnGrammarError
from app.prompts import load_prompt

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CASES = BACKEND_DIR / "evals" / "grammar" / "cases.jsonl"
DEFAULT_RESULTS_DIR = BACKEND_DIR / "results" / "evals"


def normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def fragments_match(expected: str, predicted: str) -> bool:
    """Same error location: one fragment contains the other (after normalizing)."""
    a, b = normalize(expected), normalize(predicted)
    return bool(a) and bool(b) and (a in b or b in a)


def score_case(expected: list[dict], predicted: list[TurnGrammarError]) -> dict:
    """Detected = expected error whose location was flagged; correct = flagged AND same fix."""
    detected = 0
    correct_fix = 0
    matched_predictions: set[int] = set()
    for exp in expected:
        for i, pred in enumerate(predicted):
            if fragments_match(exp["original"], pred.original):
                detected += 1
                matched_predictions.add(i)
                if normalize(exp["correction"]) in normalize(pred.correction) or normalize(
                    pred.correction
                ) in normalize(exp["correction"]):
                    correct_fix += 1
                break
    return {
        "expected": len(expected),
        "detected": detected,
        "correct_fix": correct_fix,
        "extra": len(predicted) - len(matched_predictions),
    }


def summarize(rows: list[dict]) -> dict:
    with_errors = [r for r in rows if r["score"]["expected"] > 0 and not r.get("error")]
    clean = [r for r in rows if r["score"]["expected"] == 0 and not r.get("error")]
    expected = sum(r["score"]["expected"] for r in with_errors)
    return {
        "cases": len(rows),
        "failed_calls": sum(1 for r in rows if r.get("error")),
        "failed_by_quota": sum(1 for r in rows if r.get("error_kind") == "quota"),
        "min_confidence": MIN_CONFIDENCE,
        "recall": sum(r["score"]["detected"] for r in with_errors) / expected if expected else None,
        "fix_accuracy": sum(r["score"]["correct_fix"] for r in with_errors) / expected if expected else None,
        "extra_errors_in_error_cases": sum(r["score"]["extra"] for r in with_errors),
        "false_positive_rate": (sum(1 for r in clean if r["score"]["extra"] > 0) / len(clean)) if clean else None,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


TRANSIENT_WAITS_S = (5, 15, 30)


def generate_with_retry(provider, prompt: str) -> TurnGrammarAnalysis:
    """Retry transient provider failures (503 overload, rate limit) with growing waits."""
    for wait in TRANSIENT_WAITS_S:
        try:
            return provider.generate(prompt, TurnGrammarAnalysis)
        except (LLMProviderError, LLMRateLimitError):
            time.sleep(wait)
    return provider.generate(prompt, TurnGrammarAnalysis)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    parser.add_argument("--pause-s", type=float, default=2.0, help="wait between calls (rate limit)")
    args = parser.parse_args()

    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[: args.limit]

    provider = get_llm_provider(settings)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    args.results_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.results_dir / f"{run_id}.jsonl"

    rows: list[dict] = []
    with out_path.open("w", encoding="utf-8") as out:
        for case in cases:
            row: dict = {"run_id": run_id, "id": case["id"], "text": case["text"], "model": provider.model}
            try:
                prompt = load_prompt("grammar", 1, text=case["text"])
                analysis = generate_with_retry(provider, prompt)
                # Same rule as production: only errors at or above MIN_CONFIDENCE are shown (and scored).
                shown = [e for e in analysis.errors if e.confidence >= MIN_CONFIDENCE]
                row["predicted"] = [e.model_dump(mode="json") for e in analysis.errors]
                row["shown"] = len(shown)
                row["score"] = score_case(case["expected_errors"], shown)
                row["error"] = None
                row["error_kind"] = None
            except Exception as exc:  # keep going: one failed call must not lose the run
                row["predicted"] = []
                row["score"] = {"expected": len(case["expected_errors"]), "detected": 0, "correct_fix": 0, "extra": 0}
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["error_kind"] = "quota" if isinstance(exc, LLMRateLimitError) else "other"
            rows.append(row)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            status = "ERR" if row["error"] else f"{row['score']['detected']}/{row['score']['expected']}"
            print(f"{case['id']} {status}")
            time.sleep(args.pause_s)

    s = summarize(rows)
    print(f"\nmodel={provider.model} cases={s['cases']} failed_calls={s['failed_calls']} failed_by_quota={s['failed_by_quota']}")
    if s["failed_calls"] == s["cases"]:
        # No call went through (no quota, bad key...): there is nothing to measure, so no numbers are reported.
        s.update(recall=None, fix_accuracy=None, false_positive_rate=None, extra_errors_in_error_cases=None)
        print("No case could be analysed: no metrics reported.")
    else:
        print(f"recall={_pct(s['recall'])} fix_accuracy={_pct(s['fix_accuracy'])}")
        print(f"false_positive_rate(correct sentences)={_pct(s['false_positive_rate'])} extra_errors={s['extra_errors_in_error_cases']}")
        if s["failed_calls"]:
            print("Metrics cover only the cases that got an answer.")
    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"run_id": run_id, "model": provider.model, **s}, indent=2), encoding="utf-8")
    print(f"saved: {out_path}\n       {summary_path}")


if __name__ == "__main__":
    main()
