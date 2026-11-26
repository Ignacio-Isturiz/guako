"""The human-review tool: one turn at a time, answers saved as given, resumable, and the agreement per dimension."""

from pathlib import Path

from scripts.evals import review


def _turn(turn_id: int, score: int = 4) -> dict:
    return {
        "turn_id": turn_id,
        "session_id": 1,
        "turn_number": turn_id,
        "tutor": "What did you do last weekend?",
        "learner": "I goed to the beach.",
        "analyses": {
            "grammar": {"errors": [{"original": "goed", "correction": "went", "error_type": "verb_tense", "confidence": 0.95}]},
            "communication": {"score": score, "rationale": "Clear.", "confidence": 0.8, "hidden": False},
        },
    }


def _answers(*items: str):  # noqa: ANN202
    queue = list(items)
    return lambda prompt: queue.pop(0)


def test_each_answer_is_saved_and_a_disagreement_records_the_person_score(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    out: list[str] = []

    saved = review.review([_turn(1)], ask=_answers("y", "n", "2", "too generous"), say=out.append, path=path)

    rows = review.load_reviews(path)
    assert saved == 2 and [(r["dimension"], r["agree"]) for r in rows] == [("grammar", True), ("communication", False)]
    assert rows[1]["system_score"] == 4 and rows[1]["human_score"] == 2 and rows[1]["note"] == "too generous"
    assert any("I goed to the beach." in line for line in out) and any("'goed' -> 'went'" in line for line in out)


def test_quitting_keeps_what_was_answered_and_the_next_session_resumes(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    turns = [_turn(1), _turn(2)]

    review.review(turns, ask=_answers("y", "q"), say=lambda s: None, path=path)
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return "y"

    review.review(turns, ask=ask, say=lambda s: None, path=path)

    pairs = [(r["turn_id"], r["dimension"]) for r in review.load_reviews(path)]
    assert pairs == [(1, "grammar"), (1, "communication"), (2, "grammar"), (2, "communication")]  # nothing asked twice
    assert len(asked) == 3


def test_skip_saves_nothing_and_invalid_input_is_asked_again(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"

    review.review([_turn(1)], ask=_answers("maybe", "s", "s"), say=lambda s: None, path=path)

    assert review.load_reviews(path) == []


def test_agreement_per_dimension() -> None:
    reviews = [
        {"turn_id": 1, "dimension": "communication", "agree": True, "system_score": 4, "human_score": 4},
        {"turn_id": 2, "dimension": "communication", "agree": False, "system_score": 4, "human_score": 2},
        {"turn_id": 3, "dimension": "communication", "agree": False, "system_score": 3, "human_score": None},
        {"turn_id": 1, "dimension": "grammar", "agree": False, "system_score": None, "human_score": None},
        {"turn_id": 1, "dimension": "grammar", "agree": True, "system_score": None, "human_score": None},  # changed mind
    ]

    summary = review.summarize(reviews)

    communication = summary["dimensions"]["communication"]
    assert summary["turns_reviewed"] == 3 and summary["target_turns"] == 100
    assert communication["reviewed"] == 3 and communication["agreement"] == 0.333
    assert (communication["with_scores"], communication["exact"], communication["bias"]) == (2, 0.5, 1.0)
    assert summary["dimensions"]["grammar"] == {"reviewed": 1, "agreement": 1.0}  # the later answer wins
    assert summary["dimensions"]["listening"] is None
    assert any("NOT MEASURED" in line for line in review.describe(summary))
