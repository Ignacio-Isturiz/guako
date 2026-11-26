"""The unified eval runner: cost gate, retries, failure reporting, grammar metrics and the consolidated report.

Every provider is simulated: a real run is a manual step (python -m scripts.run_evals <set> --yes).
"""

import json
from pathlib import Path

import pytest

from app.config import settings
from app.llm.errors import LLMAuthError, LLMOutputError, LLMProviderError
from app.providers import chains
from app.providers.errors import LLMExhausted
from scripts import run_evals
from scripts.evals import common, grammar, report
from scripts.evals.common import Plan, Tracker, classify_llm_failure, over_limit, with_retries
from tests.analysis_helpers import ScriptedGrammarLLM, err

NO_WAIT = {"waits": (0.0, 0.0, 0.0), "sleep": lambda s: None}


# --- retries and failures --------------------------------------------------------------------------------------


def test_a_transient_failure_is_retried_until_it_works() -> None:
    script = [LLMExhausted("all out"), LLMProviderError("503"), "ok"]

    def call() -> str:
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    result = with_retries(call, classify_llm_failure, **NO_WAIT)

    assert result.ok and result.value == "ok" and result.attempts == 3


def test_a_case_that_never_works_is_reported_with_its_reason_not_dropped() -> None:
    def call() -> None:
        raise LLMExhausted("every provider is out")

    result = with_retries(call, classify_llm_failure, **NO_WAIT)

    assert not result.ok and result.failure == "exhausted" and result.attempts == 4 and "every provider" in result.error


def test_a_bad_key_is_not_retried() -> None:
    calls = []

    def call() -> None:
        calls.append(1)
        raise LLMAuthError("bad key")

    assert with_retries(call, classify_llm_failure, **NO_WAIT).failure == "auth" and len(calls) == 1


def test_the_wait_honours_what_the_provider_asked_for_up_to_a_cap() -> None:
    waits: list[float] = []

    def call() -> None:
        raise LLMExhausted("busy", retry_after=500)

    with_retries(call, classify_llm_failure, waits=(1.0,), sleep=waits.append)

    assert waits == [common.MAX_PROVIDER_WAIT_S]


def test_an_invalid_model_answer_counts_as_bad_output() -> None:
    assert classify_llm_failure(LLMOutputError("not json", last_error="x", attempts=3)).reason == "bad_output"


# --- cost ------------------------------------------------------------------------------------------------------


def test_a_run_above_the_cost_limit_is_refused() -> None:
    assert over_limit([Plan("a", 1, 1.5), Plan("b", 1, 0.6)], 2.0) is not None
    assert over_limit([Plan("a", 1, 1.5)], 2.0) is None


def test_the_run_has_its_own_spending_cap_and_router_state() -> None:
    tracker = Tracker(settings, budget_usd=1.25, llm_order="groq,openai")

    assert tracker.cfg.paid_budget_usd == 1.25 and tracker.cfg.paid_budget_period == "total"
    assert tracker.cfg.llm_analysis_order == "groq,openai" and settings.llm_analysis_order != "" and tracker.cfg is not settings


def test_the_grammar_estimate_grows_with_the_repetitions() -> None:
    one, three = grammar.plan(settings, 1), grammar.plan(settings, 3)

    assert three.calls == 3 * one.calls == 120 and three.estimated_cost_usd == pytest.approx(3 * one.estimated_cost_usd)
    assert 0 < three.estimated_cost_usd < 2.0


def test_without_yes_nothing_is_sent(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("no chain may be built in a dry run")

    monkeypatch.setattr(chains, "build_llm", boom)
    monkeypatch.setattr(chains, "build_stt", boom)

    assert run_evals.main(["all"]) == 0
    out = capsys.readouterr().out
    assert "Nothing was sent" in out and "TOTAL estimated cost" in out


def test_with_yes_but_over_the_limit_nothing_is_sent(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(chains, "build_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))

    assert run_evals.main(["grammar", "--yes", "--max-cost", "0.000001"]) == 2
    assert "above the limit" in capsys.readouterr().out


# --- grammar metrics -------------------------------------------------------------------------------------------


def _flag(original: str, correction: str) -> dict:
    return {"original": original, "correction": correction}


def test_precision_and_recall_with_known_numbers() -> None:
    rows = [
        {"score": grammar.score_case([_flag("goed", "went")], [_flag("I goed", "I went")])},  # hit, right fix
        {"score": grammar.score_case([_flag("don't", "doesn't")], [_flag("don't", "do not"), _flag("coffee", "tea")])},  # hit, other fix, + 1 invented
        {"score": grammar.score_case([_flag("a", "an")], [])},  # missed
        {"score": grammar.score_case([], [_flag("rains", "rain")])},  # correct sentence, flagged
        {"score": grammar.score_case([], [])},  # correct sentence, clean
    ]

    m = grammar.metrics(rows)

    assert m["recall"] == pytest.approx(2 / 3, abs=1e-4)  # 2 of 3 real errors found
    assert m["precision"] == 0.5  # 2 of 4 flagged errors were real
    assert m["strict_recall"] == pytest.approx(1 / 3, abs=1e-4) and m["strict_precision"] == 0.25  # only one fix matches
    assert m["fix_accuracy"] == 0.5
    assert (m["correct_sentences"], m["correct_sentences_flagged"], m["false_positive_rate"]) == (2, 1, 0.5)


def test_one_flag_can_match_only_one_expected_error() -> None:
    score = grammar.score_case([_flag("I goed", "I went"), _flag("goed", "went")], [_flag("goed", "went")])

    assert score["matched"] == 1 and score["expected"] == 2


def test_failed_cases_are_counted_but_not_scored() -> None:
    rows = [{"score": grammar.score_case([_flag("goed", "went")], [_flag("goed", "went")])}, {"failure": "exhausted"}]

    m = grammar.metrics(rows)

    assert m["cases_scored"] == 1 and m["cases_failed"] == 1 and m["recall"] == 1.0


def test_variance_is_reported_as_median_and_range() -> None:
    per_repeat = [{"precision": 0.9, "recall": 0.8}, {"precision": 0.7, "recall": 0.9}, {"precision": 0.8, "recall": None}]

    spread = grammar.spread(per_repeat)

    assert spread["precision"] == {"median": 0.8, "min": 0.7, "max": 0.9, "values": [0.9, 0.7, 0.8]}
    assert spread["recall"]["values"] == [0.8, 0.9]  # a repetition without the figure is left out, not taken as 0
    assert spread["fix_accuracy"] is None


def test_a_grammar_run_goes_through_the_app_analysis_and_writes_every_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    llm = ScriptedGrammarLLM()
    cases = grammar.load_cases()[:3]
    # repetition 1: three answers; repetition 2: the first case never gets an answer (4 attempts), then two answers.
    llm.script = [[err("goed", "went")], [err("don't", "doesn't")], [], *[LLMExhausted("out")] * 4, [err("goed", "went")], [err("a", "b", confidence=0.2)]]
    monkeypatch.setattr(chains, "build_llm", lambda use, cfg, state: llm)
    monkeypatch.setattr(common, "RETRY_WAITS_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    tracker = Tracker(settings, 2.0)

    result = grammar.run(tracker, grammar.plan(settings, 2, 3), repeats=2, limit=3, log=lambda s: None)
    path = common.write_result(result, tmp_path)

    assert "(none: this is the first answer)" in llm.prompts[0]  # the production prompt, v2
    assert result["prompt_version"] == 2 and result["cases"] == 6 and result["failed"] == 1
    assert result["failure_reasons"] == {"exhausted": 1}
    failed = next(r for r in result["rows"] if r.get("failure"))
    assert failed["id"] == cases[0]["id"] and failed["repeat"] == 2 and failed["attempts"] == 4
    assert len(result["per_repeat"]) == 2 and result["per_repeat"][1]["cases_failed"] == 1
    # rep 1: gr_03's error was missed (2 of 3); rep 2: case 2 flagged the wrong place, case 3 only a low-confidence error.
    assert result["metrics"]["recall"]["values"] == [0.6667, 0.0]
    assert result["per_repeat"][1]["cases_scored"] == 2 and result["per_repeat"][1]["flagged_errors_unmatched"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["set"] == "grammar" and path.name.startswith("grammar-20")


# --- the consolidated report -----------------------------------------------------------------------------------


def test_the_report_says_what_was_not_measured(tmp_path: Path) -> None:
    text, data = report.build(tmp_path, reviews=[])

    for name in report.SETS:
        assert data["sets"][name] is None
    assert text.count("NO MEDIDO") == len(report.SETS)
    assert "0 of the 100" in text and "NOT MEASURED (no turn reviewed)" in text


def test_the_report_includes_failures_and_cost_of_the_latest_run(tmp_path: Path) -> None:
    rows = [{"score": grammar.score_case([_flag("goed", "went")], [_flag("goed", "went")])}, {"failure": "exhausted"}]
    per_repeat = [grammar.metrics(rows)]
    old = common.base_result("grammar", "20260101T000000Z-aaaaaa", "2026-01-01", Plan("grammar", 2, 0.01), rows,
                             prompt_version=1, repeats=1, unique_cases=2, per_repeat=per_repeat, metrics=grammar.spread(per_repeat),
                             actual_cost_usd=0.5, served_by={})  # fmt: skip
    new = {**old, "run_id": "20261125T000000Z-bbbbbb", "prompt_version": 2, "actual_cost_usd": 0.0123, "served_by": {"openai:gpt-4o-mini": 1}}
    common.write_result(old, tmp_path)
    common.write_result(new, tmp_path)

    text, data = report.build(tmp_path, reviews=[])

    assert data["sets"]["grammar"]["run_id"] == "20261125T000000Z-bbbbbb" and "rows" not in data["sets"]["grammar"]
    assert "fallidos: 1 (motivos: exhausted: 1)" in text and "$0.0123" in text and "openai:gpt-4o-mini (1)" in text
