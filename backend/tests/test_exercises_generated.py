"""Personalised practice, layer 2: exercises written by the LLM and accepted only if the grammar analyser agrees.

No real LLM: a scripted one writes the batch and judges every sentence ("bad" sentences get an error, the rest none).
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import exercises_api
from app.analysis.grammar import GrammarErrorType, TurnGrammarAnalysis, TurnGrammarError
from app.config import settings
from app.db import GeneratedExercise
from app.exercises import build_plan, generated
from app.exercises.generated import GenBatch, GenChoice, GenFill, GenFix, candidates_from, replenish, to_exercises, verify, write_and_check
from app.rag.corpus import rules_by_id
from tests.test_exercises import _remember, short_audio  # noqa: F401  (autouse fixture + helper)
from tests.test_sessions_api import _login, _new_session

RULE = "article.a_an"

GOOD = GenBatch(
    choice=GenChoice(right="My cousin bought an expensive watch.", wrong=["My cousin bought a expensive watch.", "My cousin bought expensive watch."]),
    fill=GenFill(sentence="She found ___ old coin in the garden.", answer="an", wrong_answer="a", hint="a / an"),
    fix=GenFix(wrong="He ate a apple after lunch.", right="He ate an apple after lunch."),
)
# What the "analyser" calls wrong (anything else it finds correct).
BAD = {
    "My cousin bought a expensive watch.",
    "My cousin bought expensive watch.",
    "She found a old coin in the garden.",
    "He ate a apple after lunch.",
}


class ScriptLLM:
    def __init__(self, batch: GenBatch = GOOD, bad: set[str] = BAD, error: Exception | None = None) -> None:
        self.batch, self.bad, self.error = batch, bad, error
        self.calls = {"batch": 0, "analysis": 0}

    def generate(self, prompt: str, response_model: type, *, system: str | None = None):  # noqa: ANN201
        if self.error:
            raise self.error
        if response_model is GenBatch:
            self.calls["batch"] += 1
            return self.batch
        assert response_model is TurnGrammarAnalysis
        self.calls["analysis"] += 1
        wrong = any(f"Text: {s}" in prompt or s in prompt for s in self.bad)
        errors = [TurnGrammarError(original="x", correction="y", error_type=GrammarErrorType.ARTICLE, explanation="e", confidence=0.95)] if wrong else []
        return TurnGrammarAnalysis(errors=errors)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch) -> None:
    generated._IN_FLIGHT.clear()
    generated._LAST_TRY.clear()
    monkeypatch.setattr(settings, "exercises_generation_cooldown_seconds", 0.0)


# ── turning the batch into candidates ──────────────────────────────────────

def test_a_good_batch_gives_three_candidates_with_the_sentences_to_judge() -> None:
    candidates, rejected = candidates_from(GOOD)
    assert rejected == {} and [c.kind for c in candidates] == ["choice", "fill", "fix"]
    choice, fill, fix = candidates
    assert choice.options[0] == choice.answers[0] == "My cousin bought an expensive watch."
    assert choice.must_be_correct == [choice.options[0]] and len(choice.must_have_error) == 2
    assert fill.prompt == "She found ___ old coin in the garden. (a / an)" and fill.answers == ["an"]
    assert fill.must_be_correct == ["She found an old coin in the garden."]  # the hint is not part of the sentence judged
    assert fill.must_have_error == ["She found a old coin in the garden."]
    assert (fix.prompt, fix.answers) == ("He ate a apple after lunch.", ["He ate an apple after lunch."])


@pytest.mark.parametrize(
    ("batch", "kind"),
    [
        (GenBatch(choice=GenChoice(right="Same.", wrong=["Same.", "Other."]), fill=GOOD.fill, fix=GOOD.fix), "choice"),
        (GenBatch(choice=GOOD.choice, fill=GenFill(sentence="No gap here.", answer="an", wrong_answer="a", hint="x"), fix=GOOD.fix), "fill"),
        (GenBatch(choice=GOOD.choice, fill=GenFill(sentence="A ___ b.", answer="an", wrong_answer="a"), fix=GOOD.fix), "fill"),
        (GenBatch(choice=GOOD.choice, fill=GenFill(sentence="Two ___ gaps ___.", answer="an", wrong_answer="a", hint="x"), fix=GOOD.fix), "fill"),
        (GenBatch(choice=GOOD.choice, fill=GenFill(sentence="A ___ b.", answer="x", wrong_answer="X", hint="x"), fix=GOOD.fix), "fill"),
        (GenBatch(choice=GOOD.choice, fill=GenFill(sentence="A ___ b.", answer="one two three four", wrong_answer="a", hint="x"), fix=GOOD.fix), "fill"),
        (GenBatch(choice=GOOD.choice, fill=GOOD.fill, fix=GenFix(wrong="It is fine.", right="it is fine")), "fix"),
    ],
)
def test_malformed_exercises_are_dropped_before_spending_any_check(batch: GenBatch, kind: str) -> None:
    candidates, rejected = candidates_from(batch)
    assert kind in rejected and kind not in [c.kind for c in candidates]


# ── verifying with the analyser ────────────────────────────────────────────

def test_verify_accepts_only_what_the_analyser_agrees_with() -> None:
    choice, fill, fix = candidates_from(GOOD)[0]
    assert verify(ScriptLLM(), choice, []) is None and verify(ScriptLLM(), fill, []) is None and verify(ScriptLLM(), fix, []) is None
    # the analyser finds an error in the sentence that should be correct
    flagged = ScriptLLM(bad=BAD | {"He ate an apple after lunch."})
    assert "what should be correct" in verify(flagged, fix, [])
    # the analyser finds no error in the sentence that should be wrong
    lenient = ScriptLLM(bad=BAD - {"He ate a apple after lunch."})
    assert "what should be wrong" in verify(lenient, fix, [])
    lenient_choice = ScriptLLM(bad={"My cousin bought a expensive watch."})  # misses the second wrong option
    assert "what should be wrong" in verify(lenient_choice, choice, [])


def test_verify_rejects_a_copy_of_an_existing_exercise_without_calling_the_llm() -> None:
    fix = candidates_from(GOOD)[0][2]
    llm = ScriptLLM()
    assert verify(llm, fix, ["He ate a apple after dinner."]) == "too similar to an existing exercise"
    assert llm.calls["analysis"] == 0
    assert verify(llm, fix, ["The children play in the park every day."]) is None
    choice = candidates_from(GOOD)[0][0]  # every choice asks the same question: its SENTENCE is what must differ
    assert verify(llm, choice, ["My cousin bought an expensive watch today."]) == "too similar to an existing exercise"
    assert verify(llm, choice, [generated.CHOICE_PROMPT, "She wants an orange."]) is None


def test_write_and_check_keeps_the_good_ones_and_says_why_it_dropped_the_rest() -> None:
    llm = ScriptLLM(bad=BAD - {"He ate a apple after lunch."})  # the analyser does not see the fix's mistake
    accepted, rejected = write_and_check(llm, rules_by_id()[RULE], [])
    assert [c.kind for c in accepted] == ["choice", "fill"]
    assert list(rejected) == ["fix"] and "what should be wrong" in rejected["fix"]
    assert llm.calls["batch"] == 1


def test_the_prompt_carries_the_rule_and_the_sentences_to_avoid() -> None:
    prompt = generated._prompt_for(rules_by_id()[RULE], ["She wants an orange."])
    assert rules_by_id()[RULE].title in prompt and "She wants an orange." in prompt
    assert "{" not in prompt.replace("{}", ""), "no placeholder was left unfilled"


# ── storing, caps and failures ─────────────────────────────────────────────

async def _maker(db_path: Path):  # noqa: ANN202
    from app.db import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_replenish_stores_only_what_passed_and_the_rows_give_exercises(db_path: Path) -> None:
    async def go():
        engine, maker = await _maker(db_path)
        try:
            report = await replenish(maker, ScriptLLM(), RULE)
            async with maker() as db:
                rows = (await db.scalars(select(GeneratedExercise).order_by(GeneratedExercise.id))).all()
            return report, rows
        finally:
            await engine.dispose()

    report, rows = asyncio.run(go())
    assert report.skipped == "" and report.rejected == {} and len(report.accepted) == 3
    assert [r.kind for r in rows] == ["choice", "fill", "fix"] and {r.rule_id for r in rows} == {RULE}
    choice, fill, fix = rows
    assert choice.options[0] == "My cousin bought an expensive watch." and choice.answers == [choice.options[0]]
    ex = to_exercises(fix)
    assert [e.id for e in ex] == [f"gen:{fix.id}", f"gen:{fix.id}:speak"] and [e.kind for e in ex] == ["fix", "speak"]
    assert ex[1].prompt == "He ate an apple after lunch." and ex[1].wrong == "He ate a apple after lunch."
    assert [e.kind for e in to_exercises(choice)] == ["choice"] and [e.kind for e in to_exercises(fill)] == ["fill"]
    assert generated.parse_id(f"gen:{fix.id}:speak") == (fix.id, "speak") and generated.parse_id("gen:x") is None
    assert generated.parse_id("article.a_an:fix:1") is None and generated.parse_id("mine:3:fix") is None


def test_replenish_waits_between_tries_and_never_runs_twice_at_once(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "exercises_generation_cooldown_seconds", 600.0)

    async def go():
        engine, maker = await _maker(db_path)
        try:
            first = await replenish(maker, ScriptLLM(), RULE)
            second = await replenish(maker, ScriptLLM(), RULE)
            generated._LAST_TRY.clear()
            generated._IN_FLIGHT.add(RULE)
            busy = await replenish(maker, ScriptLLM(), RULE)
            return first, second, busy
        finally:
            await engine.dispose()

    first, second, busy = asyncio.run(go())
    assert len(first.accepted) == 3 and second.skipped == "tried a moment ago" and busy.skipped == "already being written"


def test_replenish_respects_the_pool_and_daily_limits(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def go(limit_name: str, value: int):
        monkeypatch.setattr(settings, limit_name, value)
        engine, maker = await _maker(db_path)
        try:
            await replenish(maker, ScriptLLM(), RULE)  # 3 stored
            generated._LAST_TRY.clear()
            llm = ScriptLLM()
            report = await replenish(maker, llm, RULE)
            return report, llm.calls["batch"]
        finally:
            await engine.dispose()

    report, batches = asyncio.run(go("exercises_max_generated_per_rule", 3))
    assert report.skipped == "the pool of this rule is full" and batches == 0


def test_replenish_daily_limit(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def go():
        monkeypatch.setattr(settings, "exercises_daily_generation_limit", 3)
        engine, maker = await _maker(db_path)
        try:
            await replenish(maker, ScriptLLM(), RULE)
            generated._LAST_TRY.clear()
            return await replenish(maker, ScriptLLM(), "preposition.dependent_verbs")
        finally:
            await engine.dispose()

    assert asyncio.run(go()).skipped == "the daily limit was reached"


def test_replenish_never_raises_and_stores_nothing_when_the_llm_fails(db_path: Path) -> None:
    async def go():
        engine, maker = await _maker(db_path)
        try:
            report = await replenish(maker, ScriptLLM(error=RuntimeError("quota")), RULE)
            unknown = await replenish(maker, ScriptLLM(), "not.a.rule")
            async with maker() as db:
                count = len((await db.scalars(select(GeneratedExercise))).all())
            return report, unknown, count
        finally:
            await engine.dispose()

    report, unknown, count = asyncio.run(go())
    assert report.skipped == "failed" and unknown.skipped == "unknown rule" and count == 0
    assert RULE not in generated._IN_FLIGHT, "a failure does not leave the rule locked"


# ── in the plan and the API ────────────────────────────────────────────────

def _store(db_path: Path, rule: str, kind: str, prompt: str, options: list[str], answers: list[str]) -> int:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into generated_exercises (rule_id, kind, prompt, options, answers) values (?, ?, ?, ?, ?)",
            (rule, kind, prompt, json.dumps(options), json.dumps(answers)),
        )
        return conn.execute("select max(id) from generated_exercises").fetchone()[0]


def test_generated_exercises_come_after_the_banks_when_equally_fresh() -> None:
    row = GeneratedExercise(id=5, rule_id=RULE, kind="fix", prompt="He ate a apple after lunch.", options=[], answers=["He ate an apple after lunch."])
    extra = to_exercises(row)
    assert {e.id for e in build_plan([RULE], 4, extra=extra)}.isdisjoint({"gen:5", "gen:5:speak"}), "4 bank exercises are enough"
    all_bank = {e.id: 1.0 for e in build_plan([RULE], 4)}  # the learner answered the whole bank of the rule
    again = build_plan([RULE], 2, extra=extra, last_seen=all_bank)
    assert {e.id for e in again} == {"gen:5", "gen:5:speak"} or any(e.id.startswith("gen:") for e in again)


def test_a_learner_who_answered_the_bank_gets_the_generated_exercises_and_can_check_them(client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client, "ana")
    _new_session(client)
    _remember(db_path, "ana@example.com", [RULE])
    fix_id = _store(db_path, RULE, "fix", "He ate a apple after lunch.", [], ["He ate an apple after lunch."])
    choice_id = _store(db_path, RULE, "choice", generated.CHOICE_PROMPT, ["My cousin bought an expensive watch.", "wrong one", "wrong two"], ["My cousin bought an expensive watch."])
    # the learner already answered the four exercises of the bank for this rule
    for e in client.get(f"/api/practice/exercises?rule={RULE}&size=4").json()["exercises"]:
        client.post("/api/practice/check", json={"exercise_id": e["id"], "answer": "x"}) if e["kind"] != "speak" else None
    with sqlite3.connect(db_path) as conn:
        for kind in ("choice:1", "fill:1", "fix:1", "speak:1"):
            conn.execute("insert or replace into exercise_seen (user_id, exercise_id, times) values (1, ?, 1)", (f"{RULE}:{kind}",))
    body = client.get("/api/practice/exercises?size=3").json()
    ids = {e["id"] for e in body["exercises"]}
    assert ids == {f"gen:{choice_id}", f"gen:{fix_id}", f"gen:{fix_id}:speak"}, "only unseen exercises are left, and they are the generated ones"
    assert len(client.get("/api/practice/exercises?size=4").json()["exercises"]) == 4, "with everything seen it comes back to the oldest"
    choice = next(e for e in body["exercises"] if e["kind"] == "choice")
    assert sorted(choice["options"]) == sorted(["My cousin bought an expensive watch.", "wrong one", "wrong two"])
    ok = client.post("/api/practice/check", json={"exercise_id": f"gen:{choice_id}", "answer": "My cousin bought an expensive watch."}).json()
    assert ok["correct"] is True and ok["rule"]["id"] == RULE
    fix = client.post("/api/practice/check", json={"exercise_id": f"gen:{fix_id}", "answer": "he ate an apple after lunch"}).json()
    assert fix["correct"] is True
    assert client.post("/api/practice/check", json={"exercise_id": "gen:9999", "answer": "x"}).status_code == 404
    assert client.post("/api/practice/check", json={"exercise_id": f"gen:{fix_id}:speak", "answer": "x"}).status_code == 400


def test_running_low_on_unseen_exercises_schedules_more_in_the_background(client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    async def recorder(rule_id: str) -> None:
        asked.append(rule_id)

    monkeypatch.setattr(exercises_api, "_replenish", recorder)
    monkeypatch.setattr(settings, "background_tasks_enabled", True)
    _login(client, "ana")
    _new_session(client)
    _remember(db_path, "ana@example.com", [RULE, "vocabulary.age_with_be"])
    # a fresh learner has 4 unseen exercises per rule: nothing to write yet
    client.get("/api/practice/exercises")
    assert asked == []
    with sqlite3.connect(db_path) as conn:
        for kind in ("choice:1", "fill:1", "fix:1"):  # 1 left for article.a_an (< low water of 2)
            conn.execute("insert into exercise_seen (user_id, exercise_id, times) values (1, ?, 1)", (f"{RULE}:{kind}",))
    client.get("/api/practice/exercises")
    assert asked == [RULE]
    # switched off: it never asks
    asked.clear()
    monkeypatch.setattr(settings, "exercises_generation_enabled", False)
    client.get("/api/practice/exercises")
    assert asked == []
