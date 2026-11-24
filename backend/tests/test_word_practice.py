"""Word practice ("now you say it"): pass locks the word, two scored tries, silence, quota, access rules.

No Azure: the provider is scripted and the audio length is faked.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import practice_api
from app.conversation.deps import get_pronunciation_provider, get_stt_provider
from app.stt.errors import NoSpeechError, STTError
from app.llm.factory import get_llm_provider
from app.main import app
from app.practice import PRACTICE_MAX_ATTEMPTS, PRACTICE_MAX_CALLS, PRACTICE_PASS_SCORE
from app.pronunciation import PronunciationResult, WordScore
from app.pronunciation.errors import PronunciationNoSpeechError, PronunciationRateLimitError
from app.pronunciation.quota import USABLE_MONTHLY_SECONDS, month_key
from tests.analysis_helpers import ScriptedGrammarLLM, ScriptedPronunciation
from tests.fakes import FakeSTT
from tests.test_sessions_api import _login, _new_session, _query

WAV = {"audio": ("word.wav", b"RIFFfake", "audio/wav")}
BEACH_PHONEMES = [
    {"phoneme": "b", "ipa": "b", "accuracy": 66.0},
    {"phoneme": "iy", "ipa": "i", "accuracy": 4.0},
    {"phoneme": "ch", "ipa": "tʃ", "accuracy": 24.0},
]


def _heard(score: float, word: str = "beach") -> PronunciationResult:
    phonemes = [{"phoneme": "iy", "ipa": "i", "accuracy": score}]
    return PronunciationResult(accuracy_score=score, pron_score=score, words=[WordScore(word=word, accuracy=score, phonemes=phonemes)])


@pytest.fixture(autouse=True)
def short_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(practice_api, "measure_seconds", lambda path: 1.5)


@pytest.fixture(autouse=True)
def whisper() -> dict:
    """Whisper is simulated too (never Groq): by default it hears the word that was asked for.

    Change ``whisper["text"]`` to make it hear something else, or put an exception there.
    """
    heard = {"text": "beach"}

    def stt() -> FakeSTT:
        error = heard["text"] if isinstance(heard["text"], Exception) else None
        return FakeSTT([], text="" if error else heard["text"], error=error)

    app.dependency_overrides[get_stt_provider] = stt
    return heard


def _session_with_hard_word(client: TestClient, db_path: Path, *, consent: bool = True, ended: bool = True) -> int:
    """An ended session whose only turn has "beach" scored 14: the hard word to practice."""
    session_id = _new_session(client)
    if consent:
        assert client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True}).status_code == 200
    result = {
        "accuracy_score": 40.0,
        "pron_score": 40.0,
        "truncated": False,
        "words": [{"word": "beach", "accuracy": 14.0, "error_type": "None", "phonemes": BEACH_PHONEMES}],
    }
    fluency = {"metrics": {"words_per_minute": {"status": "unavailable"}}, "total_words": 0, "speaking_seconds": None}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path)"
            " values (?, 1, 'I live near a very big beach', 'ok', 'z')",
            (session_id,),
        )
        turn_id = conn.execute("select max(id) from turns").fetchone()[0]
        for dimension, payload in (("pronunciation", result), ("grammar", {"errors": [], "discarded_low_confidence": 0}), ("fluency", fluency)):
            conn.execute(
                "insert into turn_analyses (turn_id, dimension, status, result) values (?, ?, 'done', ?)",
                (turn_id, dimension, json.dumps(payload)),
            )
    if ended:
        assert client.patch(f"/api/sessions/{session_id}", json={"ended": True}).status_code == 200
    return session_id


def _practice(client: TestClient, session_id: int, word: str = "beach") -> object:
    return client.post(f"/api/sessions/{session_id}/practice", data={"word": word}, files=WAV)


def _use(azure: ScriptedPronunciation | None) -> None:
    app.dependency_overrides[get_pronunciation_provider] = lambda: azure


@pytest.fixture
def ready(client: TestClient, db_path: Path) -> tuple[int, Path]:
    _login(client, "ana")
    return _session_with_hard_word(client, db_path), db_path


def _usage(db_path: Path) -> float:
    rows = _query(db_path, "select seconds from azure_speech_usage")
    return rows[0][0] if rows else 0.0


def test_passing_the_word_locks_it_for_good(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, db_path = ready
    azure = ScriptedPronunciation([_heard(PRACTICE_PASS_SCORE)])
    _use(azure)

    res = _practice(client, session_id)

    body = res.json()
    assert res.status_code == 200 and body["status"] == "passed" and body["score"] == 90
    assert body["practice"] == {"attempts_used": 1, "attempts_left": 0, "passed": True, "locked": True, "best_score": 90}
    assert azure.calls[0][1] == "beach"  # the reference is the word itself
    assert _usage(db_path) == pytest.approx(1.5)

    again = _practice(client, session_id)  # it will not let the learner say it again

    assert again.status_code == 409 and again.json()["detail"]["code"] == "practice_locked"
    assert len(azure.calls) == 1


def test_a_word_that_still_costs_gets_two_tries_and_then_locks(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    azure = ScriptedPronunciation([_heard(40.0), _heard(60.0)])
    _use(azure)

    first = _practice(client, session_id).json()
    second = _practice(client, session_id).json()
    third = _practice(client, session_id)

    assert PRACTICE_MAX_ATTEMPTS == 2
    assert (first["status"], first["practice"]["attempts_left"]) == ("retry", 1)
    assert (second["status"], second["practice"]["locked"], second["practice"]["best_score"]) == ("locked", True, 60)
    assert third.status_code == 409 and len(azure.calls) == 2


def test_the_second_try_can_still_pass(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    _use(ScriptedPronunciation([_heard(30.0), _heard(95.0)]))

    _practice(client, session_id)
    second = _practice(client, session_id).json()

    assert second["status"] == "passed" and second["practice"]["attempts_used"] == 2


def test_a_high_azure_score_is_not_enough_if_whisper_heard_another_word(
    client: TestClient, ready: tuple[int, Path], whisper: dict
) -> None:
    session_id, _ = ready
    whisper["text"] = "Sheep."
    _use(ScriptedPronunciation([_heard(97.0)]))  # Azure is generous with a word that sounds alike

    body = _practice(client, session_id).json()

    assert body["status"] == "retry" and body["heard"] == "Sheep." and body["heard_ok"] is False
    assert body["practice"]["passed"] is False and body["practice"]["attempts_left"] == 1


def test_passing_needs_both_a_strict_score_and_whisper_hearing_the_word(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    _use(ScriptedPronunciation([_heard(PRACTICE_PASS_SCORE - 1)]))  # heard fine, but not good enough

    assert _practice(client, session_id).json()["status"] == "retry"
    assert PRACTICE_PASS_SCORE == 90.0


def test_whisper_hearing_nothing_counts_as_not_heard(client: TestClient, ready: tuple[int, Path], whisper: dict) -> None:
    session_id, _ = ready
    whisper["text"] = NoSpeechError("silence")
    _use(ScriptedPronunciation([_heard(99.0)]))

    body = _practice(client, session_id).json()

    assert body["status"] == "retry" and body["heard"] == "" and body["heard_ok"] is False


def test_a_failing_whisper_decides_nothing_and_costs_no_attempt(client: TestClient, ready: tuple[int, Path], whisper: dict) -> None:
    session_id, db_path = ready
    whisper["text"] = STTError("boom")
    _use(ScriptedPronunciation([_heard(99.0)]))

    res = _practice(client, session_id)

    assert res.status_code == 503 and res.json()["detail"]["code"] == "service_busy"
    assert _query(db_path, "select attempts, calls from word_practice") == [(0, 1)]  # the call counts, the attempt does not


def test_the_result_shows_how_the_word_sounded_and_where_it_cost(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    _use(ScriptedPronunciation([_heard(40.0)]))

    body = _practice(client, session_id).json()

    assert body["ipa"] == "i" and body["sounds"] == [{"ipa": "i", "score": 40}] and body["weakest_sound"] == 0


def test_silence_does_not_use_an_attempt_but_the_calls_are_capped(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, db_path = ready
    azure = ScriptedPronunciation([PronunciationNoSpeechError("nothing") for _ in range(PRACTICE_MAX_CALLS)])
    _use(azure)

    results = [_practice(client, session_id) for _ in range(PRACTICE_MAX_CALLS)]

    assert all(r.json()["status"] == "no_speech" and r.json()["practice"]["attempts_used"] == 0 for r in results[:-1])
    assert results[0].json()["practice"]["attempts_left"] == 2  # silence cost no attempt
    assert results[-1].json()["practice"]["locked"] is True  # but the free quota is not a loop
    assert _practice(client, session_id).status_code == 409 and len(azure.calls) == PRACTICE_MAX_CALLS
    assert _usage(db_path) == pytest.approx(1.5 * PRACTICE_MAX_CALLS)  # silence still used audio


def test_the_word_is_matched_ignoring_case_and_punctuation(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    _use(ScriptedPronunciation([_heard(95.0)]))

    assert _practice(client, session_id, word="Beach,").json()["status"] == "passed"


def test_only_words_of_the_list_can_be_practised(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    azure = ScriptedPronunciation([_heard(90.0)])
    _use(azure)

    res = _practice(client, session_id, word="zebra")

    assert res.status_code == 404 and res.json()["detail"]["code"] == "word_not_found" and azure.calls == []


def test_it_needs_audio_consent_and_an_ended_session(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    _use(ScriptedPronunciation([_heard(90.0)]))
    no_consent = _session_with_hard_word(client, db_path, consent=False)
    open_session = _session_with_hard_word(client, db_path, ended=False)

    assert _practice(client, no_consent).json()["detail"]["code"] == "audio_consent_required"
    assert _practice(client, open_session).json()["detail"]["code"] == "session_not_ended"


def test_another_users_session_is_not_found(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    _use(ScriptedPronunciation([_heard(90.0)]))
    client.cookies.clear()
    _login(client, "bob")

    assert _practice(client, session_id).status_code == 404


def test_without_quota_it_does_not_call_azure_nor_use_an_attempt(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, db_path = ready
    with sqlite3.connect(db_path) as conn:
        conn.execute("insert into azure_speech_usage (month, seconds) values (?, ?)", (month_key(), USABLE_MONTHLY_SECONDS - 1.0))
    azure = ScriptedPronunciation([_heard(90.0)])
    _use(azure)

    res = _practice(client, session_id)

    assert res.status_code == 503 and res.json()["detail"]["code"] == "quota_exhausted"
    assert azure.calls == [] and _query(db_path, "select count(*) from word_practice") == [(0,)]


def test_a_busy_service_is_retried_briefly_and_costs_no_attempt(
    client: TestClient, ready: tuple[int, Path], backoff_waits: list[float]
) -> None:
    session_id, db_path = ready
    azure = ScriptedPronunciation([PronunciationRateLimitError("429") for _ in range(3)])
    _use(azure)

    res = _practice(client, session_id)

    assert res.status_code == 503 and res.json()["detail"]["code"] == "service_busy"
    assert backoff_waits == [1.0, 3.0] and len(azure.calls) == 3  # someone is waiting: short waits
    assert _query(db_path, "select count(*) from word_practice") == [(0,)] and _usage(db_path) == 0.0


def test_a_long_recording_is_refused(client: TestClient, ready: tuple[int, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    session_id, _ = ready
    monkeypatch.setattr(practice_api, "measure_seconds", lambda path: 20.0)
    azure = ScriptedPronunciation([_heard(90.0)])
    _use(azure)

    res = _practice(client, session_id)

    assert res.status_code == 413 and azure.calls == []


def test_without_azure_configured_the_practice_is_unavailable(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, _ = ready
    _use(None)

    assert _practice(client, session_id).status_code == 503


def test_the_report_carries_the_practice_state_but_does_not_save_it(client: TestClient, ready: tuple[int, Path]) -> None:
    session_id, db_path = ready
    app.dependency_overrides[get_llm_provider] = lambda: ScriptedGrammarLLM()
    _use(ScriptedPronunciation([_heard(30.0)]))

    before = client.get(f"/api/sessions/{session_id}/report").json()["pronunciation"]["hard_words"][0]
    _practice(client, session_id)
    after = client.get(f"/api/sessions/{session_id}/report").json()["pronunciation"]["hard_words"][0]

    assert before["word"] == "beach" and before["practice"] == {"attempts_used": 0, "attempts_left": 2, "passed": False, "locked": False, "best_score": None}
    assert after["practice"]["attempts_used"] == 1 and after["practice"]["best_score"] == 30
    saved = _query(db_path, f"select report from sessions where id = {session_id}")[0][0]
    assert saved is None or json.loads(saved)["pronunciation"]["hard_words"][0]["practice"] is None
