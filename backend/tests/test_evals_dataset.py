import json
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1] / "evals" / "grammar"


def _load(name: str) -> list[dict]:
    lines = (EVALS / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_grammar_cases_are_well_formed() -> None:
    cases = _load("cases.jsonl")
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        for err in c["expected_errors"]:
            assert err["original"] in c["text"], c["id"]
            assert err["correction"] != err["original"], c["id"]
    assert any(not c["expected_errors"] for c in cases)


def test_pronunciation_cases_are_well_formed() -> None:
    cases = _load("pronunciation_cases.jsonl")
    assert cases
    for c in cases:
        assert all(w.lower() in c["text"].lower() for w in c["target_words"]), c["id"]
