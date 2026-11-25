"""Keeping the vector table in step with the corpus, and searching it. PostgreSQL + pgvector only."""

import logging
from dataclasses import dataclass

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import GrammarRuleEmbedding
from app.rag.corpus import Rule, load_rules
from app.rag.embeddings import Embedder

logger = logging.getLogger("app.rag")


@dataclass(frozen=True)
class IndexReport:
    added: int
    updated: int
    removed: int
    unchanged: int


@dataclass(frozen=True)
class Hit:
    rule_id: str
    similarity: float  # cosine similarity, 1 = same direction


async def sync_index(db: AsyncSession, embedder: Embedder, rules: tuple[Rule, ...] | None = None) -> IndexReport:
    """Embed the rules that are new or whose text changed, drop the ones that no longer exist. Commits."""
    rules = rules if rules is not None else load_rules()
    rows = {row.id: row for row in (await db.scalars(select(GrammarRuleEmbedding))).all()}
    stale = [r for r in rules if r.id not in rows or rows[r.id].content_hash != r.content_hash]
    if stale:
        vectors = await run_in_threadpool(embedder.embed, [r.embedding_text() for r in stale], "document")
        for rule, vector in zip(stale, vectors, strict=True):
            row = rows.get(rule.id)
            if row is None:
                db.add(GrammarRuleEmbedding(id=rule.id, error_type=rule.error_type, level=rule.level,
                                            content_hash=rule.content_hash, embedding=vector))
            else:
                row.error_type, row.level, row.content_hash, row.embedding = rule.error_type, rule.level, rule.content_hash, vector
    gone = [rid for rid in rows if rid not in {r.id for r in rules}]
    if gone:
        await db.execute(delete(GrammarRuleEmbedding).where(GrammarRuleEmbedding.id.in_(gone)))
    await db.commit()
    added = sum(1 for r in stale if r.id not in rows)
    report = IndexReport(added=added, updated=len(stale) - added, removed=len(gone), unchanged=len(rules) - len(stale))
    logger.info("rag_index %s", report)
    return report


async def search(db: AsyncSession, vector: list[float], error_type: str | None, limit: int = 3) -> list[Hit]:
    """The ``limit`` closest rules, best first. ``error_type`` filters by metadata first (None = every type)."""
    distance = GrammarRuleEmbedding.embedding.cosine_distance(vector)
    query = select(GrammarRuleEmbedding.id, distance.label("distance")).order_by(distance).limit(limit)
    if error_type is not None:
        query = query.where(GrammarRuleEmbedding.error_type == error_type)
    return [Hit(rule_id=row.id, similarity=1.0 - float(row.distance)) for row in (await db.execute(query)).all()]
