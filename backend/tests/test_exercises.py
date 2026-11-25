"""Personalised practice (RAG 3): the exercise bank, checking answers, the plan and the API.

Nothing here calls a real service: the speech-to-text is simulated and the audio length faked.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import exercises_api
from app.conversation.deps import get_stt_provider
from app.exercises import ExerciseError, build_plan, check_text, exercises_by_id, load_exercises, speech_matches
from app.exercises import bank
from app.exercises.plan import KIND_ROTATION
from app.main import app
from app.rag.corpus import load_rules
from app.stt.errors import NoSpeechError
from tests.fakes import FakeSTT
from tests.test_sessions_api import _login, _new_session

WAV = {"audio": ("say.wav", b"RIFFfake", "audio/wav")}


# ── the bank ────────────────────────────────────────────────────────────────

def test_every_rule_of_the_corpus_has_exercises_of_every_main_kind() -> None:
    by_rule: dict[str, set[str]] = {}
    for e in load_exercises():
        by_rule.setdefault(e.rule_id, set()).add(e.kind)
    assert set(by_rule) == {r.id for r in load_rules()}
    for rule_id, kinds in by_rule.items():
        assert {"choice", "fix", "speak"} <= kinds, rule_id
    # at least 4 kinds of exercise exist in the bank, and most rules have all of them
    assert sum(1 for kinds in by_rule.values() if len(kinds) == 4) >= 50


def test_bank_exercises_are_well_formed() -> None:
    ids = [e.id for e in load_exercises()]
    assert len(ids) == len(set(ids))
    for e in load_exercises():
        assert e.answers and all(a.strip() for a in e.answers)
        if e.kind == "choice":
            assert len(e.options) == 3 and e.answers[0] == e.options[0]
        if e.kind == "fill":
            assert "___" in e.prompt
        if e.kind in ("fix", "speak"):
            assert e.prompt not in e.answers or e.kind == "speak"
        if e.kind == "speak":
            assert e.wrong and e.wrong != e.answers[0]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("rule: nonsense.rule\nchoice: Q | a | b | c\nfix: x | y", "unknown rule"),
        ("rule: article.a_an\nchoice: Q | a | b\nfix: x | y", "choice ="),
        ("rule: article.a_an\nchoice: Q | a | b | c\nfill: no gap | a\nfix: x | y", "fill ="),
        ("rule: article.a_an\nfill: gap ___ | a\nfix: x | y", "no choice"),
        ("rule: article.a_an\nchoice: Q | a | b | c\nfix: same | same", "also an accepted answer"),
        ("rule: article.a_an\nchoice: Q | a | b | c\nquiz: x | y", "unknown field"),
    ],
)
def test_malformed_blocks_are_rejected(text: str, message: str) -> None:
    with pytest.raises(ExerciseError, match=message):
        bank._parse_block(text, "test")


# ── checking ────────────────────────────────────────────────────────────────

def test_written_answers_ignore_case_spacing_punctuation_and_apostrophes() -> None:
    fix = exercises_by_id()["subject_verb_agreement.do_does:fix:1"]  # He don't like coffee. -> He doesn't like coffee.
    assert check_text(fix, "he DOESN'T  like coffee")
    assert check_text(fix, "He doesn’t like coffee.")  # typographic apostrophe
    assert not check_text(fix, "He don't like coffee.")
    assert not check_text(fix, "")


def test_several_accepted_answers() -> None:
    fix = exercises_by_id()["vocabulary.age_with_be:fix:1"]
    assert check_text(fix, "She is twenty years old.") and check_text(fix, "she is twenty")
    fill = exercises_by_id()["pronoun.who_which_relative:fill:1"]
    assert check_text(fill, "that") and check_text(fill, "which") and not check_text(fill, "who")


def test_speech_must_be_the_corrected_sentence_not_the_mistake() -> None:
    say = exercises_by_id()["vocabulary.age_with_be:speak:1"]  # say: She is twenty years old. (wrong: She has twenty years.)
    assert speech_matches(say, "She is twenty years old.")
    assert speech_matches(say, "she's twenty years old")  # contraction written by the speech-to-text
    assert not speech_matches(say, "She has twenty years")  # repeating the mistake
    assert not speech_matches(say, "")
    assert not speech_matches(say, "I like pizza")


# ── the plan ────────────────────────────────────────────────────────────────

def test_plan_starts_with_the_most_frequent_rules_and_mixes_the_kinds() -> None:
    ranked = ["article.a_an", "vocabulary.age_with_be", "preposition.dependent_verbs", "verb_form.make_do"]
    plan = build_plan(ranked, 4)
    assert [e.rule_id for e in plan] == ranked
    assert [e.kind for e in plan] == list(KIND_ROTATION)


def test_plan_with_few_rules_comes_back_to_them_without_repeating_exercises() -> None:
    plan = build_plan(["article.a_an", "vocabulary.age_with_be"], 8)
    assert len(plan) == 8
    assert len({e.id for e in plan}) == 8
    assert {e.rule_id for e in plan} == {"article.a_an", "vocabulary.age_with_be"}
    assert len({e.kind for e in plan}) == 4


def test_plan_stops_when_there_is_nothing_more_to_give() -> None:
    assert len(build_plan(["article.a_an"], 20)) == 4
    assert build_plan([], 8) == []
    assert build_plan(["not.a.rule"], 8) == []


# ── the API ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def short_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exercises_api, "measure_seconds", lambda path: 2.0)


@pytest.fixture
def whisper() -> dict:
    heard = {"text": "She is twenty years old."}

    def stt() -> FakeSTT:
        error = heard["text"] if isinstance(heard["text"], Exception) else None
        return FakeSTT([], text="" if error else heard["text"], error=error)

    app.dependency_overrides[get_stt_provider] = stt
    return heard


def _remember(db_path: Path, user_email: str, rules: list[str]) -> None:
    """Put mistakes of those rules in the learner's memory (one row per item)."""
    with sqlite3.connect(db_path) as conn:
        user_id = conn.execute('select id from "user" where email = ?', (user_email,)).fetchone()[0]
        session_id = conn.execute("select max(id) from sessions").fetchone()[0]
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path) values (?, 1, 'x', 'y', 'z')",
            (session_id,),
        )
        turn_id = conn.execute("select max(id) from turns").fetchone()[0]
        for rule_id in rules:
            conn.execute(
                "insert into error_events (user_id, session_id, turn_id, error_type, rule_id, original, correction, embedding)"
                " values (?, ?, ?, 'other', ?, 'a', 'b', ?)",
                (user_id, session_id, turn_id, rule_id, json.dumps([0.0])),
            )


def test_exercises_need_a_login(client: TestClient) -> None:
    assert client.get("/api/practice/exercises").status_code == 401
    assert client.post("/api/practice/check", json={"exercise_id": "x", "answer": "y"}).status_code == 401


def test_a_learner_with_no_mistakes_gets_an_empty_session(client: TestClient) -> None:
    _login(client, "newbie")
    body = client.get("/api/practice/exercises").json()
    assert body == {"exercises": [], "focus": []}


def test_the_session_is_built_from_the_learners_own_rules_worst_first(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _new_session(client)
    _remember(db_path, "ana@example.com", ["article.a_an"] + ["vocabulary.age_with_be"] * 3 + ["verb_form.make_do"] * 2)
    body = client.get("/api/practice/exercises?size=6").json()
    assert [f["rule_id"] for f in body["focus"]] == ["vocabulary.age_with_be", "verb_form.make_do", "article.a_an"]
    assert [f["count"] for f in body["focus"]] == [3, 2, 1]
    assert len(body["exercises"]) == 6
    assert len({e["kind"] for e in body["exercises"]}) >= 3, "the kinds are mixed"
    first = body["exercises"][0]
    assert first["rule_id"] == "vocabulary.age_with_be" and first["rule_title"]
    # the answers never travel with the exercise
    assert "answers" not in first and "answer" not in first and "wrong" not in first
    choice = next(e for e in body["exercises"] if e["kind"] == "choice")
    assert len(choice["options"]) == 3


def test_one_rule_can_be_practised_by_hand(client: TestClient) -> None:
    _login(client, "ana")
    body = client.get("/api/practice/exercises?rule=article.a_an&size=4").json()
    assert {e["rule_id"] for e in body["exercises"]} == {"article.a_an"}
    assert client.get("/api/practice/exercises?rule=nope").status_code == 404
    assert client.get("/api/practice/exercises?size=99").status_code == 422


def test_check_gives_the_verdict_the_answer_and_the_rule(client: TestClient) -> None:
    _login(client, "ana")
    ok = client.post("/api/practice/check", json={"exercise_id": "article.a_an:fill:1", "answer": "An"})
    assert ok.status_code == 200
    assert ok.json()["correct"] is True and ok.json()["expected"] == "an"
    assert ok.json()["rule"]["id"] == "article.a_an" and ok.json()["rule"]["rule_es"]
    bad = client.post("/api/practice/check", json={"exercise_id": "article.a_an:fill:1", "answer": "a"}).json()
    assert bad["correct"] is False and bad["expected"] == "an"


def test_check_refuses_unknown_and_spoken_exercises(client: TestClient) -> None:
    _login(client, "ana")
    assert client.post("/api/practice/check", json={"exercise_id": "nope:fill:1", "answer": "a"}).status_code == 404
    spoken = client.post("/api/practice/check", json={"exercise_id": "article.a_an:speak:1", "answer": "a"})
    assert spoken.status_code == 400 and spoken.json()["detail"]["code"] == "use_speak"


def test_speak_accepts_the_corrected_sentence(client: TestClient, whisper: dict) -> None:
    _login(client, "ana")
    res = client.post("/api/practice/speak", data={"exercise_id": "vocabulary.age_with_be:speak:1"}, files=WAV)
    assert res.status_code == 200, res.text
    assert res.json()["correct"] is True and res.json()["heard"] == "She is twenty years old."
    assert res.json()["expected"] == "She is twenty years old."


def test_speak_does_not_accept_the_mistake_or_silence(client: TestClient, whisper: dict) -> None:
    _login(client, "ana")
    url, data = "/api/practice/speak", {"exercise_id": "vocabulary.age_with_be:speak:1"}
    whisper["text"] = "She has twenty years"
    assert client.post(url, data=data, files=WAV).json()["correct"] is False
    whisper["text"] = NoSpeechError("silence")
    silent = client.post(url, data=data, files=WAV).json()
    assert silent["correct"] is False and silent["heard"] == ""


def test_speak_refuses_the_wrong_kind_format_and_long_audio(client: TestClient, whisper: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client, "ana")
    url = "/api/practice/speak"
    assert client.post(url, data={"exercise_id": "article.a_an:fill:1"}, files=WAV).status_code == 400
    assert client.post(url, data={"exercise_id": "nope:speak:1"}, files=WAV).status_code == 404
    bad_format = {"audio": ("say.txt", b"x", "text/plain")}
    assert client.post(url, data={"exercise_id": "article.a_an:speak:1"}, files=bad_format).status_code == 415
    monkeypatch.setattr(exercises_api, "measure_seconds", lambda path: 99.0)
    assert client.post(url, data={"exercise_id": "article.a_an:speak:1"}, files=WAV).status_code == 413


def test_speak_does_not_nudge_the_recognizer_towards_the_answer(client: TestClient) -> None:
    fake = FakeSTT([], text="She is twenty years old.")
    app.dependency_overrides[get_stt_provider] = lambda: fake
    _login(client, "ana")
    client.post("/api/practice/speak", data={"exercise_id": "vocabulary.age_with_be:speak:1"}, files=WAV)
    assert fake.contexts == [None], "no context: it must hear what was said, not what we want to hear"
