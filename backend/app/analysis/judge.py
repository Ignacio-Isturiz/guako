"""The judge of one turn: "darse a entender" (communication) and "listening", in ONE LLM call.

Two dimensions, one call: one rubric prompt, one confidence, one place to calibrate (the evals of
evals/judges). The call goes through the router with the "analysis" use, never straight to a provider.

HONESTY RULE. A judge that is not sure must not put a number in front of the learner:
- the judge reports a ``confidence`` (0-1) for each score;
- it is capped by how reliable the transcript is (a recognizer that was unsure, or text that needed a
  recognition fix, means the judge may be scoring recognition errors, not the learner);
- below MIN_JUDGE_CONFIDENCE the result is stored (the evals need it) but marked ``hidden`` and the report
  does not show that score: it counts the turn as not measured.
MIN_JUDGE_CONFIDENCE and the reliability cut-offs are STARTING values, not calibrated: the judge evals
(evals/judges) are what should retune them.
"""

import re
from typing import Any

from pydantic import BaseModel, Field

from app.llm.base import LLMProvider
from app.prompts import load_prompt

# Below this, the score is not shown to the learner.
MIN_JUDGE_CONFIDENCE = 0.6
# Fewer words than this and the turn is trivial ("yes", "me too"): no judge call, nothing to measure.
MIN_JUDGED_WORDS = 3
FILLER_WORDS = frozenset({"um", "uh", "uhm", "hmm", "mm", "mmm", "ah", "eh", "er", "erm"})

# Transcript reliability from the recognizer's own numbers (exp of the average log-probability of the words,
# and the probability that there is no speech). Cut-offs are starting values, from two audios only.
RELIABILITY_HIGH_AT = 0.75
RELIABILITY_MEDIUM_AT = 0.5
NO_SPEECH_LOW_ABOVE = 0.5
# The judge's confidence can never exceed this for each reliability. "unknown" = the provider sent nothing:
# no cap, and no invented number either.
CONFIDENCE_CAP = {"high": 1.0, "medium": 0.8, "low": 0.55, "unknown": 1.0}

MAX_TUTOR_CHARS = 500
MAX_TOPIC_CHARS = 200
# v2 (after the first eval): "communication" no longer mixes in whether the answer is on topic, a request to
# repeat is judged by its clarity, the examples of the descriptors are NOT sentences of evals/judges/cases.jsonl
# (a test guards that), and the rationale must describe the text instead of repeating the rubric. v1 is kept in
# app/prompts so the two eval runs can be compared.
# v3: v2 fixed "communication" but wrote about the tutor's question and "off topic" inside that dimension, and the model
# carried that over to "listening", which collapsed (79 % -> 14 % exact). v3 only asks it to read the sentence ON ITS OWN,
# which keeps both dimensions apart. v1 and v2 stay in app/prompts to compare the runs.
PROMPT_VERSION = 3

_LANGUAGES = {"es": "Spanish", "en": "English"}


class JudgedDimension(BaseModel):
    score: int = Field(ge=1, le=5)
    rationale: str = Field(max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class TurnJudgement(BaseModel):
    communication: JudgedDimension
    listening: JudgedDimension | None = None
    # The learner said they did not understand or asked for a repeat: a request, not a wrong answer.
    asked_to_repeat: bool = False


def content_words(text: str) -> int:
    """Words that carry something: hesitation sounds do not count."""
    return sum(1 for w in re.findall(r"[\w']+", text.lower()) if w not in FILLER_WORDS)


def is_trivial(transcript: str) -> bool:
    return content_words(transcript) < MIN_JUDGED_WORDS


def transcript_reliability(confidence: float | None, no_speech_prob: float | None, fixes: int = 0) -> str:
    """high / medium / low / unknown, from what the recognizer reported and from the fixes we had to make."""
    if confidence is None and no_speech_prob is None:
        level = "unknown"
    elif confidence is None:
        level = "medium"
    elif confidence >= RELIABILITY_HIGH_AT:
        level = "high"
    elif confidence >= RELIABILITY_MEDIUM_AT:
        level = "medium"
    else:
        level = "low"
    if no_speech_prob is not None and no_speech_prob > NO_SPEECH_LOW_ABOVE:
        level = "low"
    if fixes:  # a word was replaced because the recognizer wrote another one: the text was wrong somewhere
        level = {"high": "medium", "unknown": "medium"}.get(level, "low")
    return level


_RELIABILITY_NOTES = {
    "low": (
        "\nThe transcript has LOW reliability: the recognizer was unsure, so some words may be wrong because of "
        "how the learner pronounced them, not because of what they chose to say. Judge the meaning you can infer, "
        "do not penalize garbled wording that looks like a recognition error, and lower your confidence.\n"
    ),
    "medium": (
        "\nThe transcript has MEDIUM reliability: a word or two may have been misrecognised. Do not penalize "
        "wording that looks like a recognition error.\n"
    ),
}

_LISTENING_BLOCK = (
    '\nDIMENSION "listening": did the answer have to do with what the tutor just said or asked? (Evidence that the '
    "learner understood the tutor.)\n"
    "5 = Answers directly, or follows exactly the point the tutor raised (including a clarifying question about it).\n"
    "4 = Answers, but only part of it or indirectly; clearly relevant.\n"
    "3 = Related to the topic, but does not answer what was asked.\n"
    "2 = Barely related: the learner seems to have caught only a word.\n"
    "1 = Unrelated, or answers a different question.\n"
    'If the learner says they did not understand or asks the tutor to repeat or explain ("sorry?", "can you repeat '
    'that?"), set "asked_to_repeat" to true and "listening" to null: that is a request, not a wrong answer.\n'
)
_NO_LISTENING_BLOCK = '\nSet "listening" to null and "asked_to_repeat" to false: there is no previous tutor message to compare with.\n'


def build_prompt(ctx: dict[str, Any], want_listening: bool, intended: dict | None) -> str:
    fixes = (intended or {}).get("fixes") or []
    meant = (
        f'\nWhat the learner most likely MEANT (the recognizer wrote some words differently): """{intended["text"]}"""\n'
        if intended and intended.get("text")
        else ""
    )
    reliability = transcript_reliability(ctx.get("stt_confidence"), ctx.get("stt_no_speech_prob"), len(fixes))
    return load_prompt(
        "judge",
        PROMPT_VERSION,
        level=ctx.get("level") or "unknown",
        topic=(ctx.get("topic") or "free conversation")[:MAX_TOPIC_CHARS],
        tutor=(ctx.get("tutor_prev") or "")[:MAX_TUTOR_CHARS] or "(none)",
        learner=ctx["transcript"],
        meant_block=meant,
        reliability_note=_RELIABILITY_NOTES.get(reliability, ""),
        listening_block=_LISTENING_BLOCK if want_listening else _NO_LISTENING_BLOCK,
        rationale_language=_LANGUAGES.get(ctx.get("feedback_language", "es"), "Spanish"),
    )


def _dimension_result(judged: JudgedDimension, reliability: str) -> dict[str, Any]:
    confidence = min(judged.confidence, CONFIDENCE_CAP[reliability])
    return {
        "score": judged.score,
        "rationale": judged.rationale.strip(),
        "judge_confidence": judged.confidence,
        "confidence": round(confidence, 3),
        "reliability": reliability,
        "hidden": confidence < MIN_JUDGE_CONFIDENCE,  # stored for the evals, never shown to the learner
        "asked_to_repeat": False,
    }


def judge_turn(llm: LLMProvider, ctx: dict[str, Any], want_listening: bool, intended: dict | None = None) -> dict[str, dict | None]:
    """One LLM call (may raise LLMError). Returns the result of each dimension, ready for turn_analyses."""
    judgement = llm.generate(build_prompt(ctx, want_listening, intended), TurnJudgement)
    assert isinstance(judgement, TurnJudgement)
    fixes = (intended or {}).get("fixes") or []
    reliability = transcript_reliability(ctx.get("stt_confidence"), ctx.get("stt_no_speech_prob"), len(fixes))

    listening: dict | None = None
    if want_listening:
        if judgement.asked_to_repeat:
            listening = {"score": None, "asked_to_repeat": True, "hidden": False, "reliability": reliability}
        elif judgement.listening is not None:
            listening = _dimension_result(judgement.listening, reliability)
    return {"communication": _dimension_result(judgement.communication, reliability), "listening": listening}
