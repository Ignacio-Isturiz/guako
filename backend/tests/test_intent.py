"""Layers against a misrecognised word ("to die" for "today"): context for Whisper, and the intended text
that pronunciation is scored against. Nothing here calls Whisper, the LLM or Azure.
"""

import json
import sqlite3
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.analysis.grammar import analyze_grammar
from app.analysis.intent import MAX_CHANGED_FRACTION, MIN_ALLOWED_CHANGES, validated_fixes
from app.conversation.nodes import make_transcribe
from app.pronunciation import PronunciationResult, WordScore
from app.reports import build_pronunciation_report
from app.stt.groq import PROMPT_MAX_CHARS, GroqWhisperSTTProvider
from tests.analysis_helpers import ScriptedGrammarLLM, ScriptedPronunciation, run_analyses
from tests.fakes import FakeSTT
from tests.test_sessions_api import _login, _query

SAID = "No, I doesn't anything special to die."
MEANT = "No, I doesn't anything special today."
TUTOR = "That's great to hear! Did you do anything special this morning?"


# --- layer 1: the tutor's last message is the context of the recognizer ----------------------------


def test_the_transcribe_node_gives_whisper_the_tutors_last_message() -> None:
    stt = FakeSTT([], text="hello")
    state = {"user_audio_path": "a.wav", "messages": [{"role": "assistant", "content": "Hi!"}, {"role": "user", "content": "Hey"}, {"role": "assistant", "content": TUTOR}]}

    make_transcribe(stt)(state)  # type: ignore[arg-type]

    assert stt.contexts == [TUTOR]


def test_the_first_turn_has_no_context() -> None:
    stt = FakeSTT([], text="hello")

    make_transcribe(stt)({"user_audio_path": "a.wav", "messages": []})  # type: ignore[arg-type]

    assert stt.contexts == [None]


def _groq_with_fake_client(captured: list[dict]) -> GroqWhisperSTTProvider:
    def create(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        return SimpleNamespace(model_dump=lambda: {"text": "hi", "language": "english", "duration": 1.0, "words": []})

    provider = GroqWhisperSTTProvider(api_key=SecretStr("not-a-real-key"))
    provider._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))  # type: ignore[assignment]
    return provider


def test_groq_receives_the_context_as_prompt_and_only_when_there_is_one(tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFFfake")
    sent: list[dict] = []
    provider = _groq_with_fake_client(sent)

    provider.transcribe(str(audio), TUTOR)
    provider.transcribe(str(audio), "x" * 5000)
    provider.transcribe(str(audio))
    provider.transcribe(str(audio), "   ")

    assert sent[0]["prompt"] == TUTOR
    assert len(sent[1]["prompt"]) == PROMPT_MAX_CHARS  # Whisper reads a limited prompt
    assert "prompt" not in sent[2] and "prompt" not in sent[3]


# --- layer 2: the intended text is checked in code before it is used -------------------------------


def test_a_recognition_fix_is_accepted_and_listed() -> None:
    text, fixes = validated_fixes(SAID, MEANT)

    # The real case: two recognised words ("to die") were really one ("today").
    assert text == "No I doesn't anything special today" and fixes == [{"heard": "to die", "intended": "today"}]


def test_a_grammar_correction_is_not_a_recognition_fix() -> None:
    # The model also "fixed" doesn't -> didn't, which is a grammar error of the learner: it must stay as said.
    proposal = "No, I didn't anything special today."
    errors = [("doesn't", "didn't")]

    text, fixes = validated_fixes(SAID, proposal, errors)

    assert text == "No I doesn't anything special today"
    assert fixes == [{"heard": "to die", "intended": "today"}]
    assert validated_fixes("I goed home", "I went home", [("goed", "went")]) == ("", [])  # nothing else to fix


def test_nothing_to_fix_means_no_intended_text() -> None:
    assert validated_fixes(SAID, SAID) == ("", [])
    assert validated_fixes(SAID, SAID.upper()) == ("", [])  # case is not a change
    assert validated_fixes("", "hello") == ("", [])


def test_a_proposal_that_adds_or_drops_words_is_rejected() -> None:
    # The learner did not say the added "do": the grammar mistake stays theirs.
    assert validated_fixes(SAID, "No, I don't do anything special today.") == ("", [])
    assert validated_fixes("I go home", "I go") == ("", [])


def test_a_proposal_that_rewrites_too_much_is_rejected() -> None:
    assert (MIN_ALLOWED_CHANGES, MAX_CHANGED_FRACTION) == (2, 0.25)
    assert validated_fixes("I like red cars", "We hate blue trains") == ("", [])  # 4 of 4
    assert validated_fixes("a b c d", "a b c x")[0] != ""  # one word is fine
    twenty = " ".join(f"w{i}" for i in range(20))
    assert validated_fixes(twenty, twenty.replace("w3", "x3").replace("w9", "x9"))[0] != ""  # 2 of 20
    five = twenty.replace("w1 ", "x1 ").replace("w3 ", "x3 ").replace("w5 ", "x5 ").replace("w7 ", "x7 ").replace("w9 ", "x9 ")
    assert validated_fixes(twenty, five)[0] != ""  # 5 of 20 is the limit (25 %)
    six = five.replace("w11 ", "x11 ")
    assert validated_fixes(twenty, six) == ("", [])  # 6 of 20 is a rewrite


def test_grammar_analysis_returns_the_checked_intended_text_and_uses_the_tutors_message() -> None:
    llm = ScriptedGrammarLLM()
    llm.script = [{"errors": [], "intended_text": MEANT}]

    result = analyze_grammar(llm, SAID, TUTOR)

    assert result["intended_text"] == "No I doesn't anything special today" and result["heard_fixes"][0]["intended"] == "today"
    assert TUTOR in llm.prompts[0] and SAID in llm.prompts[0] and "Learner text:" in llm.prompts[0]


def test_grammar_analysis_drops_a_bad_proposal() -> None:
    llm = ScriptedGrammarLLM()
    llm.script = [{"errors": [], "intended_text": "A completely different sentence about trains."}]

    assert analyze_grammar(llm, SAID)["intended_text"] == ""


# --- pronunciation is scored against what was meant ------------------------------------------------


def _wav(path: Path) -> str:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return str(path)


def _conversation(db_path: Path, tmp_path: Path, *, seconds: float = 3.0, words: str | None = None) -> None:
    """Session with Guako's question (turn 0) and the learner's answer (turn 1) as Whisper wrote it."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("insert into sessions (user_id, level, topic, audio_consent, created_at) values (1, 'B1', 't', 1, current_timestamp)")
        sid = conn.execute("select max(id) from sessions").fetchone()[0]
        conn.execute("insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path) values (?, 0, '', ?, 'z')", (sid, TUTOR))
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path, user_audio_path, user_audio_seconds, word_timestamps)"
            " values (?, 1, ?, 'ok', 'z', ?, ?, ?)",
            (sid, SAID, _wav(tmp_path / "turn.wav"), seconds, words),
        )


def _result() -> PronunciationResult:
    return PronunciationResult(accuracy_score=80.0, pron_score=75.0, words=[WordScore(word="today", accuracy=76.0)])


@pytest.fixture
def seeded(client: TestClient, db_path: Path) -> Path:
    _login(client, "ana")
    return db_path


def _row(db_path: Path, dimension: str) -> tuple:
    """The analysis of the learner's turn (turn 1), not of Guako's opening line."""
    sql = (
        "select a.status, a.result, a.error from turn_analyses a join turns t on t.id = a.turn_id "
        f"where a.dimension = '{dimension}' and t.turn_number = 1"
    )
    return _query(db_path, sql)[0]


def test_pronunciation_is_scored_against_the_intended_text_and_says_so(seeded: Path, tmp_path: Path) -> None:
    _conversation(seeded, tmp_path)
    llm = ScriptedGrammarLLM()
    llm.script = [{"errors": [], "intended_text": MEANT}]
    azure = ScriptedPronunciation([_result()])

    run_analyses(seeded, llm, azure)

    assert azure.calls[0][1] == "No I doesn't anything special today"  # not "...to die."
    assert TUTOR in llm.prompts[0]  # the grammar analysis got Guako's question as context
    stored = json.loads(_row(seeded, "pronunciation")[1])
    assert stored["reference_text"] == "No I doesn't anything special today" and stored["heard_fixes"][0]["intended"] == "today"


def test_without_a_fix_the_reference_is_the_transcript(seeded: Path, tmp_path: Path) -> None:
    _conversation(seeded, tmp_path)
    llm = ScriptedGrammarLLM()
    llm.script = [{"errors": [], "intended_text": SAID}]
    azure = ScriptedPronunciation([_result()])

    run_analyses(seeded, llm, azure)

    assert azure.calls[0][1] == SAID and json.loads(_row(seeded, "pronunciation")[1])["heard_fixes"] == []


def test_if_the_grammar_analysis_failed_pronunciation_still_uses_the_transcript(seeded: Path, tmp_path: Path, backoff_waits: list[float]) -> None:
    from tests.analysis_helpers import rate_limited

    _conversation(seeded, tmp_path)
    llm = ScriptedGrammarLLM()
    llm.script = rate_limited()
    azure = ScriptedPronunciation([_result()])

    run_analyses(seeded, llm, azure)

    assert _row(seeded, "grammar")[0] == "failed" and _row(seeded, "pronunciation")[0] == "done"
    assert azure.calls[0][1] == SAID


def test_a_long_turn_keeps_the_transcript_because_the_cut_follows_its_word_timings(seeded: Path, tmp_path: Path) -> None:
    words = json.dumps([{"word": w, "start": i * 5.0, "end": i * 5.0 + 4.0} for i, w in enumerate(SAID.split())])
    _conversation(seeded, tmp_path, seconds=40.0, words=words)
    llm = ScriptedGrammarLLM()
    llm.script = [{"errors": [], "intended_text": MEANT}]
    azure = ScriptedPronunciation([_result()])

    run_analyses(seeded, llm, azure)

    assert azure.calls[0][1].split()[:2] == ["No,", "I"] and "today" not in azure.calls[0][1]
    assert json.loads(_row(seeded, "pronunciation")[1])["heard_fixes"] == []


# --- the report tells the learner what was understood differently ----------------------------------


def test_the_report_lists_what_was_scored_as_something_else() -> None:
    result = {"words": [{"word": "today", "accuracy": 76.0, "phonemes": []}], "truncated": False, "heard_fixes": [{"heard": "die", "intended": "today"}]}
    row = SimpleNamespace(status="done", result=result)

    report = build_pronunciation_report([(3, row)])

    assert [(f.turn_number, f.heard, f.intended) for f in report.heard_fixes] == [(3, "die", "today")]
    assert [h.word for h in report.hard_words] == ["today"]  # "today" is what gets practised, not "die"
