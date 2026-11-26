"""The WER eval: the declared normalization, the pooled WER, and a run with a simulated recognizer."""

from pathlib import Path

import pytest

from app.config import settings
from app.providers import chains
from app.stt.errors import STTError
from app.stt.schemas import TranscriptionResult
from scripts.evals import common, wer
from scripts.evals.common import Tracker


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Yes, I do.", "yes i do"),  # case and punctuation
        ("I went to Medellín", "i went to medellin"),  # diacritics
        ("I don't know", "i do not know"),  # contractions
        ("I'm sure it's fine, isn't it?", "i am sure it is fine is not it"),
        ("I can't and I won't", "i can not and i will not"),
        ("John's car", "johns car"),  # a possessive only loses the apostrophe
        ("Let's go", "let us go"),
        ("I have 3 cats", "i have three cats"),  # numbers
        ("about 25 or 1205", "about twenty five or one thousand two hundred five"),
        ("at 8:30 or 9:00 or 7:05", "at eight thirty or nine or seven oh five"),
        ("eight-thirty", "eight thirty"),  # hyphens split words
        ("Um, I think, uh, yes", "i think yes"),  # fillers
        ("I’m here", "i am here"),  # curly apostrophe
    ],
)
def test_normalization(raw: str, normalized: str) -> None:
    assert wer.normalize(raw) == normalized


def test_reference_and_transcript_written_differently_but_said_the_same_have_no_error() -> None:
    reference = "I am not sure, but I think the train leaves at nine, so we should arrive around eight-thirty."
    heard = "I'm not sure but I think the train leaves at 9 so we should arrive around 8:30"

    assert wer.measure([(wer.normalize(reference), wer.normalize(heard))])["wer"] == 0.0


def test_the_global_wer_pools_the_words_instead_of_averaging_audios() -> None:
    pairs = [("yes i do", "yes i did"), ("one two three four five six seven eight nine ten", "one two three four five six seven eight nine ten")]

    result = wer.measure(pairs)

    assert result["wer"] == pytest.approx(1 / 13, abs=1e-4)  # 1 error in 13 words, not the mean of 33 % and 0 %
    assert (result["substitutions"], result["deletions"], result["insertions"]) == (1, 0, 0)


def test_number_words() -> None:
    assert [wer.number_to_words(n) for n in (0, 13, 40, 99, 100, 2026)] == [
        "zero", "thirteen", "forty", "ninety nine", "one hundred", "two thousand twenty six",
    ]  # fmt: skip


def test_the_manifest_says_who_recorded_and_their_accent() -> None:
    rows = wer.load_manifest()

    assert len(rows) == 20 and all(r["speaker"] != "unknown" and r["accent"] != "unknown" for r in rows)
    assert all((wer.AUDIO_DIR / r["file"]).is_file() for r in rows)


class _FakeSTT:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers

    def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
        answer = self.answers[Path(audio_path).name]
        if isinstance(answer, Exception):
            raise answer
        return TranscriptionResult(text=str(answer), words=[])


def test_a_run_reports_each_audio_the_failures_and_that_one_speaker_cannot_show_fairness(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = wer.load_manifest()[:3]
    answers: dict[str, object] = {manifest[0]["file"]: manifest[0]["text"], manifest[1]["file"]: "I like coffee a lot", manifest[2]["file"]: STTError("bad key", kind="auth")}
    monkeypatch.setattr(chains, "build_stt", lambda cfg, state: _FakeSTT(answers))
    monkeypatch.setattr(common.time, "sleep", lambda s: None)

    result = wer.run(Tracker(settings, 2.0), wer.plan(settings, 1, 3), limit=3, log=lambda s: None)

    assert result["cases"] == 3 and result["failed"] == 1 and result["failure_reasons"] == {"auth": 1}
    assert [r.get("wer") for r in result["rows"][:2]] == [0.0, 0.0]
    m = result["metrics"]
    assert m["global"]["audios"] == 2 and m["global"]["wer"] == 0.0 and "short_clean" in m["by_condition"]
    assert "cannot be compared across accents" in m["fairness_note"]
    assert any("NOTE" in line for line in wer.describe(result))


def test_audio_without_a_reference_is_listed_not_used() -> None:
    assert any(name.startswith("WhatsApp") for name in wer.unlisted_audio(wer.load_manifest()))
