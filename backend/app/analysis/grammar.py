"""Grammar analysis of one turn: structured LLM output, then only the confident errors are kept."""

from enum import Enum

from pydantic import BaseModel, Field

from app.analysis.intent import validated_fixes
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
    # The sentence the learner meant (only misrecognised words changed); checked by analysis/intent.py.
    intended_text: str = ""


def analyze_grammar(llm: LLMProvider, transcript: str, context: str = "") -> dict:
    """One LLM call (may raise LLMError). Returns the JSON stored in ``turn_analyses.result``.

    ``context`` is the tutor's previous message; it helps tell which words were misrecognised.
    """
    prompt = load_prompt("grammar", 2, text=transcript, context=context.strip() or "(none: this is the first answer)")
    analysis = llm.generate(prompt, TurnGrammarAnalysis)
    assert isinstance(analysis, TurnGrammarAnalysis)
    shown = [e for e in analysis.errors if e.confidence >= MIN_CONFIDENCE]
    # All the errors count here, even the low-confidence ones that are not shown: a fix that is really a
    # grammar correction must not become the pronunciation reference.
    intended_text, heard_fixes = validated_fixes(
        transcript, analysis.intended_text, [(e.original, e.correction) for e in analysis.errors]
    )
    return {
        "intended_text": intended_text,  # "" = no fix: the transcript is what was meant
        "heard_fixes": heard_fixes,
        "errors": [e.model_dump(mode="json") for e in shown],
        "discarded_low_confidence": len(analysis.errors) - len(shown),
        "min_confidence": MIN_CONFIDENCE,
    }
