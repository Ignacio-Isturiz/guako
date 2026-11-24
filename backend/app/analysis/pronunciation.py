"""Pronunciation analysis of one turn: what text and how much audio to send, and what to store.

REFERENCE TEXT. Azure scores audio against a text you give it. The only text we have is Whisper's
transcript, which is what the learner SAID, not what they MEANT to say. Whisper leans on a language
model, so it usually writes the intended word even when it was pronounced badly ("sink" -> "think"),
and then Azure compares the audio with that word and scores the difference. Limitation: when the
sound is clear enough that Whisper writes exactly what was said (a real "sink"), the reference
matches the audio and the word scores well, so some mispronunciations go unnoticed. Scores are
therefore a lower bound on what a human teacher would flag, never an accusation. We do not use the
grammar-corrected text as reference: that would punish grammar mistakes as pronunciation.

Long turns. Azure assesses at most 30 s of audio per call. A longer turn is cut to its first
``provider.max_audio_seconds`` seconds, and the reference text is cut to the words (from Whisper's
timings) that end inside that span; the report says the turn was only partly assessed.
"""

from dataclasses import dataclass
from typing import Any

from app.pronunciation.schemas import PronunciationResult


@dataclass(frozen=True)
class AssessmentPlan:
    reference_text: str
    audio_seconds: float  # seconds of audio that will be sent (and counted against the quota)
    truncated: bool
    fixes: tuple[dict, ...] = ()  # recognition fixes applied to the reference: {"heard", "intended"}


def plan_assessment(
    transcript: str,
    word_timestamps: list[dict] | None,
    audio_seconds: float,
    max_seconds: float,
    intended: dict | None = None,
) -> AssessmentPlan | None:
    """None when a long turn cannot be cut consistently (no word timings): the caller fails it.

    ``intended`` = {"text", "fixes"} from the grammar analysis: what the learner meant when the recognizer
    wrote another word that sounds alike. It is used as the reference only for turns sent whole; a long turn
    is cut by the recognizer's word timings, which the fixed text no longer lines up with.
    """
    timings = word_timestamps or []
    if audio_seconds <= 0:
        # Unknown length: take the end of the last word, or assume the most that could be sent.
        audio_seconds = max((float(w["end"]) for w in timings), default=max_seconds)
    if audio_seconds <= max_seconds:
        if intended and intended.get("text"):
            return AssessmentPlan(intended["text"], audio_seconds, truncated=False, fixes=tuple(intended["fixes"]))
        return AssessmentPlan(" ".join(transcript.split()), audio_seconds, truncated=False)

    kept = [str(w["word"]).strip() for w in timings if float(w["end"]) <= max_seconds]
    if not kept:
        return None
    return AssessmentPlan(" ".join(kept), max_seconds, truncated=True)


def stored_result(result: PronunciationResult, plan: AssessmentPlan) -> dict[str, Any]:
    """What goes into turn_analyses.result. Azure's own fluency/completeness are not kept: against
    a reference taken from the transcript they say nothing (completeness is always ~100), and
    fluency is measured by our own analysis."""
    return {
        "accuracy_score": result.accuracy_score,
        "pron_score": result.pron_score,
        "words": [w.model_dump() for w in result.words],
        "assessed_seconds": round(plan.audio_seconds, 2),
        "truncated": plan.truncated,
        "reference_text": plan.reference_text,
        "heard_fixes": list(plan.fixes),  # words the recognizer wrote that we scored as something else
    }


def empty_result() -> dict[str, Any]:
    """The learner said nothing, so there is nothing to assess (and nothing was sent)."""
    return {"accuracy_score": None, "pron_score": None, "words": [], "assessed_seconds": 0.0, "truncated": False}
