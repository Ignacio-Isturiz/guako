"""The judges of "darse a entender" and "listening", and the analysis graph that runs them.

Nothing here calls an LLM: answers are simulated. What is checked is the honesty rule (a score the judge is not
sure about is never shown), what a failing provider or a missing context does, which turns are skipped, what goes
into the prompt, and that one failing node never takes the others down.
"""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analysis.graph import build_analysis_graph
from app.analysis.judge import (
    CONFIDENCE_CAP,
    MAX_TUTOR_CHARS,
    MIN_JUDGE_CONFIDENCE,
    MIN_JUDGED_WORDS,
    JudgedDimension,
    TurnJudgement,
    content_words,
    is_trivial,
    judge_turn,
    transcript_reliability,
)
from app.config import settings
from app.conversation.deps import get_stt_provider, get_tts_provider
from app.llm.errors import LLMProviderError
from app.llm.factory import get_llm_provider
from app.main import app
from app.providers.errors import LLMExhausted
from app.providers.router import ProviderRouter, Route
from app.providers.routed import RoutedLLM, classify_llm, llm_exhausted
from app.providers.state import ProviderState
from app.reports import JudgeReport, SessionReport, build_judge_report
from app.stt import STTProvider, TranscriptionResult, WordTiming
from app.stt.verbose_json import to_result
from tests.analysis_helpers import ScriptedGrammarLLM, err, judgement, run_analyses
from tests.fakes import FakeTTS
from tests.test_provider_router import make_state
from tests.test_sessions_api import AUDIO, _login, _new_session, _query

TUTOR = "Did you do anything special this morning?"


# --- a turn in the database ----------------------------------------------------------------------------


def _turn(
    db_path: Path,
    transcript: str,
    *,
    opening: bool = True,
    stt_confidence: float | None = None,
    no_speech: float | None = None,
    level: str = "B1",
    topic: str = "Daily routine",
) -> int:
    """A session with Guako's question as turn 0 (unless ``opening`` is False) and the learner's answer as turn 1."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("insert into sessions (user_id, level, topic, audio_consent, created_at) values (1, ?, ?, 0, current_timestamp)", (level, topic))
        session_id = conn.execute("select max(id) from sessions").fetchone()[0]
        if opening:
            conn.execute("insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path) values (?, 0, '', ?, 'z')", (session_id, TUTOR))
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path, stt_confidence, stt_no_speech_prob)"
            " values (?, 1, ?, 'ok', 'z', ?, ?)",
            (session_id, transcript, stt_confidence, no_speech),
        )
    return session_id


def _analysis(db_path: Path, dimension: str, turn_number: int = 1) -> tuple:
    sql = (
        "select a.status, a.result, a.error from turn_analyses a join turns t on t.id = a.turn_id "
        f"where a.dimension = '{dimension}' and t.turn_number = {turn_number}"
    )
    return _query(db_path, sql)[0]


def _stored(db_path: Path, dimension: str) -> dict:
    return json.loads(_analysis(db_path, dimension)[1])


def _report(db_path: Path, dimension: str) -> JudgeReport:
    status, result, _ = _analysis(db_path, dimension)
    return build_judge_report([(1, SimpleNamespace(status=status, result=json.loads(result) if result else None))])


@pytest.fixture
def seeded(client: TestClient, db_path: Path) -> Path:
    _login(client, "ana")
    return db_path


def _run(db_path: Path, llm: ScriptedGrammarLLM) -> None:
    run_analyses(db_path, llm)


# --- the honesty rule --------------------------------------------------------------------------------------


def test_a_score_the_judge_was_not_sure_about_is_stored_but_never_shown(seeded: Path) -> None:
    _turn(seeded, "I went to the beach yesterday")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [judgement(communication=2, listening=1, confidence=0.4)]

    _run(seeded, llm)

    stored = _stored(seeded, "communication")
    assert stored["score"] == 2 and stored["hidden"] is True  # kept for the evals...
    for dimension in ("communication", "listening"):
        report = _report(seeded, dimension)  # ...but the report does not show it
        assert report.score is None and report.turns_hidden == 1 and report.turns_judged == 0 and report.status == "incomplete"
        assert any("confianza" in note for note in report.notes)


def test_the_threshold_is_exact_and_documented() -> None:
    assert MIN_JUDGE_CONFIDENCE == 0.6
    llm = ScriptedGrammarLLM()
    ctx = {"transcript": "I like trains very much", "tutor_prev": TUTOR}

    at = judgement(communication=4, listening=None, confidence=MIN_JUDGE_CONFIDENCE)
    below = judgement(communication=4, listening=None, confidence=MIN_JUDGE_CONFIDENCE - 0.01)

    llm.judgements = [at]
    assert judge_turn(llm, ctx, False)["communication"]["hidden"] is False  # exactly at the threshold: shown
    llm.judgements = [below]
    assert judge_turn(llm, ctx, False)["communication"]["hidden"] is True


def test_an_unreliable_transcript_caps_the_confidence_so_the_score_is_hidden() -> None:
    confident = judgement(communication=5, listening=None, confidence=0.95)
    llm = ScriptedGrammarLLM()

    def run(stt_confidence: float | None, fixes: int = 0) -> dict:
        llm.judgements = [confident]
        intended = {"text": "x", "fixes": [{"heard": "a", "intended": "b"}] * fixes} if fixes else None
        return judge_turn(llm, {"transcript": "I like trains", "tutor_prev": TUTOR, "stt_confidence": stt_confidence}, False, intended)["communication"]

    assert run(0.9)["confidence"] == 0.95 and run(0.9)["reliability"] == "high"  # no cap
    assert run(0.6)["confidence"] == CONFIDENCE_CAP["medium"] and run(0.6)["hidden"] is False
    assert run(0.3)["confidence"] == CONFIDENCE_CAP["low"] and run(0.3)["hidden"] is True  # unsure recognizer: not shown
    assert run(None)["confidence"] == 0.95 and run(None)["reliability"] == "unknown"  # nothing reported: no cap, no invention
    assert run(0.9, fixes=1)["reliability"] == "medium"  # a word had to be fixed: the text was wrong somewhere


def test_reliability_levels_come_from_the_recognizers_numbers() -> None:
    assert transcript_reliability(0.8, 0.01) == "high"
    assert transcript_reliability(0.6, 0.01) == "medium"
    assert transcript_reliability(0.3, 0.01) == "low"
    assert transcript_reliability(0.9, 0.9) == "low"  # it thinks there was no speech
    assert transcript_reliability(None, None) == "unknown"
    assert transcript_reliability(None, None, fixes=1) == "medium"
    assert transcript_reliability(0.6, 0.0, fixes=1) == "low"


# --- one call, two rows, and what goes into the prompt -------------------------------------------------------


def test_one_llm_call_judges_both_dimensions_and_fills_both_rows(seeded: Path) -> None:
    _turn(seeded, "No, I didn't do anything special today")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [judgement(communication=5, listening=4)]

    _run(seeded, llm)

    assert len(llm.judge_prompts) == 1  # not two calls
    assert (_analysis(seeded, "communication")[0], _analysis(seeded, "listening")[0]) == ("done", "done")
    assert _stored(seeded, "communication")["score"] == 5 and _stored(seeded, "listening")["score"] == 4
    assert _report(seeded, "communication").score == 100 and _report(seeded, "listening").score == 75  # (s - 1) / 4 * 100


def test_the_prompt_has_the_tutors_message_the_level_and_the_topic_and_nothing_else(seeded: Path) -> None:
    _turn(seeded, "I went to the beach yesterday", level="A2", topic="Weekend plans")
    llm = ScriptedGrammarLLM()
    llm.script = [[err("went", "go")]]  # a grammar error that the judge must never see

    _run(seeded, llm)

    prompt = llm.judge_prompts[0]
    assert TUTOR in prompt and "I went to the beach yesterday" in prompt
    assert "Learner level: A2" in prompt and "Weekend plans" in prompt
    assert "Respond ONLY with JSON" in prompt and "5 = " in prompt and "1 = " in prompt  # the rubric with its descriptors
    assert "verb_tense" not in prompt and "Use the past" not in prompt  # independent of the grammar analysis


def test_a_long_tutor_message_is_cut_so_the_prompt_stays_small() -> None:
    llm = ScriptedGrammarLLM()

    judge_turn(llm, {"transcript": "I like trains", "tutor_prev": "x" * 5000}, True)

    assert "x" * MAX_TUTOR_CHARS in llm.judge_prompts[0] and "x" * (MAX_TUTOR_CHARS + 1) not in llm.judge_prompts[0]


def test_the_rationale_language_follows_the_learner_and_the_text_the_recognizer_fixed_is_shown() -> None:
    llm = ScriptedGrammarLLM()
    intended = {"text": "No, I didn't do anything special today", "fixes": [{"heard": "to die", "intended": "today"}]}

    judge_turn(llm, {"transcript": "No I didn't anything special to die", "tutor_prev": TUTOR, "feedback_language": "en"}, True, intended)
    judge_turn(llm, {"transcript": "No I didn't anything special to die", "tutor_prev": TUTOR, "feedback_language": "es"}, True)

    assert "written in English" in llm.judge_prompts[0] and "written in Spanish" in llm.judge_prompts[1]
    assert "MEANT" in llm.judge_prompts[0] and "special today" in llm.judge_prompts[0]
    assert "MEANT" not in llm.judge_prompts[1]


def test_a_low_reliability_transcript_is_flagged_in_the_prompt() -> None:
    llm = ScriptedGrammarLLM()

    judge_turn(llm, {"transcript": "I like trains", "tutor_prev": TUTOR, "stt_confidence": 0.3}, True)
    judge_turn(llm, {"transcript": "I like trains", "tutor_prev": TUTOR, "stt_confidence": 0.95}, True)

    assert "LOW reliability" in llm.judge_prompts[0] and "reliability" not in llm.judge_prompts[1].lower().replace("transcript has", "")


# --- missing context, trivial turns, and "can you repeat?" -----------------------------------------------------


def test_without_the_tutors_previous_message_only_communication_is_judged(seeded: Path) -> None:
    _turn(seeded, "I went to the beach yesterday", opening=False)
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [judgement(communication=4, listening=None)]

    _run(seeded, llm)

    assert _analysis(seeded, "communication")[0] == "done"
    assert _analysis(seeded, "listening")[0] == "skipped_no_context"
    assert "there is no previous tutor message" in llm.judge_prompts[0]  # the model is told so
    report = _report(seeded, "listening")
    assert report.status == "empty" and report.turns_without_context == 1 and report.score is None


@pytest.mark.parametrize("transcript", ["Yes", "Me too.", "um, yes, uh", "Yes, sure"])
def test_a_trivial_turn_is_skipped_without_calling_the_llm(seeded: Path, transcript: str) -> None:
    _turn(seeded, transcript)
    llm = ScriptedGrammarLLM()
    llm.script = [[]]

    _run(seeded, llm)

    assert (_analysis(seeded, "communication")[0], _analysis(seeded, "listening")[0]) == ("skipped_trivial", "skipped_trivial")
    assert llm.judge_prompts == []
    report = _report(seeded, "communication")
    assert report.status == "empty" and report.turns_trivial == 1  # it does not count for or against the learner


def test_the_triviality_threshold() -> None:
    assert MIN_JUDGED_WORDS == 3
    assert content_words("um, I, uh, like trains") == 3  # hesitation sounds are not words
    assert is_trivial("Me too") and not is_trivial("I like trains")
    assert is_trivial("") and is_trivial("um uh hmm")


def test_asking_to_repeat_is_a_request_not_a_wrong_answer(seeded: Path) -> None:
    _turn(seeded, "Sorry, could you repeat that please")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [judgement(communication=5, listening=None, asked_to_repeat=True)]

    _run(seeded, llm)

    listening = _stored(seeded, "listening")
    assert listening["asked_to_repeat"] is True and listening["score"] is None
    report = _report(seeded, "listening")
    assert report.turns_asked_to_repeat == 1 and report.score is None and report.status == "empty"
    assert any("repetir" in note for note in report.notes)
    assert _report(seeded, "communication").score == 100  # the message itself was perfectly clear


# --- failures: incomplete, never broken ----------------------------------------------------------------------------


def test_a_failing_provider_marks_the_judge_failed_and_the_report_incomplete(seeded: Path, backoff_waits: list[float]) -> None:
    _turn(seeded, "I went to the beach yesterday")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [LLMProviderError("503") for _ in range(4)]  # the first try plus the three retries

    _run(seeded, llm)  # must not raise

    for dimension in ("communication", "listening"):
        status, result, error = _analysis(seeded, dimension)
        assert (status, result, error) == ("failed", None, "ai_unavailable")
        report = _report(seeded, dimension)
        assert report.status == "incomplete" and report.score is None and report.turns_failed == 1
    assert _analysis(seeded, "grammar")[0] == "done" and _analysis(seeded, "fluency")[0] == "done"  # the rest is intact
    assert backoff_waits == [2.0, 6.0, 18.0]


def test_a_judge_that_works_on_the_retry_is_not_failed(seeded: Path, backoff_waits: list[float]) -> None:
    _turn(seeded, "I went to the beach yesterday")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [LLMProviderError("503"), judgement()]

    _run(seeded, llm)

    assert _analysis(seeded, "communication")[0] == "done" and backoff_waits == [2.0]


def test_when_every_provider_is_out_the_judge_stays_pending_and_does_not_wait(seeded: Path, backoff_waits: list[float]) -> None:
    _turn(seeded, "I went to the beach yesterday")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [LLMExhausted("all out", retry_after=60)]

    _run(seeded, llm)

    assert (_analysis(seeded, "communication")[0], _analysis(seeded, "listening")[0]) == ("pending", "pending")
    assert backoff_waits == [] and _analysis(seeded, "grammar")[0] == "done"
    assert _report(seeded, "communication").status == "pending"  # the report says so, honestly


def test_an_answer_without_a_listening_score_fails_only_the_listening(seeded: Path) -> None:
    _turn(seeded, "I went to the beach yesterday")
    llm = ScriptedGrammarLLM()
    llm.script = [[]]
    llm.judgements = [judgement(communication=4, listening=None)]  # the model forgot it, and did not say it asked to repeat

    _run(seeded, llm)

    assert _analysis(seeded, "communication")[0] == "done"
    assert _analysis(seeded, "listening")[0:3:2] == ("failed", "no_listening_score")


# --- the report -------------------------------------------------------------------------------------------------------


def _row(status: str, **result: object) -> SimpleNamespace:
    return SimpleNamespace(status=status, result=result or None)


def test_the_average_is_over_the_turns_that_were_judged() -> None:
    rows = [(1, _row("done", score=5, rationale="a")), (2, _row("done", score=3, rationale="b")), (3, _row("done", score=1, rationale="c"))]

    report = build_judge_report(rows)

    assert report.score == 50 and report.status == "ok" and [t.score for t in report.turns] == [5, 3, 1]


def test_the_report_status_tells_what_is_missing() -> None:
    ok = _row("done", score=4, rationale="x")

    assert build_judge_report([(1, ok), (2, _row("pending"))]).status == "incomplete"
    assert build_judge_report([(1, ok), (2, _row("failed"))]).status == "incomplete"
    assert build_judge_report([(1, ok), (2, _row("done", score=4, hidden=True))]).status == "incomplete"
    assert build_judge_report([(1, ok), (2, _row("skipped_trivial"))]).status == "ok"  # trivial turns do not make it incomplete
    assert build_judge_report([(1, _row("pending"))]).status == "pending"
    assert build_judge_report([(1, None)]).status == "pending"  # never queued counts as pending
    assert build_judge_report([(1, _row("skipped_trivial"))]).status == "empty"
    assert build_judge_report([]).status == "empty"


def test_the_two_dimensions_no_longer_show_as_pending_placeholders(client: TestClient, db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Ears(STTProvider):
        def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
            return TranscriptionResult(text="I like to travel by train", duration=2.0, words=[WordTiming(word="I", start=0, end=0.3)], confidence=0.82, no_speech_prob=0.01)

    class Tutor:
        def generate(self, prompt: str, response_model: type, *, system: str | None = None):  # type: ignore[no-untyped-def]
            from tests.analysis_helpers import DEFAULT_JUDGEMENT

            if "communication" in response_model.model_fields:
                return response_model.model_validate(DEFAULT_JUDGEMENT)
            return response_model(errors=[]) if "errors" in response_model.model_fields else response_model(reply="Nice!")

    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    app.dependency_overrides[get_stt_provider] = lambda: Ears()
    app.dependency_overrides[get_tts_provider] = lambda: FakeTTS([])
    app.dependency_overrides[get_llm_provider] = lambda: Tutor()
    _login(client, "ana")
    session_id = _new_session(client)
    assert client.post(f"/api/sessions/{session_id}/opening").status_code == 201
    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201
    client.patch(f"/api/sessions/{session_id}", json={"ended": True})

    body = client.get(f"/api/sessions/{session_id}/report").json()

    assert body["communication"]["status"] == "ok" and body["communication"]["score"] == 75
    assert body["listening"]["status"] == "ok" and body["listening"]["score"] == 100  # Guako's opening is the previous message
    # The confidence of the transcription was saved with the turn, for the judge that ran after it.
    assert _query(db_path, "select stt_confidence, stt_no_speech_prob from turns where turn_number = 1") == [(0.82, 0.01)]


def test_a_report_saved_before_the_judges_still_loads_and_is_rebuilt() -> None:
    old = {"session_id": 1, "user_turns": 0, "grammar": {"status": "empty", "score": None, "errors": [], "turns_analyzed": 0, "turns_failed": 0},
           "fluency": {"status": "empty", "score": None, "words_per_minute": None, "long_pauses": 0, "filler_words": 0, "total_words": 0},
           "communication": {"status": "pending", "score": None}, "listening": {"status": "pending", "score": None}}

    assert SessionReport.model_validate(old).communication.status == "pending"


# --- the graph ---------------------------------------------------------------------------------------------------------


def test_the_graph_has_the_documented_shape() -> None:
    graph = build_analysis_graph(None, None, None).get_graph()  # type: ignore[arg-type]

    assert {n for n in graph.nodes} == {"__start__", "load", "fluency", "grammar", "merge", "triage", "pronunciation", "judge", "persist", "__end__"}
    edges = {(e.source, e.target) for e in graph.edges}
    assert {("__start__", "load"), ("fluency", "merge"), ("grammar", "merge"), ("merge", "triage"), ("pronunciation", "persist"), ("judge", "persist"), ("persist", "__end__")} <= edges
    # phase 1 fans out from load, phase 2 from triage; nothing skips the merge or the persist
    assert {("load", "fluency"), ("load", "grammar"), ("triage", "pronunciation"), ("triage", "judge"), ("triage", "persist")} <= edges


def test_the_mermaid_diagram_names_every_node() -> None:
    diagram = build_analysis_graph(None, None, None).get_graph().draw_mermaid()  # type: ignore[arg-type]

    assert all(name in diagram for name in ("load", "fluency", "grammar", "merge", "triage", "pronunciation", "judge", "persist"))


def test_a_node_that_fails_does_not_take_the_others_down(seeded: Path, backoff_waits: list[float]) -> None:
    _turn(seeded, "I went to the beach yesterday")
    llm = ScriptedGrammarLLM()
    llm.script = [LLMProviderError("503") for _ in range(4)]  # the grammar fails for good
    llm.judgements = [judgement(communication=4, listening=5)]

    _run(seeded, llm)

    assert _analysis(seeded, "grammar")[0] == "failed"
    assert _analysis(seeded, "fluency")[0] == "done"  # the sibling of phase 1 survives
    assert _analysis(seeded, "communication")[0] == "done"  # and phase 2 still runs, on the transcript


def test_only_the_pending_dimensions_are_run_again(seeded: Path) -> None:
    _turn(seeded, "I went to the beach yesterday")
    first = ScriptedGrammarLLM()
    first.script = [[]]
    first.judgements = [LLMExhausted("all out")]
    _run(seeded, first)
    assert _analysis(seeded, "communication")[0] == "pending"

    second = ScriptedGrammarLLM()  # no grammar script: if the grammar ran again it would crash
    second.judgements = [judgement(communication=3, listening=3)]
    _run(seeded, second)

    assert second.prompts == [] and len(second.judge_prompts) == 1  # only the judge was called
    assert _analysis(seeded, "communication")[0] == "done" and _stored(seeded, "communication")["score"] == 3


def test_the_judge_goes_through_the_router_with_the_analysis_use() -> None:
    class StubJudge:
        name, model = "openai", "stub"

        def generate_with_usage(self, prompt: str, response_model: type, *, system: str | None = None):  # type: ignore[no-untyped-def]
            from app.llm.base import LLMUsage

            return TurnJudgement(communication=JudgedDimension(score=4, rationale="ok", confidence=0.9)), LLMUsage(600, 120)

    state: ProviderState = make_state()
    routed = RoutedLLM(ProviderRouter("llm", "analysis", [Route("openai", StubJudge())], state, classify_llm, llm_exhausted("analysis")))

    result = judge_turn(routed, {"transcript": "I like trains very much", "tutor_prev": ""}, False)

    assert result["communication"]["score"] == 4
    aggregates, _ = state.drain()
    key = next(iter(aggregates))
    assert key[1:] == ("openai", "llm", "analysis") and aggregates[key]["prompt_tokens"] == 600  # counted, with its use


# --- confidence of the transcription ----------------------------------------------------------------------------------


def test_the_confidence_comes_from_the_segments_weighted_by_length() -> None:
    payload = {
        "text": "hello there",
        "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
        "segments": [
            {"start": 0.0, "end": 3.0, "avg_logprob": -0.2, "no_speech_prob": 0.01},
            {"start": 3.0, "end": 4.0, "avg_logprob": -1.0, "no_speech_prob": 0.4},
        ],
    }

    result = to_result(payload, "Groq")

    assert result.confidence == pytest.approx(__import__("math").exp((-0.2 * 3 + -1.0 * 1) / 4), abs=1e-3)
    assert result.no_speech_prob == 0.4  # the highest, not the average: one doubtful segment is enough


def test_without_segments_there_is_no_confidence_and_none_is_invented() -> None:
    result = to_result({"text": "hello", "words": []}, "Groq")

    assert result.confidence is None and result.no_speech_prob is None
