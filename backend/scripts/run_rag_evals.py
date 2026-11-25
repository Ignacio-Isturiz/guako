"""Measure the grammar-rule retrieval and calibrate ``RAG_MIN_SIMILARITY`` (REAL embedding calls, free quota).

Run from backend/ with DATABASE_URL pointing at a PostgreSQL where the corpus is indexed
(``python -m scripts.index_rules``)::

    python -m scripts.run_rag_evals                                # evals/rag/cases.jsonl, typed search
    python -m scripts.run_rag_evals evals/rag/cases_fragments.jsonl --untyped

``--untyped`` searches every rule whatever error type the analyser gave (the LLM's type often differs from the
corpus type). A path argument picks another case file.

Each case in evals/rag/cases.jsonl is a mistake a learner could make, written apart from the corpus examples
(so the rules are not "tested on their own answers"), with the rule that should explain it, or ``null`` when the
corpus has no rule for it (nothing should be attached then). For each threshold it reports:

- precision: of the rules attached, how many were the expected one
- coverage: of the cases that have a rule, how many got the expected one
- false attach: of the cases without a rule, how many got one anyway (a wrong rule shown to a learner)
"""

import asyncio
import json
import sys
from pathlib import Path

from app.config import settings
from app.db import async_session_maker
from app.rag import get_embedder
from app.rag.retrieve import query_text
from app.rag.store import search

CASES = Path(__file__).resolve().parents[1] / "evals" / "rag" / "cases.jsonl"
THRESHOLDS = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75)


async def main(argv: list[str]) -> int:
    untyped = "--untyped" in argv
    paths = [a for a in argv if not a.startswith("--")]
    source = Path(paths[0]) if paths else CASES
    embedder = get_embedder()
    if embedder is None:
        print("GEMINI_API_KEY is not set.")
        return 1
    cases = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    vectors = embedder.embed([query_text(c) for c in cases], "query")
    best = []
    async with async_session_maker() as db:
        for case, vector in zip(cases, vectors, strict=True):
            top = (await search(db, vector, None if untyped or case["error_type"] == "other" else case["error_type"], limit=1))[0]
            best.append((case, top.rule_id, top.similarity))

    with_rule = [b for b in best if b[0]["expected_rule"]]
    without = [b for b in best if not b[0]["expected_rule"]]
    top1 = sum(1 for c, rid, _ in with_rule if rid == c["expected_rule"])
    print(f"{len(with_rule)} cases with a rule, {len(without)} without. Top-1 with no threshold: {top1}/{len(with_rule)}")
    print("\nWrong top-1 (expected -> got, similarity):")
    for c, rid, sim in with_rule:
        if rid != c["expected_rule"]:
            print(f"  {c['original']!r}: {c['expected_rule']} -> {rid} ({sim:.3f})")
    print("\nCases without a rule: what they would get with no threshold:")
    for c, rid, sim in without:
        print(f"  {c['original']!r}: {rid} ({sim:.3f})")

    print(f"\n{'threshold':>9} {'precision':>10} {'coverage':>9} {'false attach':>13}   (current: {settings.rag_min_similarity})")
    for t in THRESHOLDS:
        attached = [b for b in best if b[2] >= t]
        right = sum(1 for c, rid, _ in attached if c["expected_rule"] == rid)
        coverage = sum(1 for c, rid, s in with_rule if s >= t and rid == c["expected_rule"])
        false = sum(1 for c, _, s in without if s >= t)
        precision = f"{right / len(attached):.0%}" if attached else "-"
        print(f"{t:>9.2f} {precision:>10} {coverage / len(with_rule):>9.0%} {false}/{len(without)} = {false / len(without):.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
