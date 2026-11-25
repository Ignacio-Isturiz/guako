"""GET /api/sessions/{id}/report. The LLM is scripted: no call to Gemini or Groq."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm.errors import LLMProviderError, LLMRateLimitError
from app.llm.factory import get_llm_provider
from app.main import app
from app.reports import LONG_PAUSE_SECONDS, compute_fluency
from app.stt import WordTiming
from tests.analysis_helpers import ScriptedGrammarLLM, err, rate_limited, run_analyses


@pytest.fixture
def llm() -> Iterator[ScriptedGrammarLLM]:
    scripted = ScriptedGrammarLLM()
    app.dependency_overrides[get_llm_provider] = lambda: scripted
    yield scripted


def _login(client: TestClient, name: str) -> None:
    creds = {"username": name, "email": f"{name}@example.com", "password": "Passw0rd123"}
    assert client.post("/api/auth/register", json=creds).status_code == 201
    login = client.post("/api/auth/login", data={"username": creds["email"], "password": creds["password"]})
    assert login.status_code == 204


def _new_session(client: TestClient) -> int:
    return client.post("/api/sessions", json={"level": "B1", "topic": "Travel"}).json()["id"]


def _words(*items: tuple[str, float, float]) -> str:
    return json.dumps([{"word": w, "start": s, "end": e, "confidence": None} for w, s, e in items])


def _add_turn(db_path: Path, session_id: int, number: int, transcript: str, words: str | None) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path,"
            " word_timestamps) values (?, ?, ?, 'ok', 'z', ?)",
            (session_id, number, transcript, words),
        )


def _end(client: TestClient, session_id: int) -> None:
    assert client.patch(f"/api/sessions/{session_id}", json={"ended": True}).status_code == 200


def test_report_of_an_active_session_is_409(client: TestClient, llm: ScriptedGrammarLLM) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.get(f"/api/sessions/{session_id}/report")

    assert res.status_code == 409 and res.json()["detail"]["code"] == "session_not_ended"
    assert llm.prompts == []


def test_report_of_someone_elses_session_is_404(client: TestClient, llm: ScriptedGrammarLLM) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _end(client, session_id)
    client.post("/api/auth/logout")
    _login(client, "bob")

    assert client.get(f"/api/sessions/{session_id}/report").status_code == 404
    assert client.get("/api/sessions/9999/report").status_code == 404
    assert llm.prompts == []


def test_report_requires_login(client: TestClient, llm: ScriptedGrammarLLM) -> None:
    assert client.get("/api/sessions/1/report").status_code == 401


def test_session_without_user_turns_gets_an_explicit_empty_report(client: TestClient, llm: ScriptedGrammarLLM) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _end(client, session_id)

    res = client.get(f"/api/sessions/{session_id}/report")

    assert res.status_code == 200
    body = res.json()
    assert body["user_turns"] == 0
    assert body["grammar"]["status"] == "empty" and body["grammar"]["score"] is None and body["grammar"]["errors"] == []
    assert body["fluency"]["status"] == "empty" and body["fluency"]["score"] is None
    assert llm.prompts == []  # nothing to analyse, no LLM call


def test_full_report(client: TestClient, llm: ScriptedGrammarLLM, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    # Turn 1: 6 words, one filler ("um"), one 1.5 s pause before "the". Spans 0.0 -> 3.0 s.
    _add_turn(
        db_path,
        session_id,
        1,
        "I goed to um the beach",
        _words(
            ("I", 0.0, 0.3), ("goed", 0.4, 0.8), ("to", 0.9, 1.1), ("um", 1.2, 1.5), ("the", 3.0, 3.3), ("beach", 3.4, 4.0)
        ),
    )
    # Turn 2: 3 words in 1.0 s.
    _add_turn(db_path, session_id, 2, "It was fun", _words(("It", 0.0, 0.3), ("was", 0.4, 0.7), ("fun", 0.8, 1.0)))
    llm.script = [[err("goed", "went"), err("beach", "the beach", confidence=0.4)], []]  # 0.4 is below the threshold
    run_analyses(db_path, llm)
    _end(client, session_id)

    res = client.get(f"/api/sessions/{session_id}/report")

    assert res.status_code == 200, res.text
    body = res.json()
    print(json.dumps(body, indent=2))
    assert body["user_turns"] == 2
    assert body["grammar"] == {
        "status": "ok",
        "score": 89,  # 1 error in 9 words
        "errors": [
            {
                "turn_number": 1,
                "original": "goed",
                "correction": "went",
                "error_type": "verb_tense",
                "explanation": "Use the past.",
                "rule": None,  # the RAG is off in tests (SQLite)
                "seen_before": 0,  # the memory is off in tests (SQLite)
            }
        ],
        "turns_analyzed": 2,
        "turns_failed": 0,
        "turns_pending": 0,
    }
    fluency = body["fluency"]
    assert fluency["status"] == "ok"
    assert (fluency["total_words"], fluency["long_pauses"], fluency["filler_words"]) == (9, 1, 1)
    assert fluency["words_per_minute"] == pytest.approx(108.0)  # 9 words in 5 s of speech
    assert 0 <= fluency["score"] <= 100
    # These turns have no stored audio: pronunciation is explained, not left "pending" forever.
    assert body["pronunciation"]["status"] == "unavailable" and body["pronunciation"]["reason"] == "no_audio_consent"
    assert body["pronunciation"]["score"] is None and body["pronunciation"]["turns_without_audio"] == 2
    # The judge scores both from 1 to 5; the report shows 0-100 = (score - 1) / 4 * 100.
    assert (body["communication"]["status"], body["communication"]["score"], body["communication"]["turns_judged"]) == ("ok", 75, 2)
    # Listening needs Guako's previous message: turn 1 has none (no opening here), so only turn 2 is judged.
    assert (body["listening"]["status"], body["listening"]["score"], body["listening"]["turns_judged"]) == ("ok", 100, 1)
    assert body["listening"]["turns_without_context"] == 1


@pytest.mark.parametrize("failure", [LLMRateLimitError("429"), LLMProviderError("503")])
def test_failed_grammar_analysis_makes_grammar_incomplete_not_the_whole_report(
    client: TestClient, llm: ScriptedGrammarLLM, db_path: Path, failure: Exception
) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _add_turn(db_path, session_id, 1, "I goed home", _words(("I", 0.0, 0.3), ("goed", 0.4, 0.8), ("home", 0.9, 1.2)))
    _add_turn(db_path, session_id, 2, "It was fun", _words(("It", 0.0, 0.3), ("was", 0.4, 0.7), ("fun", 0.8, 1.0)))
    llm.script = [failure] * 4 + [[]]  # turn 1 fails on the first try and on the 3 retries
    run_analyses(db_path, llm)
    _end(client, session_id)

    res = client.get(f"/api/sessions/{session_id}/report")

    assert res.status_code == 200
    grammar = res.json()["grammar"]
    assert grammar["status"] == "incomplete"
    assert (grammar["turns_analyzed"], grammar["turns_failed"]) == (1, 1)
    assert grammar["score"] == 100  # scored over the analysed turn only
    assert res.json()["fluency"]["status"] == "ok"  # fluency does not depend on the LLM


def test_every_analysis_failing_leaves_no_grammar_score(client: TestClient, llm: ScriptedGrammarLLM, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _add_turn(db_path, session_id, 1, "I goed home", None)
    llm.script = rate_limited()
    run_analyses(db_path, llm)
    _end(client, session_id)

    body = client.get(f"/api/sessions/{session_id}/report").json()

    assert body["grammar"]["status"] == "incomplete" and body["grammar"]["score"] is None
    assert body["fluency"]["status"] == "empty"  # no word timings stored for that turn
    assert body["fluency"]["unavailable"] == ["words_per_minute", "long_pauses", "filler_words"]
    assert body["fluency"]["turns_without_timings"] == 1


def _w(word: str, start: float, end: float) -> WordTiming:
    return WordTiming(word=word, start=start, end=end)


def test_fluency_pause_threshold_and_filler_normalisation() -> None:
    just_under = LONG_PAUSE_SECONDS - 0.01
    words = [_w("Well,", 0.0, 0.5), _w("UM", 0.5 + just_under, 1.5), _w("yes", 1.5 + LONG_PAUSE_SECONDS, 3.0)]

    report = compute_fluency([words])

    assert report.long_pauses == 1  # only the gap that reaches the threshold
    assert report.filler_words == 1  # "UM" counts, case ignored


def test_fluency_score_is_perfect_for_fast_clean_speech_and_clamped_for_bad_speech() -> None:
    fast = [_w(f"w{i}", i * 0.4, i * 0.4 + 0.3) for i in range(20)]  # ~152 wpm, no pauses, no fillers
    assert compute_fluency([fast]).score == 100

    awful = [_w("um", 0.0, 0.5), _w("uh", 5.0, 5.5), _w("eh", 10.0, 10.5)]
    score = compute_fluency([awful]).score
    assert score is not None and 0 <= score < 20


def _two_turn_session(client: TestClient, db_path: Path) -> int:
    session_id = _new_session(client)
    _add_turn(db_path, session_id, 1, "I goed home", _words(("I", 0.0, 0.3), ("goed", 0.4, 0.8), ("home", 0.9, 1.2)))
    _add_turn(db_path, session_id, 2, "It was fun", _words(("It", 0.0, 0.3), ("was", 0.4, 0.7), ("fun", 0.8, 1.0)))
    _end(client, session_id)
    return session_id


def test_a_complete_report_is_saved_and_not_rebuilt(client: TestClient, llm: ScriptedGrammarLLM, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _two_turn_session(client, db_path)
    llm.script = [[err("goed", "went")], []]
    run_analyses(db_path, llm)

    first = client.get(f"/api/sessions/{session_id}/report")
    second = client.get(f"/api/sessions/{session_id}/report")  # the script is empty: a rebuild would crash

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(llm.prompts) == 2  # one call per turn; building the report never calls the LLM
    assert sqlite3.connect(db_path).execute("select report is not null from sessions").fetchone() == (1,)


def test_an_incomplete_report_is_not_saved(client: TestClient, llm: ScriptedGrammarLLM, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _two_turn_session(client, db_path)
    llm.script = [*rate_limited(), []]
    run_analyses(db_path, llm)

    body = client.get(f"/api/sessions/{session_id}/report").json()

    assert body["grammar"]["status"] == "incomplete" and body["grammar"]["turns_failed"] == 1
    assert sqlite3.connect(db_path).execute("select report is null from sessions").fetchone() == (1,)


def test_turns_without_analysis_are_queued_and_the_report_is_pending_until_they_finish(
    client: TestClient, llm: ScriptedGrammarLLM, db_path: Path
) -> None:
    """Sessions saved before the analysis existed: the first read queues them, the next one is complete."""
    _login(client, "ana")
    session_id = _two_turn_session(client, db_path)
    llm.script = [[err("goed", "went")], []]

    first = client.get(f"/api/sessions/{session_id}/report").json()  # the background task runs after this answer
    second = client.get(f"/api/sessions/{session_id}/report").json()

    assert first["grammar"]["status"] == "incomplete" and first["grammar"]["turns_pending"] == 2
    assert second["grammar"]["status"] == "ok" and second["grammar"]["turns_analyzed"] == 2


def test_sessions_list_shows_saved_scores_only(client: TestClient, llm: ScriptedGrammarLLM, db_path: Path) -> None:
    _login(client, "ana")
    analysed = _two_turn_session(client, db_path)
    llm.script = [[err("goed", "went")], []]
    run_analyses(db_path, llm)
    report = client.get(f"/api/sessions/{analysed}/report").json()
    other = _new_session(client)
    _add_turn(db_path, other, 1, "Hello there", None)

    by_id = {s["id"]: s for s in client.get("/api/sessions").json()}

    assert by_id[analysed]["grammar_score"] == report["grammar"]["score"]
    assert by_id[analysed]["fluency_score"] == report["fluency"]["score"]
    assert by_id[other]["grammar_score"] is None and by_id[other]["fluency_score"] is None


def test_the_report_ignores_gukos_opening(client: TestClient, llm: ScriptedGrammarLLM, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _add_turn(db_path, session_id, 0, "", None)  # Guako's opening: no learner part
    _add_turn(db_path, session_id, 1, "I goed home", _words(("I", 0.0, 0.3), ("goed", 0.4, 0.8), ("home", 0.9, 1.2)))
    llm.script = [[err("goed", "went")]]  # one LLM call only: the opening has no learner text
    run_analyses(db_path, llm)
    _end(client, session_id)

    body = client.get(f"/api/sessions/{session_id}/report").json()

    assert body["user_turns"] == 1
    assert body["grammar"]["turns_analyzed"] == 1 and body["grammar"]["errors"][0]["turn_number"] == 1
