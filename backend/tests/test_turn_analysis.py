"""Background turn analysis: fluency from known timings, retries, failures and never analysing twice.

No call to Gemini or Groq: the LLM is scripted.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analysis import runner
from app.analysis.fluency import analyze_fluency
from app.analysis.grammar import MIN_CONFIDENCE, TurnGrammarAnalysis
from app.config import settings
from app.conversation.deps import get_stt_provider, get_tts_provider
from app.llm.errors import LLMAuthError, LLMProviderError, LLMRateLimitError
from app.llm.factory import get_llm_provider
from app.main import app
from app.stt import WordTiming
from tests.analysis_helpers import ScriptedGrammarLLM, err, rate_limited, run_analyses
from tests.fakes import FakeSTT, FakeTTS
from tests.test_sessions_api import AUDIO, _login, _new_session, _query


def _w(word: str, start: float, end: float) -> WordTiming:
    return WordTiming(word=word, start=start, end=end)


# --- fluency (plain code) -------------------------------------------------------------------------


def test_fluency_with_known_timings() -> None:
    # 6 words from 0.0 to 4.0 s = 90 wpm; one 1.7 s gap before "the"; one "um" and one "Uh,".
    words = [_w("I", 0.0, 0.3), _w("um", 0.4, 0.8), _w("went", 0.9, 1.3), _w("Uh,", 1.4, 1.6), _w("the", 3.3, 3.6), _w("beach", 3.7, 4.0)]

    result = analyze_fluency(words)

    assert result["metrics"] == {
        "words_per_minute": {"status": "ok", "value": 90.0},
        "long_pauses": {"status": "ok", "value": 1},
        "filler_words": {"status": "ok", "value": 2},
    }
    assert result["total_words"] == 6 and result["speaking_seconds"] == 4.0


@pytest.mark.parametrize("words", [None, []])
def test_fluency_without_word_timings_is_unavailable_not_invented(words: list | None) -> None:
    result = analyze_fluency(words)

    assert result["speaking_seconds"] is None
    assert all(m == {"status": "unavailable"} for m in result["metrics"].values())


# --- grammar schema --------------------------------------------------------------------------------


def test_grammar_schema_is_closed_and_confidence_is_bounded() -> None:
    TurnGrammarAnalysis.model_validate({"errors": [err("a", "b")]})
    with pytest.raises(ValidationError):
        TurnGrammarAnalysis.model_validate({"errors": [err("a", "b", error_type="made up type")]})
    with pytest.raises(ValidationError):
        TurnGrammarAnalysis.model_validate({"errors": [err("a", "b", confidence=1.5)]})


# --- runner ---------------------------------------------------------------------------------------


def _saved_turn(client: TestClient, db_path: Path) -> int:
    session_id = _new_session(client)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path, word_timestamps)"
            " values (?, 1, 'I goed home', 'ok', 'z', ?)",
            (session_id, '[{"word": "I", "start": 0.0, "end": 0.3}, {"word": "goed", "start": 0.4, "end": 0.8}]'),
        )
    return session_id


def _analyses(db_path: Path) -> dict[str, tuple]:
    rows = _query(db_path, "select dimension, status, result, error from turn_analyses order by dimension")
    return {r[0]: r for r in rows}


def test_low_confidence_errors_are_not_kept(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _saved_turn(client, db_path)
    llm = ScriptedGrammarLLM()
    llm.script = [[err("goed", "went", confidence=MIN_CONFIDENCE), err("home", "the home", confidence=MIN_CONFIDENCE - 0.01)]]

    run_analyses(db_path, llm)

    result = json.loads(_analyses(db_path)["grammar"][2])
    assert [e["original"] for e in result["errors"]] == ["goed"]  # exactly at the threshold is kept
    assert result["discarded_low_confidence"] == 1


def test_429_is_retried_with_growing_waits_and_then_succeeds(
    client: TestClient, db_path: Path, backoff_waits: list[float]
) -> None:
    _login(client, "ana")
    _saved_turn(client, db_path)
    llm = ScriptedGrammarLLM()
    llm.script = [LLMRateLimitError("429"), LLMProviderError("503"), [err("goed", "went")]]

    run_analyses(db_path, llm)

    assert len(llm.prompts) == 3
    assert backoff_waits == [2.0, 6.0]  # growing waits, one per failed attempt
    assert _analyses(db_path)["grammar"][1] == "done"


def test_a_definitive_failure_marks_the_turn_failed_and_keeps_the_fluency(
    client: TestClient, db_path: Path, backoff_waits: list[float]
) -> None:
    _login(client, "ana")
    _saved_turn(client, db_path)
    llm = ScriptedGrammarLLM()
    llm.script = rate_limited()

    run_analyses(db_path, llm)  # must not raise

    rows = _analyses(db_path)
    assert rows["grammar"][1] == "failed" and rows["grammar"][2] is None and rows["grammar"][3] == "ai_busy"
    assert rows["fluency"][1] == "done"
    assert backoff_waits == [2.0, 6.0, 18.0] and len(llm.prompts) == 4


def test_a_bad_api_key_is_not_retried(client: TestClient, db_path: Path, backoff_waits: list[float]) -> None:
    _login(client, "ana")
    _saved_turn(client, db_path)
    llm = ScriptedGrammarLLM()
    llm.script = [LLMAuthError("no key")]

    run_analyses(db_path, llm)

    assert _analyses(db_path)["grammar"][1] == "failed" and backoff_waits == [] and len(llm.prompts) == 1


def test_a_turn_is_never_analysed_twice(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _saved_turn(client, db_path)
    llm = ScriptedGrammarLLM()
    llm.script = [[err("goed", "went")], [err("home", "house")]]

    run_analyses(db_path, llm)
    run_analyses(db_path, llm)  # same turn again: its rows are done, nothing is queued or called

    assert len(llm.prompts) == 1
    assert _query(db_path, "select count(*) from turn_analyses") == [(2,)]  # unique (turn, dimension)


def test_the_llm_slot_is_free_after_a_run(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _saved_turn(client, db_path)
    llm = ScriptedGrammarLLM()
    llm.script = rate_limited()

    run_analyses(db_path, llm)

    # One LLM call at a time, and never held while waiting to retry or after giving up.
    assert runner._LLM_SLOT.acquire(blocking=False)
    runner._LLM_SLOT.release()


# --- wiring in the turn endpoint ------------------------------------------------------------------


class _TutorAndAnalyst:
    """Tutor replies for the conversation, the scripted grammar answers for the analysis."""

    def __init__(self, grammar: ScriptedGrammarLLM) -> None:
        self._grammar = grammar

    def generate(self, prompt: str, response_model: type, *, system: str | None = None):  # type: ignore[no-untyped-def]
        if "errors" in response_model.model_fields:
            return self._grammar.generate(prompt, response_model)
        return response_model(reply="That sounds fun!")


def test_creating_a_turn_queues_and_runs_the_analysis_after_saving(
    client: TestClient, tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    calls: list[str] = []
    grammar = ScriptedGrammarLLM()
    grammar.script = [[err("goed", "went")]]
    app.dependency_overrides[get_stt_provider] = lambda: FakeSTT(calls, text="I goed home")
    app.dependency_overrides[get_tts_provider] = lambda: FakeTTS(calls)
    app.dependency_overrides[get_llm_provider] = lambda: _TutorAndAnalyst(grammar)
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == 201
    rows = _analyses(db_path)
    assert rows["grammar"][1] == "done" and rows["fluency"][1] == "done"
    assert calls == ["stt", "tts"]  # the tutor LLM is not in this list: only the pipeline fakes record


def test_a_failed_turn_leaves_no_analysis_rows(
    client: TestClient, tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    calls: list[str] = []
    app.dependency_overrides[get_stt_provider] = lambda: FakeSTT(calls, error=LLMProviderError("boom"))
    app.dependency_overrides[get_tts_provider] = lambda: FakeTTS(calls)
    app.dependency_overrides[get_llm_provider] = lambda: ScriptedGrammarLLM()
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code >= 400
    assert _query(db_path, "select count(*) from turns") == [(0,)]
    assert _query(db_path, "select count(*) from turn_analyses") == [(0,)]
