"""Deciding if an answer is right.

Written answers (choice, fill, fix) are compared as normalised text with the accepted answers: case, spacing,
final punctuation and the kind of apostrophe do not matter. Spoken answers are compared word by word with the
sentence that had to be said, and must be closer to the right sentence than to the one with the mistake: the
speech-to-text writes what it heard, so a learner who repeats the mistake is not marked right.
"""

import re
from difflib import SequenceMatcher

from app.exercises.bank import Exercise

# A spoken sentence is accepted when this much of it matches the target (and it is closer to it than to the mistake).
SPEECH_MIN_RATIO = 0.85

# Speech-to-text writes "she's" where the bank has "she is" (or the reverse): both sides are expanded the same way.
_CONTRACTIONS = {
    "i'm": "i am", "you're": "you are", "he's": "he is", "she's": "she is", "it's": "it is", "we're": "we are",
    "they're": "they are", "that's": "that is", "there's": "there is", "what's": "what is", "i've": "i have",
    "you've": "you have", "we've": "we have", "they've": "they have", "i'll": "i will", "you'll": "you will",
    "don't": "do not", "doesn't": "does not", "didn't": "did not", "can't": "cannot", "won't": "will not",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not", "weren't": "were not", "haven't": "have not",
    "hasn't": "has not", "couldn't": "could not", "shouldn't": "should not", "wouldn't": "would not",
}


def normalize(text: str) -> str:
    """Lowercase, one kind of apostrophe, no punctuation, single spaces."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    return " ".join(text.split())


def _words(text: str) -> list[str]:
    expanded = " ".join(_CONTRACTIONS.get(token, token) for token in normalize(text).split())
    return expanded.split()


def check_text(exercise: Exercise, answer: str) -> bool:
    """Is a typed or chosen answer one of the accepted ones?"""
    given = normalize(answer)
    return bool(given) and any(given == normalize(accepted) for accepted in exercise.answers)


def speech_matches(exercise: Exercise, heard: str) -> bool:
    """Is what was heard the sentence of a speaking exercise (and not its mistaken version)?"""
    tokens = _words(heard)
    if not tokens:
        return False
    right = SequenceMatcher(None, tokens, _words(exercise.answers[0])).ratio()
    wrong = SequenceMatcher(None, tokens, _words(exercise.wrong)).ratio() if exercise.wrong else 0.0
    return right >= SPEECH_MIN_RATIO and right > wrong
