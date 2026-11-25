"""Personalised practice, layers 1 and 3: the learner's own sentences as exercises, and not repeating what was answered.

The bank, checking and the plain API are in test_exercises.py (its fixtures and helpers are reused here).
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.exercises import build_plan, load_exercises, personal
from tests.test_exercises import WAV, _remember, short_audio, whisper  # noqa: F401  (fixtures + helpers)
from tests.test_sessions_api import _login, _new_session


# ── layer 1: the learner's own sentences ───────────────────────────────────

def test_a_mistake_is_put_back_into_the_sentence_it_was_said_in() -> None:
    said = "Hello. I am boring in the class today. It was long."
    assert personal.fix_sentence(said, "boring", "bored") == ("I am boring in the class today.", "I am bored in the class today.")
    assert personal.fix_sentence(said, "BORING", "bored")[1] == "I am bored in the class today."  # case-insensitive


@pytest.mark.parametrize(
    ("transcript", "original", "correction"),
    [
        ("I am boring in the class today.", "tired", "bored"),  # the fragment is not in the transcript
        ("Hello. So boring.", "boring", "bored"),  # the sentence is too short to be worth it
        ("I am bored in the class today.", "bored", "bored"),  # nothing changes
        ("I am boring in the class today.", "", "bored"),
    ],
)
def test_no_exercise_when_the_sentence_cannot_be_built(transcript: str, original: str, correction: str) -> None:
    assert personal.fix_sentence(transcript, original, correction) is None
    assert personal.exercises_for(1, None, transcript, original, correction) == []


def test_personal_exercises_are_a_fix_and_a_speak_with_their_own_ids() -> None:
    fix, speak = personal.exercises_for(7, "vocabulary.adjectives_ed_ing", "I am boring in the class today.", "boring", "bored")
    assert (fix.id, fix.kind, fix.personal) == ("mine:7:fix", "fix", True)
    assert fix.prompt == "I am boring in the class today." and fix.answers == ("I am bored in the class today.",)
    assert (speak.id, speak.kind) == ("mine:7:speak", "speak")
    assert speak.prompt == "I am bored in the class today." and speak.wrong == "I am boring in the class today."
    assert personal.parse_id("mine:7:fix") == (7, "fix") and personal.parse_id("mine:7:fill") is None
    assert personal.parse_id("article.a_an:fix:1") is None


def _remember_said(db_path: Path, email: str, transcript: str, original: str, correction: str, rule: str | None) -> int:
    """A turn where the learner said ``transcript`` and the analysis found this mistake; returns the event id."""
    with sqlite3.connect(db_path) as conn:
        user_id = conn.execute('select id from "user" where email = ?', (email,)).fetchone()[0]
        session_id = conn.execute("select max(id) from sessions").fetchone()[0]
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path)"
            " values (?, (select coalesce(max(turn_number), 0) + 1 from turns where session_id = ?), ?, 'y', 'z')",
            (session_id, session_id, transcript),
        )
        turn_id = conn.execute("select max(id) from turns").fetchone()[0]
        conn.execute(
            "insert into error_events (user_id, session_id, turn_id, error_type, rule_id, original, correction, embedding)"
            " values (?, ?, ?, 'vocabulary', ?, ?, ?, ?)",
            (user_id, session_id, turn_id, rule, original, correction, json.dumps([0.0])),
        )
        return conn.execute("select max(id) from error_events").fetchone()[0]


def test_the_session_includes_the_learners_own_sentences(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    event_id = _remember_said(db_path, "ana@example.com", "I am boring in the class today.", "boring", "bored", "vocabulary.adjectives_ed_ing")
    body = client.get("/api/practice/exercises?size=8").json()
    mine = [e for e in body["exercises"] if e["personal"]]
    assert {e["id"] for e in mine} == {f"mine:{event_id}:fix", f"mine:{event_id}:speak"}
    assert all(e["rule_id"] == "vocabulary.adjectives_ed_ing" for e in mine)
    fix = next(e for e in mine if e["kind"] == "fix")
    assert fix["prompt"] == "I am boring in the class today."
    assert "I am bored" not in json.dumps(fix), "the corrected sentence never travels with the exercise"
    ok = client.post("/api/practice/check", json={"exercise_id": fix["id"], "answer": "i am bored in the class today"}).json()
    assert ok["correct"] is True and ok["expected"] == "I am bored in the class today."
    assert ok["rule"]["id"] == "vocabulary.adjectives_ed_ing"


def test_a_mistake_without_a_rule_still_gives_exercises_and_no_rule_card(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    _remember_said(db_path, "ana@example.com", "She go to the market every day.", "She go", "She goes", None)
    body = client.get("/api/practice/exercises").json()
    assert [e["kind"] for e in body["exercises"]] == ["fix", "speak"]
    assert all(e["personal"] and e["rule_id"] is None and e["rule_title"] is None for e in body["exercises"])
    assert body["focus"] == []
    fix = body["exercises"][0]
    answer = client.post("/api/practice/check", json={"exercise_id": fix["id"], "answer": "She goes to the market every day."}).json()
    assert answer["correct"] is True and answer["rule"] is None


def test_personal_exercises_belong_to_their_owner(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    event_id = _remember_said(db_path, "ana@example.com", "I am boring in the class today.", "boring", "bored", None)
    client.cookies.clear()
    _login(client, "bob")
    assert client.get("/api/practice/exercises").json()["exercises"] == []
    stolen = client.post("/api/practice/check", json={"exercise_id": f"mine:{event_id}:fix", "answer": "x"})
    assert stolen.status_code == 404
    assert client.post("/api/practice/check", json={"exercise_id": "mine:999:fix", "answer": "x"}).status_code == 404


def test_one_rule_by_hand_only_uses_the_learners_sentences_of_that_rule(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    _remember_said(db_path, "ana@example.com", "I am boring in the class today.", "boring", "bored", "vocabulary.adjectives_ed_ing")
    _remember_said(db_path, "ana@example.com", "She go to the market every day.", "She go", "She goes", None)
    body = client.get("/api/practice/exercises?rule=article.a_an&size=8").json()
    assert not any(e["personal"] for e in body["exercises"])
    body = client.get("/api/practice/exercises?rule=vocabulary.adjectives_ed_ing&size=8").json()
    assert sum(e["personal"] for e in body["exercises"]) == 2


# ── layer 3: do not repeat what was already answered ───────────────────────

def test_plan_gives_unseen_exercises_first_and_the_oldest_seen_when_all_were_seen() -> None:
    rule = "article.a_an"
    ids = [e.id for e in load_exercises() if e.rule_id == rule]
    assert len(ids) == 4
    seen = {ids[0]: 100.0, ids[1]: 200.0}  # two answered, two never
    assert {e.id for e in build_plan([rule], 2, last_seen=seen)} == set(ids[2:]), "the never-answered ones come first"
    all_seen = {ids[0]: 400.0, ids[1]: 100.0, ids[2]: 300.0, ids[3]: 200.0}
    plan = build_plan([rule], 4, last_seen=all_seen)
    assert {e.id for e in plan} == set(ids), "it never runs out: everything comes back, with the four kinds"


def test_plan_prefers_the_learners_own_sentence_while_it_is_fresh() -> None:
    mine = personal.exercises_for(3, "article.a_an", "I need a umbrella today please.", "a umbrella", "an umbrella")
    assert len(mine) == 2
    plan = build_plan(["article.a_an"], 4, personal=mine)
    assert {"mine:3:fix", "mine:3:speak"} <= {e.id for e in plan}
    seen = {"mine:3:fix": 50.0, "mine:3:speak": 50.0}
    again = build_plan(["article.a_an"], 4, personal=mine, last_seen=seen)
    assert not {"mine:3:fix", "mine:3:speak"} & {e.id for e in again}, "once answered, the bank's unseen ones go first"


def test_answering_marks_the_exercise_as_seen_and_the_next_round_changes(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    _remember(db_path, "ana@example.com", ["article.a_an"])
    first = client.get("/api/practice/exercises?size=2").json()["exercises"]
    assert [e["kind"] for e in first] == ["choice", "fill"]
    for e in first:
        assert client.post("/api/practice/check", json={"exercise_id": e["id"], "answer": "x"}).status_code == 200
    with sqlite3.connect(db_path) as conn:
        assert {r[0] for r in conn.execute("select exercise_id from exercise_seen")} == {e["id"] for e in first}
    second = {e["id"] for e in client.get("/api/practice/exercises?size=2").json()["exercises"]}
    assert not second & {e["id"] for e in first}, "what was just answered does not come back while there is something unseen"
    client.post("/api/practice/check", json={"exercise_id": first[0]["id"], "answer": "x"})  # again: counts, does not fail
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select times from exercise_seen where exercise_id = ?", (first[0]["id"],)).fetchone()[0] == 2


def test_asking_for_exercises_does_not_mark_them_as_seen(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    _remember(db_path, "ana@example.com", ["article.a_an"])
    a = [e["id"] for e in client.get("/api/practice/exercises?size=4").json()["exercises"]]
    b = [e["id"] for e in client.get("/api/practice/exercises?size=4").json()["exercises"]]
    assert a == b, "leaving a round half way does not use up its exercises"


def test_spoken_answers_are_marked_as_seen_too(client: TestClient, db_path: Path, whisper: dict) -> None:  # noqa: F811
    _login(client, "ana")
    client.post("/api/practice/speak", data={"exercise_id": "vocabulary.age_with_be:speak:1"}, files=WAV)
    with sqlite3.connect(db_path) as conn:
        assert [r[0] for r in conn.execute("select exercise_id from exercise_seen")] == ["vocabulary.age_with_be:speak:1"]
