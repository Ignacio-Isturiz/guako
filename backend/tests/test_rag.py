"""RAG over the grammar-rule corpus.

The corpus and the report tests run anywhere. The tests that search need PostgreSQL with pgvector: they use a
throwaway database (``ragtest``) on the server given by RAG_TEST_SERVER (default: the dev container on port 5433,
``docker run -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=rag-dev-only -p 5433:5432 pgvector/pgvector:pg16``) and are
skipped when it is not reachable. They use a fake embedder: no network, no quota.
"""

import asyncio
import hashlib
import math
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.analysis.grammar import GrammarErrorType
from app.config import settings
from app.db import GrammarRuleEmbedding
from app.rag.corpus import CorpusError, Rule, load_rules, rules_by_id
from app.rag.embeddings import EmbeddingError
from app.rag.retrieve import attach_rules, query_text
from app.rag.store import search, sync_index
from app.reports import build_grammar_report

SERVER = os.environ.get("RAG_TEST_SERVER", "postgresql+asyncpg://rag:rag-dev-only@127.0.0.1:5433")
DIM = settings.embedding_dimensions


class FakeEmbedder:
    """Bag of words hashed into DIM buckets: texts that share words are close. Deterministic, offline."""

    dimensions = DIM

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * DIM
            for word in re.findall(r"[a-z']+", t.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class BrokenEmbedder:
    dimensions = DIM

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        raise EmbeddingError("down")


# --- the corpus ---------------------------------------------------------------------------------


def test_corpus_loads_and_covers_every_error_type() -> None:
    rules = load_rules()
    assert len(rules) >= 50
    assert len({r.id for r in rules}) == len(rules)
    covered = {r.error_type for r in rules}
    assert covered == {t.value for t in GrammarErrorType}, "every type the analyser can output needs rules"
    for rule in rules:
        assert rule.id.startswith(rule.error_type + ".")
        assert len(rule.examples) >= 2 and rule.rule_es and rule.spanish_note


def test_every_example_is_written_as_wrong_to_right() -> None:
    for rule in load_rules():
        for example in rule.examples:
            wrong, right = (part.strip() for part in example.split("->"))
            assert wrong and right and wrong != right, f"{rule.id}: {example}"


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "x.txt").write_text(body, encoding="utf-8")
    return tmp_path


GOOD = (
    "id: article.a\nerror_type: article\nlevel: A1\ntitle: T\nrule: R\nrule_es: RE\n"
    "examples:\n- a -> b\nspanish_note: N\n"
)


@pytest.mark.parametrize(
    "body",
    [
        GOOD.replace("error_type: article", "error_type: nonsense"),
        GOOD.replace("id: article.a", "id: verb_form.a"),
        GOOD.replace("level: A1", "level: Z9"),
        GOOD.replace("- a -> b", "- no arrow here"),
        GOOD.replace("rule_es: RE\n", ""),
        GOOD + "surprise: field\n",
        GOOD + "\n===\n" + GOOD,  # duplicated id
    ],
)
def test_malformed_rule_files_are_rejected(tmp_path: Path, body: str) -> None:
    with pytest.raises(CorpusError):
        load_rules.__wrapped__(_write(tmp_path, body))


def test_embedding_text_changes_when_the_rule_changes() -> None:
    a = load_rules()[0]
    b = Rule(**{**a.__dict__, "rule": a.rule + " Extra."})
    assert a.content_hash != b.content_hash
    assert a.embedding_text().startswith(a.title)


# --- the report ---------------------------------------------------------------------------------


class _Row:
    def __init__(self, result: dict) -> None:
        self.status, self.result = "done", result


def _report(errors: list[dict]):
    return build_grammar_report([(1, "I have seen him yesterday")], {1: _Row({"errors": errors})})


def _error(**extra: str) -> dict:
    return {"original": "have seen", "correction": "saw", "error_type": "verb_tense", "explanation": "x", **extra}


def test_report_shows_the_rule_of_the_corpus() -> None:
    rule_id = "verb_tense.present_perfect_vs_past"
    shown = _report([_error(rule_id=rule_id)]).errors[0].rule
    assert shown is not None
    assert (shown.id, shown.rule, shown.rule_es) == (rule_id, rules_by_id()[rule_id].rule, rules_by_id()[rule_id].rule_es)


@pytest.mark.parametrize("extra", [{}, {"rule_id": "verb_tense.was_deleted_from_the_corpus"}])
def test_report_has_no_rule_when_there_is_none(extra: dict) -> None:
    assert _report([_error(**extra)]).errors[0].rule is None


# --- search (PostgreSQL + pgvector) -------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_url() -> str:
    """URL of a throwaway database with the table created; the test is skipped when there is no server."""

    async def prepare() -> None:
        admin = create_async_engine(f"{SERVER}/postgres", isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                if not await conn.scalar(text("select 1 from pg_database where datname = 'ragtest'")):
                    await conn.execute(text("create database ragtest"))
        finally:
            await admin.dispose()

    try:
        asyncio.run(prepare())
    except Exception as exc:  # no server: these tests cannot run here
        pytest.skip(f"PostgreSQL with pgvector not reachable ({type(exc).__name__})")
    return f"{SERVER}/ragtest"


@asynccontextmanager
async def open_maker(url: str):
    """A session factory with an empty ``grammar_rules`` table, created inside the running event loop."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("create extension if not exists vector"))
            await conn.execute(text("drop table if exists grammar_rules"))
            await conn.run_sync(GrammarRuleEmbedding.__table__.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def test_index_is_incremental(pg_url: str) -> None:
    embedder = FakeEmbedder()
    rules = load_rules()

    async def go():
        async with open_maker(pg_url) as maker:
            async with maker() as db:
                first = await sync_index(db, embedder, rules)
            async with maker() as db:
                again = await sync_index(db, embedder, rules)
            changed = (Rule(**{**rules[0].__dict__, "rule": "A different rule."}), *rules[2:])  # one edited, one deleted
            async with maker() as db:
                third = await sync_index(db, embedder, changed)
                count = len((await db.scalars(select(GrammarRuleEmbedding.id))).all())
        return first, again, third, count

    first, again, third, count = asyncio.run(go())
    assert (first.added, first.unchanged) == (len(rules), 0)
    assert (again.added, again.updated, again.unchanged) == (0, 0, len(rules))
    assert (third.updated, third.removed, third.added) == (1, 1, 0)
    assert count == len(rules) - 1


def test_search_filters_by_error_type_and_ranks_by_similarity(pg_url: str) -> None:
    embedder = FakeEmbedder()

    async def go():
        async with open_maker(pg_url) as maker:
            async with maker() as db:
                await sync_index(db, embedder)
            query = embedder.embed(["I have seen him yesterday -> I saw him yesterday"], "query")[0]
            async with maker() as db:
                return await search(db, query, "verb_tense", 3), await search(db, query, "article", 3)

    tense, article = asyncio.run(go())
    assert tense[0].rule_id == "verb_tense.present_perfect_vs_past"
    assert tense[0].similarity >= tense[1].similarity
    assert all(h.rule_id.startswith("article.") for h in article)


def test_attach_rules_adds_only_close_rules_and_survives_failures(pg_url: str) -> None:
    embedder = FakeEmbedder()

    def result() -> dict:
        return {
            "errors": [
                {"original": "I have seen him yesterday", "correction": "I saw him yesterday",
                 "error_type": "verb_tense", "explanation": "Use the past simple with yesterday."},
                {"original": "zzz qqq", "correction": "xxx", "error_type": "verb_tense", "explanation": ""},
            ]
        }

    async def go():
        async with open_maker(pg_url) as maker:
            async with maker() as db:
                await sync_index(db, embedder)
            ok = await attach_rules(maker, embedder, result(), min_similarity=0.3)
            broken = await attach_rules(maker, BrokenEmbedder(), result(), min_similarity=0.3)
        return ok, broken

    ok, broken = asyncio.run(go())
    assert ok["errors"][0]["rule_id"] == "verb_tense.present_perfect_vs_past"
    assert 0.3 <= ok["errors"][0]["rule_similarity"] <= 1
    assert "rule_id" not in ok["errors"][1], "a gibberish error must not get a rule"
    assert broken == result(), "a failing embedder leaves the analysis as it was"
    assert query_text(result()["errors"][0]).startswith("I have seen him yesterday -> I saw him yesterday.")
