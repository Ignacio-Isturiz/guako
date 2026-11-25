"""Attach to each grammar error the rule of the corpus that explains it.

Retrieval is a fixed step after the analysis (not an agent): for every error the analyser found, embed
"what was said -> the fix" and look for the closest rule. If even the best one is
not close enough, the error simply gets no rule: a wrong rule would be worse than none (same honesty rule
as the confidence threshold of the analysis).

It never raises: the rules are an extra on top of the analysis, which is already done by now.
"""

import logging

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.rag.embeddings import Embedder
from app.rag.store import search

logger = logging.getLogger("app.rag")


def query_text(error: dict) -> str:
    """What the embedding of an error is made of: the mistake, its fix and the analyser's own explanation."""
    return f"{error['original']} -> {error['correction']}. {error.get('explanation', '')}".strip()


async def find_rule(db: AsyncSession, vector: list[float], min_similarity: float) -> tuple[str, float] | None:
    """Best rule above the threshold, whatever its type.

    The analyser's error type is NOT used as a filter: it often differs from the type the corpus files the rule
    under ("she go" comes as verb_form, its rule is subject_verb_agreement). Measured on fragments like the real
    ones: coverage 74% -> 84% for 2 points of precision (evals/rag/cases_fragments.jsonl).
    """
    hits = await search(db, vector, None, limit=1)
    if hits and hits[0].similarity >= min_similarity:
        return hits[0].rule_id, hits[0].similarity
    return None


async def attach_rules(
    maker: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    result: dict,
    min_similarity: float | None = None,
    vectors_out: list[list[float]] | None = None,
) -> dict:
    """Adds ``rule_id`` and ``rule_similarity`` to each error of a grammar result that has a matching rule.

    ``vectors_out``, if given, receives the embedding of every error (the memory stores them): it is left empty
    when the embedding failed.
    """
    errors = result.get("errors") or []
    if not errors:
        return result
    threshold = settings.rag_min_similarity if min_similarity is None else min_similarity
    try:
        vectors = await run_in_threadpool(embedder.embed, [query_text(e) for e in errors], "query")
        if vectors_out is not None:
            vectors_out.extend(vectors)
        async with maker() as db:
            for error, vector in zip(errors, vectors, strict=True):
                found = await find_rule(db, vector, threshold)
                if found:
                    error["rule_id"], error["rule_similarity"] = found[0], round(found[1], 3)
    except Exception:  # embeddings down, quota, table not indexed yet...: the analysis stands without rules
        logger.exception("rag_attach_failed errors=%d", len(errors))
    return result
