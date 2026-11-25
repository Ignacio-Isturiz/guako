"""Write exercises with the LLM, check them with the grammar analyser and (unless --dry-run) store them.

Uses the analysis LLM chain, so it SPENDS provider quota: one batch is 1 call to write plus 2 to 7 calls to check.
Run it from backend/ (with DATABASE_URL pointing at the database you want to fill)::

    python -m scripts.generate_exercises --rule article.a_an --dry-run   # only print what would be accepted
    python -m scripts.generate_exercises --rule article.a_an --batches 3
    python -m scripts.generate_exercises --all --batches 1               # one batch for each of the rules

Read what comes out: the analyser is the same kind of model as the writer, so a wrong exercise can slip through.
"""

import argparse
import asyncio
import sys

from app.config import settings
from app.db import async_session_maker
from app.exercises.generated import bank_signatures, replenish, write_and_check
from app.providers import chains
from app.rag.corpus import rules_by_id


def show(rule_id: str, accepted, rejected: dict[str, str]) -> None:
    print(f"\n== {rule_id}")
    for c in accepted:
        print(f"  ACCEPTED {c.kind}: {c.prompt}")
        if c.options:
            print("     options (first is right):", " | ".join(c.options))
        elif c.kind == "fix":
            print("     right:", c.answers[0])
        else:
            print("     answer:", c.answers[0])
    for kind, why in rejected.items():
        print(f"  rejected {kind}: {why}")


async def main(args: argparse.Namespace) -> int:
    rules = sorted(rules_by_id()) if args.all else args.rule
    unknown = [r for r in rules if r not in rules_by_id()]
    if not rules or unknown:
        print(f"Give --rule <id> (unknown: {unknown}) or --all.")
        return 1
    llm = chains.analysis_llm(settings)
    settings.exercises_generation_cooldown_seconds = 0  # this is a person asking, not the app
    totals = {"accepted": 0, "rejected": 0}
    for rule_id in rules:
        for _ in range(args.batches):
            if args.dry_run:
                try:
                    accepted, rejected = await asyncio.to_thread(write_and_check, llm, rules_by_id()[rule_id], bank_signatures(rule_id))
                except Exception as exc:  # providers out of quota or unavailable: say so and go on with the next rule
                    print(f"\n== {rule_id}: failed ({type(exc).__name__}: {exc})")
                    continue
            else:
                report = await replenish(async_session_maker, llm, rule_id)
                if report.skipped:
                    print(f"\n== {rule_id}: skipped ({report.skipped})")
                    continue
                accepted = [type("C", (), {"kind": r.kind, "prompt": r.prompt, "options": r.options, "answers": r.answers}) for r in report.accepted]
                rejected = report.rejected
            totals["accepted"] += len(accepted)
            totals["rejected"] += len(rejected)
            show(rule_id, accepted, rejected)
    print(f"\nAccepted {totals['accepted']}, rejected {totals['rejected']}" + (" (dry run: nothing was stored)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule", action="append", default=[], help="rule id (repeat for several)")
    parser.add_argument("--all", action="store_true", help="every rule of the corpus")
    parser.add_argument("--batches", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="do not store anything")
    sys.exit(asyncio.run(main(parser.parse_args())))
