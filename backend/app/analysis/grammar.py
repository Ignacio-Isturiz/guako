"""Grammar analysis of one turn: structured LLM output, then only the confident errors are kept."""

from enum import Enum

from pydantic import BaseModel, Field

from app.llm.base import LLMProvider
from app.prompts import load_prompt

# Honesty rule: a correction the analyser is not sure about is never shown to the learner.
# 0.7 is a starting value, not a calibrated one: below it the prompt tells the model it is
# guessing. Re-tune it with evals/grammar (the eval report counts how many errors each cut-off drops).
MIN_CONFIDENCE = 0.7


class GrammarErrorType(str, Enum):
    """Closed set of error types; anything else the model invents fails validation (and is retried)."""

    VERB_TENSE = "verb_tense"
    SUBJECT_VERB_AGREEMENT = "subject_verb_agreement"
    VERB_FORM = "verb_form"
    ARTICLE = "article"
    PREPOSITION = "preposition"
    PLURAL_NOUN = "plural_noun"
    PRONOUN = "pronoun"
    WORD_ORDER = "word_order"
    VOCABULARY = "vocabulary"
    OTHER = "other"


class TurnGrammarError(BaseModel):
    original: str
    correction: str
    error_type: GrammarErrorType
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)


class TurnGrammarAnalysis(BaseModel):
    errors: list[TurnGrammarError]


def analyze_grammar(llm: LLMProvider, transcript: str) -> dict:
    """One LLM call (may raise LLMError). Returns the JSON stored in ``turn_analyses.result``."""
    prompt = load_prompt("grammar", 1, text=transcript)
    analysis = llm.generate(prompt, TurnGrammarAnalysis)
    assert isinstance(analysis, TurnGrammarAnalysis)
    shown = [e for e in analysis.errors if e.confidence >= MIN_CONFIDENCE]
    return {
        "errors": [e.model_dump(mode="json") for e in shown],
        "discarded_low_confidence": len(analysis.errors) - len(shown),
        "min_confidence": MIN_CONFIDENCE,
    }
