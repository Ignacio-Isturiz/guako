"""The judge eval set: the dataset, the agreement metrics, and that a failed case is reported, never scored."""

import pytest

from app.analysis.judge import PROMPT_VERSION
from app.config import settings
from app.prompts import load_prompt
from app.providers import chains
from app.providers.errors import LLMExhausted
from scripts.evals import common, judges
from scripts.evals.common import Tracker
from tests.analysis_helpers import ScriptedGrammarLLM, judgement


def _cases() -> list[dict]:
    return judges.load_cases()


def _perfect(case: dict) -> dict:
    return judgement(communication=case["expected"]["communication"], listening=case["expected"]["listening"], asked_to_repeat=bool(case.get("asked_to_repeat")))


# --- the dataset ----------------------------------------------------------------------------------------


def test_there_are_fifteen_well_formed_cases() -> None:
    cases = _cases()

    assert len(cases) == 15 and len({c["id"] for c in cases}) == 15
    for case in cases:
        assert {"id", "tutor", "learner", "level", "topic", "expected", "reviewed", "note"} <= set(case)
        assert 1 <= case["expected"]["communication"] <= 5
        listening = case["expected"]["listening"]
        assert (listening is None) == bool(case.get("asked_to_repeat"))
        assert listening is None or 1 <= listening <= 5


def test_the_cases_cover_the_whole_scale_of_both_dimensions() -> None:
    cases = _cases()

    assert {c["expected"]["communication"] for c in cases} == {1, 2, 3, 4, 5}
    assert {c["expected"]["listening"] for c in cases if c["expected"]["listening"]} == {1, 2, 3, 4, 5}
    assert any(c["expected"]["communication"] == 5 and c["expected"]["listening"] == 1 for c in cases)
    assert any(c["expected"]["communication"] <= 2 and (c["expected"]["listening"] or 0) >= 3 for c in cases)


def test_the_prompt_never_contains_a_sentence_of_the_eval_cases() -> None:
    template = load_prompt("judge", PROMPT_VERSION)

    for case in _cases():
        assert case["learner"].lower() not in template.lower(), case["id"]
        assert case["tutor"].lower() not in template.lower(), case["id"]


def test_the_earlier_prompt_versions_are_kept_to_compare_runs() -> None:
    assert PROMPT_VERSION == 3 and "ON ITS OWN" in load_prompt("judge", 3)
    assert "relevance belongs to the other dimension" in load_prompt("judge", 2)


# --- the metrics ----------------------------------------------------------------------------------------------


def test_agreement_with_known_numbers() -> None:
    result = judges.agreement([(5, 5, 0.9), (4, 5, 0.8), (3, 1, 0.5)])

    assert result == {
        "cases": 3,
        "exact": pytest.approx(0.333, abs=1e-3),
        "within_one": pytest.approx(0.667, abs=1e-3),
        "mean_abs_error": 1.0,
        "bias": pytest.approx(-0.333, abs=1e-3),
        "confidence_when_exact": 0.9,
        "confidence_when_off": 0.65,
    }


def test_nothing_to_compare_gives_no_figure() -> None:
    assert judges.agreement([]) is None


def test_the_repeat_request_agrees_only_when_both_say_so() -> None:
    case = next(c for c in _cases() if c.get("asked_to_repeat"))
    row = {"judgement": {"communication": {"score": 5, "hidden": False, "confidence": 0.9}, "listening": {"score": None, "asked_to_repeat": True}}}

    summary = judges.summarize([case], [row])

    assert summary["asked_to_repeat_agreed"] == "1/1" and summary["listening"] is None


# --- running it ---------------------------------------------------------------------------------------------------


def test_a_partial_run_reports_the_failures_and_scores_only_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = _cases()
    llm = ScriptedGrammarLLM()
    llm.judgements = [_perfect(c) for c in cases[:12]] + [LLMExhausted("out of quota")] * (3 * 4)  # 3 cases x 4 attempts
    monkeypatch.setattr(chains, "build_llm", lambda use, cfg, state: llm)
    monkeypatch.setattr(common, "RETRY_WAITS_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(common.time, "sleep", lambda s: None)

    result = judges.run(Tracker(settings, 2.0), judges.plan(settings), log=lambda s: None)

    assert result["cases"] == 15 and result["failed"] == 3 and result["failure_reasons"] == {"exhausted": 3}
    assert result["per_repeat"][0]["judged"] == 12 and result["metrics"]["communication"]["exact"]["median"] == 1.0
    assert not result["expectations_reviewed"] and any("NOT yet reviewed" in line for line in judges.describe(result))


def test_if_nothing_could_be_judged_no_figure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ScriptedGrammarLLM()
    llm.judgements = [LLMExhausted("out")] * 60
    monkeypatch.setattr(chains, "build_llm", lambda use, cfg, state: llm)
    monkeypatch.setattr(common, "RETRY_WAITS_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(common.time, "sleep", lambda s: None)

    result = judges.run(Tracker(settings, 2.0), judges.plan(settings), log=lambda s: None)

    assert result["failed"] == 15 and result["metrics"] == {"communication": None, "listening": None}
    assert any("NOT MEASURED" in line for line in judges.describe(result))
