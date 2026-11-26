"""Personalization eval, for now the grammar-rule retrieval: is the rule attached to an error the right one?

This is the only measurable piece of the personalization today: the personalized exercises have no eval set.
It uses the app's own lookup (``find_rule``: the closest rule of ANY type, above ``RAG_MIN_SIMILARITY``) on two case
files: evals/rag/cases.jsonl (mistakes written apart from the corpus) and evals/rag/cases_fragments.jsonl (short
fragments, like the ones the analyser really flags). Needs PostgreSQL with the corpus indexed
(``python -m scripts.index_rules``) and a Gemini key for the embeddings (free quota; no money).

- precision:     of the rules attached, how many were the expected one
- coverage:      of the cases that have a rule, how many got the expected one
- false attach:  of the cases with NO rule in the corpus, how many got one anyway (a wrong rule shown to a learner)
"""

import asyncio
from typing import Any

from app.config import settings
from app.rag import EmbeddingError, get_embedder
from app.rag.retrieve import find_rule, query_text
from scripts.evals.common import EVALS_DIR, Failure, Plan, base_result, load_jsonl, new_run_id, now_iso, with_retries

# Thresholds tried to (re)calibrate RAG_MIN_SIMILARITY: the report shows the metrics at each one.
THRESHOLDS = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)
CASE_FILES = {"written": EVALS_DIR / "rag" / "cases.jsonl", "fragments": EVALS_DIR / "rag" / "cases_fragments.jsonl"}


def plan(cfg: Any, repeats: int = 1, limit: int | None = None) -> Plan:  # noqa: ARG001
    total = sum(len(load_jsonl(p)[:limit] if limit else load_jsonl(p)) for p in CASE_FILES.values())
    return Plan(
        "rag",
        calls=total,
        estimated_cost_usd=0.0,
        notes=[f"{settings.embedding_model} embeddings (Gemini, free quota) + PostgreSQL; threshold {settings.rag_min_similarity}"],
    )


def score(cases: list[dict[str, Any]], best: list[tuple[str, float] | None], threshold: float) -> dict[str, Any]:
    """``best`` = the closest rule of each case and its similarity; a rule is attached only at or above ``threshold``."""
    found = [b if b and b[1] >= threshold else None for b in best]
    with_rule = [(c, f) for c, f in zip(cases, found, strict=True) if c["expected_rule"]]
    without = [(c, f) for c, f in zip(cases, found, strict=True) if not c["expected_rule"]]
    attached = [(c, f) for c, f in zip(cases, found, strict=True) if f]
    right = sum(1 for c, f in attached if f[0] == c["expected_rule"])
    return {
        "cases": len(cases),
        "cases_with_rule": len(with_rule),
        "cases_without_rule": len(without),
        "precision": round(right / len(attached), 4) if attached else None,
        "coverage": round(sum(1 for c, f in with_rule if f and f[0] == c["expected_rule"]) / len(with_rule), 4) if with_rule else None,
        "false_attach": round(sum(1 for _, f in without if f) / len(without), 4) if without else None,
    }


async def _lookup(cases: list[dict[str, Any]]) -> list[tuple[str, float] | None]:
    from app.db import async_session_maker, engine  # imported here: building the engine needs a valid DATABASE_URL

    embedder = get_embedder()
    if embedder is None:
        raise RuntimeError("GEMINI_API_KEY is not set")
    vectors = await asyncio.to_thread(embedder.embed, [query_text(c) for c in cases], "query")
    try:
        async with async_session_maker() as db:
            return [await find_rule(db, v, 0.0) for v in vectors]  # the best rule; thresholds are applied in score()
    finally:
        await engine.dispose()  # each asyncio.run has its own event loop: no pooled connection may outlive it


def classify(exc: Exception) -> Failure:
    """An embedding failure (often Gemini's per-minute limit) is retried; a database that cannot be reached is not."""
    if isinstance(exc, EmbeddingError):
        return Failure("provider_error", True)
    if isinstance(exc, OSError) or type(exc).__module__.startswith("asyncpg") or "connect" in str(exc).lower():
        return Failure("db_unreachable", False)
    return Failure("unexpected_error", False)


def run(tracker: Any, the_plan: Plan, repeats: int = 1, limit: int | None = None, log=print) -> dict[str, Any]:  # noqa: ANN001, ARG001
    run_id, started = new_run_id(), now_iso()
    rows: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"threshold": settings.rag_min_similarity}
    for name, path in CASE_FILES.items():
        cases = load_jsonl(path)[:limit] if limit else load_jsonl(path)
        attempt = with_retries(lambda c=cases: asyncio.run(_lookup(c)), classify)
        if not attempt.ok:  # no database, no key, no quota: every case fails with the reason, none is dropped
            rows += [{"file": name, "original": c["original"], "failure": attempt.failure, "error": attempt.error} for c in cases]
            metrics[name] = None
            log(f"  {name}: FAILED ({attempt.failure}) {attempt.error}")
            continue
        found = attempt.value
        rows += [
            {"file": name, "original": c["original"], "expected_rule": c["expected_rule"], "best_rule": f[0] if f else None,
             "similarity": round(f[1], 3) if f else None, "attached": bool(f and f[1] >= settings.rag_min_similarity)}
            for c, f in zip(cases, found, strict=True)
        ]  # fmt: skip
        metrics[name] = score(cases, found, settings.rag_min_similarity)
        metrics[f"{name}_sweep"] = {str(t): score(cases, found, t) for t in THRESHOLDS}
        log(f"  {name}: {metrics[name]}")
    return base_result(
        "rag", run_id, started, the_plan, rows,
        prompt_version=None, embedding_model=settings.embedding_model, actual_cost_usd=0.0,
        served_by={f"gemini:{settings.embedding_model}": sum(1 for r in rows if not r.get("failure"))}, metrics=metrics,
        not_measured=["personalized exercises: there is no eval set for them yet"],
    )  # fmt: skip


def describe(result: dict[str, Any]) -> list[str]:
    lines = [f"rule retrieval at threshold {result['metrics']['threshold']} ({result['embedding_model']})"]
    for name in CASE_FILES:
        m = result["metrics"].get(name)
        if m is None:
            lines.append(f"  {name}: NOT MEASURED ({', '.join(sorted(result['failure_reasons'])) or 'no result'})")
            continue
        pct = lambda v: "n/a" if v is None else f"{v:.0%}"  # noqa: E731
        lines.append(f"  {name} ({m['cases']} cases): precision {pct(m['precision'])}, coverage {pct(m['coverage'])}, false attach {pct(m['false_attach'])}")
        sweep = result["metrics"].get(f"{name}_sweep") or {}
        lines += [f"    at {t}: precision {pct(v['precision'])}, coverage {pct(v['coverage'])}, false attach {pct(v['false_attach'])}" for t, v in sweep.items()]
    lines += [f"  NOT MEASURED: {item}" for item in result.get("not_measured", [])]
    return lines
