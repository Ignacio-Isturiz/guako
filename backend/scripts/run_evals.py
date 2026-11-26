"""One command for every eval set of Guako (see evals/README.md).

Run from backend/:
    python -m scripts.run_evals grammar               # shows what it would send and its cost; sends NOTHING
    python -m scripts.run_evals grammar --yes         # runs it (3 repetitions by default)
    python -m scripts.run_evals all --yes             # grammar, judges, pronunciation, rag, wer, then the report
    python -m scripts.run_evals review                # human review of real turns, one at a time
    python -m scripts.run_evals review --summary      # agreement between the system and the person
    python -m scripts.run_evals report                # consolidated report of the latest runs

Without ``--yes`` nothing is sent. With it, a run whose estimate is above ``--max-cost`` (2 USD by default) does
not start, and the run's own spending cap is ``--max-cost`` too (see scripts/evals/common.py).
"""

import argparse
import sys

from app.config import settings
from scripts.evals import grammar, judges, pronunciation, rag, report, review, wer
from scripts.evals.common import DEFAULT_MAX_COST_USD, Tracker, over_limit, write_result

SETS = {"grammar": grammar, "judges": judges, "pronunciation": pronunciation, "rag": rag, "wer": wer}
DEFAULT_REPEATS = {"grammar": grammar.DEFAULT_REPEATS, "judges": 1, "pronunciation": 1, "rag": 1, "wer": 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", choices=[*SETS, "all", "review", "report"])
    parser.add_argument("--yes", action="store_true", help="really send the calls (without it nothing is sent)")
    parser.add_argument("--repeats", type=int, default=None, help="repetitions of the set (grammar: 3 by default)")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD, help="USD: refuse above this estimate, and stop paying at it")
    parser.add_argument("--llm-order", default=None, help="override LLM_ANALYSIS_ORDER for this run (e.g. groq,gemini,openai)")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases (a cheap try)")
    parser.add_argument("--summary", action="store_true", help="review: only print the agreement, ask nothing")
    args = parser.parse_args(argv)

    if args.target == "report":
        print(f"saved {report.write()}")
        return 0
    if args.target == "review":
        if not args.summary:
            review.review(review.load_turns())
        print("\n".join(review.describe(review.summarize(review.load_reviews()))))
        return 0

    names = list(SETS) if args.target == "all" else [args.target]
    tracker = Tracker(settings, budget_usd=args.max_cost, llm_order=args.llm_order)
    repeats = {n: args.repeats or DEFAULT_REPEATS[n] for n in names}
    plans = {n: SETS[n].plan(tracker.cfg, repeats[n], args.limit) for n in names}
    for p in plans.values():
        print(p.describe())
    total = sum(p.estimated_cost_usd for p in plans.values())
    print(f"TOTAL estimated cost: ${total:.4f} (limit ${args.max_cost:.2f})")
    if not args.yes:
        print("Nothing was sent. Run again with --yes to run it.")
        return 0
    if refusal := over_limit(list(plans.values()), args.max_cost):
        print(refusal)
        return 2

    spent = 0.0
    for n in names:
        print(f"\n== {n} ==")
        # Each set gets its own tracker (its own cost and providers), and what is left of the run's cap.
        tracker = Tracker(settings, budget_usd=max(args.max_cost - spent, 0.0), llm_order=args.llm_order)
        result = SETS[n].run(tracker, plans[n], repeats[n], args.limit)
        spent += result.get("actual_cost_usd", 0.0)
        path = write_result(result)
        print("\n".join(SETS[n].describe(result)))
        print(f"cases {result['cases']}, failed {result['failed']} {result['failure_reasons'] or ''}; cost ${result.get('actual_cost_usd', 0.0):.4f}; saved {path}")
    if args.target == "all":
        print(f"\nreport: {report.write()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
