"""The learner's memory: every grammar mistake is kept, so the report can say "this already happened to you".

Writing: when a turn's grammar analysis is saved, its errors are saved too as ``error_events`` (in the same
transaction, replacing any earlier ones of that turn, so a re-run never duplicates).

Reading: for the mistakes of the session being reported, count in how many *earlier* sessions of the same learner
the same mistake appeared. "The same" means:
- the same rule of the corpus (plain SQL, exact), or
- when no rule was close enough: the same error type and a very similar embedding (``memory_min_similarity``).

HONESTY RULE: this only counts what was seen *before*. The absence of a mistake in a session is never reported as
"you improved": the learner may simply not have used that structure, so the data cannot say it.
"""

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import ConversationSession, ErrorEvent, Turn

logger = logging.getLogger("app.rag")


def events_from(result: dict, vectors: list[list[float]]) -> list[dict]:
    """The errors of a grammar result, paired with their embeddings (same order, same length)."""
    errors = result.get("errors") or []
    if len(errors) != len(vectors):
        return []
    return [
        {
            "error_type": e["error_type"],
            "rule_id": e.get("rule_id"),
            "original": e["original"],
            "correction": e["correction"],
            "embedding": vector,
        }
        for e, vector in zip(errors, vectors, strict=True)
    ]


async def record_events(db: AsyncSession, *, user_id: int, session_id: int, turn_id: int, events: list[dict]) -> None:
    """Replace the memory of one turn. Does not commit: the caller commits it with the analysis."""
    await db.execute(delete(ErrorEvent).where(ErrorEvent.turn_id == turn_id))
    for event in events:
        db.add(ErrorEvent(user_id=user_id, session_id=session_id, turn_id=turn_id, **event))


async def seen_before(db: AsyncSession, session: ConversationSession) -> dict[tuple[int, str], int]:
    """{(turn_number, original): earlier sessions with the same mistake} for the mistakes of ``session``."""
    mine = (
        await db.execute(
            select(ErrorEvent, Turn.turn_number)
            .join(Turn, Turn.id == ErrorEvent.turn_id)
            .where(ErrorEvent.session_id == session.id)
        )
    ).all()
    counts: dict[tuple[int, str], int] = {}
    # Earlier sessions of the same learner (never the one being reported, never later ones).
    earlier = select(ConversationSession.id).where(
        ConversationSession.user_id == session.user_id,
        ConversationSession.id != session.id,
        ConversationSession.created_at < session.created_at,
    )
    for event, turn_number in mine:
        query = select(func.count(func.distinct(ErrorEvent.session_id))).where(
            ErrorEvent.user_id == session.user_id, ErrorEvent.session_id.in_(earlier)
        )
        if event.rule_id:
            query = query.where(ErrorEvent.rule_id == event.rule_id)
        else:
            similarity = 1 - ErrorEvent.embedding.cosine_distance(event.embedding)
            query = query.where(
                ErrorEvent.rule_id.is_(None),
                ErrorEvent.error_type == event.error_type,
                similarity >= settings.memory_min_similarity,
            )
        counts[(turn_number, event.original)] = int(await db.scalar(query) or 0)
    return counts
