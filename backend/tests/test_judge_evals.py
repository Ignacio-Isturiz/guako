"""The judge evals: the dataset, the agreement metrics, and that no number is ever invented when there is no quota.

The LLM is simulated: running the real eval is a manual step (scripts/run_judge_evals.py --yes).
"""

import json
import sys
from pathlib import Path

import pytest

from app.llm.errors import LLMProviderError, LLMRateLimitError
from app.providers import chains
from app.providers.errors import LLMExhausted
from scripts import run_judge_evals as evals
from tests.analysis_helpers import ScriptedGrammarLLM, judgement


def _cases() -> list[dict]:
    return evals.load_cases()


# --- the dataset ----------------------------------------------------------------------------------------


def test_there_are_fifteen_well_formed_cases() -> None:
    cases = _cases()

    assert len(cases) == 15 and len({c["id"] for c in cases}) == 15
    for case in cases:
        assert {"id", "tutor", "learner", "level", "topic", "expected", "reviewed", "note"} <= set(case)
        assert case["level"] in {"A1", "A2", "B1", "B2", "C1"} and case["tutor"].strip() and case["learner"].strip()
        assert 1 <= case["expected"]["communication"] <= 5
        listening = case["expected"]["listening"]
        assert (listening is None) == bool(case.get("asked_to_repeat"))  # no listening score only when it asked to repeat
        assert listening is None or 1 <= listening <= 5


def test_the_cases_cover_the_whole_scale_of_both_dimensions() -> None:
    cases = _cases()

    assert {c["expected"]["communication"] for c in cases} == {1, 2, 3, 4, 5}
    assert {c["expected"]["listening"] for c in cases if c["expected"]["listening"]} == {1, 2, 3, 4, 5}
    # The two dimensions are independent: clear but off topic, and on topic but unclear.
    assert any(c["expected"]["communication"] == 5 and c["expected"]["listening"] == 1 for c in cases)
    assert any(c["expected"]["communication"] <= 2 and (c["expected"]["listening"] or 0) >= 3 for c in cases)


def test_the_prompt_never_contains_a_sentence_of_the_eval_cases() -> None:
    """Examples in the rubric that are also eval cases would leak the answer: the eval would measure memory."""
    from app.analysis.judge import PROMPT_VERSION
    from app.prompts import load_prompt

    template = load_prompt("judge", PROMPT_VERSION)

    for case in _cases():
        assert case["learner"].lower() not in template.lower(), case["id"]
        assert case["tutor"].lower() not in template.lower(), case["id"]


def test_the_two_prompt_versions_exist_and_the_run_says_which_one_it_used() -> None:
    from app.analysis.judge import PROMPT_VERSION
    from app.prompts import load_prompt

    assert PROMPT_VERSION == 3 and "ON ITS OWN" in load_prompt("judge", 3)
    # The earlier prompts are kept to compare the runs; v2 is the one that broke listening, so it is the one
    # that talks about "relevance belongs to the other dimension".
    assert "judges ONE turn" in load_prompt("judge", 1) and "relevance belongs to the other dimension" in load_prompt("judge", 2)
    assert "relevance belongs to the other dimension" not in load_prompt("judge", 3)
    cases = _cases()
    assert evals.summarize(cases, [{"status": "no_quota", "error": "x"}] * len(cases))["prompt_version"] == PROMPT_VERSION


def test_the_expectations_start_unreviewed_so_the_report_says_so() -> None:
    assert not any(c["reviewed"] for c in _cases())  # drafts until a person confirms them


# --- the metrics ----------------------------------------------------------------------------------------------


def test_agreement_with_known_numbers() -> None:
    result = evals.agreement([(5, 5, 0.9), (4, 5, 0.8), (3, 1, 0.5)])

    assert result == {
        "cases": 3,
        "exact": pytest.approx(0.333, abs=1e-3),
        "within_one": pytest.approx(0.667, abs=1e-3),
        "mean_abs_error": 1.0,
        "bias": pytest.approx(-0.333, abs=1e-3),  # negative: stricter than the person
        "confidence_when_exact": 0.9,
        "confidence_when_off": 0.65,
    }


def test_nothing_to_compare_gives_no_figure() -> None:
    assert evals.agreement([]) is None


# --- running it ---------------------------------------------------------------------------------------------------


def test_a_case_without_quota_is_reported_as_such_and_not_scored() -> None:
    case = _cases()[0]

    assert evals.judge_case(_Failing(LLMExhausted("all out")), case)["status"] == "no_quota"
    assert evals.judge_case(_Failing(LLMRateLimitError("429")), case)["status"] == "no_quota"
    assert evals.judge_case(_Failing(LLMProviderError("503")), case)["status"] == "failed"


class _Failing:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, *args: object, **kwargs: object) -> object:
        raise self.error


def test_if_nothing_could_be_judged_no_figure_is_reported() -> None:
    cases = _cases()
    results = [evals.judge_case(_Failing(LLMExhausted("all out")), c) for c in cases]

    summary = evals.summarize(cases, results)

    assert summary["judged"] == 0 and summary["no_quota"] == 15
    assert summary["communication"] is None and summary["listening"] is None  # not 0 %, not anything


def test_a_partial_run_counts_only_the_cases_that_were_judged() -> None:
    cases = _cases()
    llm = ScriptedGrammarLLM()
    llm.judgements = [judgement(communication=c["expected"]["communication"], listening=c["expected"]["listening"], asked_to_repeat=bool(c.get("asked_to_repeat"))) for c in cases[:5]]
    results = [evals.judge_case(llm, c) for c in cases[:5]] + [{"status": "no_quota", "error": "ai_busy"} for _ in cases[5:]]

    summary = evals.summarize(cases, results)

    assert (summary["judged"], summary["no_quota"]) == (5, 10)
    assert summary["communication"]["cases"] == 5 and summary["communication"]["exact"] == 1.0  # a perfect judge, on 5 cases


def test_the_repeat_request_agrees_only_when_both_say_so() -> None:
    cases = _cases()
    repeat_case = next(c for c in cases if c.get("asked_to_repeat"))
    llm = ScriptedGrammarLLM()
    llm.judgements = [judgement(communication=5, listening=None, asked_to_repeat=True)]

    summary = evals.summarize([repeat_case], [evals.judge_case(llm, repeat_case)])

    assert summary["asked_to_repeat_agreed"] == "1/1" and summary["listening"] is None  # no score to compare


def test_a_hidden_score_is_still_counted_but_reported_apart() -> None:
    case = _cases()[0]
    llm = ScriptedGrammarLLM()
    llm.judgements = [judgement(communication=2, listening=2, confidence=0.3)]

    summary = evals.summarize([case], [evals.judge_case(llm, case)])

    assert summary["communication_hidden"] == 1 and summary["communication"]["cases"] == 1  # the cost of the honesty rule is visible


def test_without_yes_nothing_is_sent(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("the LLM chain must not even be built in a dry run")

    monkeypatch.setattr(chains, "analysis_llm", boom)
    monkeypatch.setattr(sys, "argv", ["run_judge_evals"])

    evals.main()

    assert "Nothing was sent" in capsys.readouterr().out


def test_a_real_run_writes_the_report_with_the_date_and_the_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = _cases()
    llm = ScriptedGrammarLLM()
    llm.judgements = [judgement(communication=c["expected"]["communication"], listening=c["expected"]["listening"], asked_to_repeat=bool(c.get("asked_to_repeat"))) for c in cases[:12]]
    llm.judgements += [LLMExhausted("out of quota")] * 3
    monkeypatch.setattr(chains, "analysis_llm", lambda cfg: llm)
    monkeypatch.setattr(evals, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_judge_evals", "--yes"])

    evals.main()

    files = list(tmp_path.glob("judges-*.jsonl"))
    assert len(files) == 1 and files[0].name.startswith("judges-20")  # dated
    lines = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert lines[0]["summary"]["judged"] == 12 and lines[0]["summary"]["no_quota"] == 3  # the quota failures are written down
    out = capsys.readouterr().out
    assert "PARTIAL" in out and "NOT yet reviewed" in out


def test_a_run_with_no_quota_at_all_exits_without_a_figure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    llm = ScriptedGrammarLLM()
    llm.judgements = [LLMExhausted("out of quota")] * 15
    monkeypatch.setattr(chains, "analysis_llm", lambda cfg: llm)
    monkeypatch.setattr(evals, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_judge_evals", "--yes"])

    with pytest.raises(SystemExit) as info:
        evals.main()

    out = capsys.readouterr().out
    assert info.value.code == 1 and "No quota today" in out and "exact" not in out
