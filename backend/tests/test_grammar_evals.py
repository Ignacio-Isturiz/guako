from app.llm.schemas import GrammarError
from scripts.run_grammar_evals import score_case, summarize


def _err(original: str, correction: str) -> GrammarError:
    return GrammarError(original=original, correction=correction, error_type="x", explanation="y")


def test_score_detects_location_and_fix() -> None:
    expected = [{"original": "goed", "correction": "went"}]
    score = score_case(expected, [_err("I goed", "I went")])
    assert score == {"expected": 1, "detected": 1, "correct_fix": 1, "extra": 0}


def test_score_wrong_fix_and_extra() -> None:
    expected = [{"original": "goed", "correction": "went"}]
    score = score_case(expected, [_err("goed", "gone"), _err("market", "shop")])
    assert score["detected"] == 1 and score["correct_fix"] == 0 and score["extra"] == 1


def test_summarize_false_positive_rate() -> None:
    rows = [
        {"score": {"expected": 0, "detected": 0, "correct_fix": 0, "extra": 1}},
        {"score": {"expected": 0, "detected": 0, "correct_fix": 0, "extra": 0}},
        {"score": {"expected": 2, "detected": 1, "correct_fix": 1, "extra": 0}},
    ]
    s = summarize(rows)
    assert s["false_positive_rate"] == 0.5 and s["recall"] == 0.5
