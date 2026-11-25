"""Memory of the learner (RAG 2): saving the mistakes and counting the earlier sessions where they happened.

Needs PostgreSQL with pgvector, like the search tests in test_rag.py (same throwaway ``ragtest`` database, skipped
when there is no server). Offline: the vectors are written by hand.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import Base, ConversationSession, ErrorEvent, Turn, User
from app.rag.memory import events_from, record_events, seen_before
from tests.test_rag import pg_url  # noqa: F401  (fixture: skips when there is no PostgreSQL)

DIM = settings.embedding_dimensions
RULE = "verb_tense.present_perfect_vs_past"


def vec(*head: float) -> list[float]:
    """A unit vector that points at the first dimensions: easy to make similar or different vectors."""
    v = [0.0] * DIM
    for i, x in enumerate(head):
        v[i] = x
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


@asynccontextmanager
async def database(url: str):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("create extension if not exists vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def make_user(db, name: str) -> User:
    user = User(email=f"{name}@example.com", hashed_password="x", username=name)
    db.add(user)
    await db.flush()
    return user


async def make_session(db, user: User, days_ago: int) -> tuple[ConversationSession, Turn]:
    session = ConversationSession(
        user_id=user.id, level="B1", topic="t", created_at=datetime.now(UTC) - timedelta(days=days_ago)
    )
    db.add(session)
    await db.flush()
    turn = Turn(session_id=session.id, turn_number=1, user_transcript="x", reply_text="y")
    db.add(turn)
    await db.flush()
    return session, turn


def event(original: str = "have seen", rule_id: str | None = RULE, error_type: str = "verb_tense", embedding=None) -> dict:
    return {
        "error_type": error_type,
        "rule_id": rule_id,
        "original": original,
        "correction": "saw",
        "embedding": embedding or vec(1, 0),
    }


def test_events_from_pairs_errors_with_vectors() -> None:
    result = {"errors": [{"original": "a", "correction": "b", "error_type": "article", "rule_id": "article.a_an"}]}
    [one] = events_from(result, [vec(1)])
    assert (one["rule_id"], one["original"], one["error_type"]) == ("article.a_an", "a", "article")
    assert events_from(result, []) == [], "no vectors (the embedding failed): nothing to remember"
    assert events_from({"errors": []}, []) == []


def test_record_events_replaces_the_turn_and_does_not_duplicate(pg_url: str) -> None:  # noqa: F811
    async def go() -> list[str]:
        async with database(pg_url) as maker, maker() as db:
            user = await make_user(db, "ana")
            session, turn = await make_session(db, user, 0)
            for events in ([event("first"), event("second")], [event("only")]):
                await record_events(db, user_id=user.id, session_id=session.id, turn_id=turn.id, events=events)
                await db.commit()
            return list((await db.scalars(select(ErrorEvent.original))).all())

    assert asyncio.run(go()) == ["only"]


def test_seen_before_counts_earlier_sessions_of_the_same_learner_by_rule(pg_url: str) -> None:  # noqa: F811
    async def go() -> dict:
        async with database(pg_url) as maker, maker() as db:
            ana, bob = await make_user(db, "ana"), await make_user(db, "bob")
            rows = {}
            for name, user, days in (("old1", ana, 9), ("old2", ana, 5), ("now", ana, 1), ("later", ana, 0), ("other", bob, 7)):
                rows[name] = await make_session(db, user, days)
            # "now" is reported; "later" is created after it (it must not count) and so is bob's session.
            rows["later"][0].created_at = datetime.now(UTC) + timedelta(days=1)
            for name in ("old1", "old1", "old2", "now", "later", "other"):  # old1 twice: still one session
                session, turn = rows[name]
                await record_events(db, user_id=session.user_id, session_id=session.id, turn_id=turn.id,
                                    events=[event()] if name != "old1" else [event(), event("had seen")])
            await db.commit()
            return await seen_before(db, rows["now"][0])

    assert asyncio.run(go()) == {(1, "have seen"): 2}


def test_seen_before_without_a_rule_uses_similar_vectors_of_the_same_type(pg_url: str) -> None:  # noqa: F811
    async def go() -> dict:
        async with database(pg_url) as maker, maker() as db:
            user = await make_user(db, "ana")
            old_a, turn_a = await make_session(db, user, 9)  # a very similar mistake, same type
            old_b, turn_b = await make_session(db, user, 8)  # a different mistake, same type
            old_c, turn_c = await make_session(db, user, 7)  # a similar vector but another type
            now, turn_now = await make_session(db, user, 1)
            for s, t, ev in (
                (old_a, turn_a, event("x", None, "vocabulary", vec(1, 0.05))),
                (old_b, turn_b, event("y", None, "vocabulary", vec(0, 1))),
                (old_c, turn_c, event("z", None, "article", vec(1, 0.05))),
                (now, turn_now, event("w", None, "vocabulary", vec(1, 0))),
            ):
                await record_events(db, user_id=user.id, session_id=s.id, turn_id=t.id, events=[ev])
            await db.commit()
            return await seen_before(db, now)

    assert asyncio.run(go()) == {(1, "w"): 1}
