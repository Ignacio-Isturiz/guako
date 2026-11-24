"""What the learner MEANT to say, checked in code before it is trusted.

A speech recognizer writes the words it thinks it heard, and a learner's pronunciation can make it write
another word that sounds alike ("to die" for "today"). Pronunciation is scored against a reference text,
so if the reference is the wrong word the real mistake is never seen. The LLM proposes the intended
sentence (see prompts/grammar_v2.txt); this module only accepts the proposal when it is a small,
word-for-word substitution, so a wrong guess can never rewrite what the learner said.
"""

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

# A recognition fix changes a word or two. Short answers are the common case ("to die" -> "today" is 2 of 7
# words), so a couple of words are always allowed; beyond that, more than this share of the words changed
# means the proposal is a rewrite, not a recognition fix.
MIN_ALLOWED_CHANGES = 2
MAX_CHANGED_FRACTION = 0.25


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text)


def _coincides_with_grammar(heard: str, intended: str, grammar_errors: Iterable[tuple[str, str]]) -> bool:
    """A replacement that is also a grammar correction ("doesn't" -> "didn't") is a grammar mistake of the
    learner, not a misrecognised word: scoring pronunciation against the corrected word would punish a
    grammar slip as if it were pronunciation."""
    h, i = " ".join(_words(heard)).lower(), " ".join(_words(intended)).lower()
    for original, correction in grammar_errors:
        o, c = " ".join(_words(original)).lower(), " ".join(_words(correction)).lower()
        if h and i and h in o and i in c:
            return True
    return False


def validated_fixes(
    transcript: str, intended: str, grammar_errors: Iterable[tuple[str, str]] = ()
) -> tuple[str, list[dict[str, str]]]:
    """(intended text, [{"heard", "intended"}]) if the proposal is acceptable, else ("", []).

    Accepted only when every difference is a word replaced by another word (no word added or removed) and
    few words changed (see MIN_ALLOWED_CHANGES and MAX_CHANGED_FRACTION). Replacements that match a grammar
    error in ``grammar_errors`` ((original, correction) pairs) are dropped: the learner's own words stay.
    An unchanged text also returns ("", []): there is nothing to fix and the transcript is used as is.
    """
    errors = list(grammar_errors)
    heard, meant = _words(transcript), _words(intended)
    if not heard or not meant:
        return "", []
    matcher = SequenceMatcher(None, [w.lower() for w in heard], [w.lower() for w in meant], autojunk=False)
    fixes: list[dict[str, str]] = []
    out: list[str] = []
    changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(heard[i1:i2])
            continue
        if tag != "replace":  # a word added or dropped: the learner did not say that
            return "", []
        heard_part, meant_part = " ".join(heard[i1:i2]), " ".join(meant[j1:j2])
        if _coincides_with_grammar(heard_part, meant_part, errors):
            out.extend(heard[i1:i2])  # keep what the learner said; it does not count as a change
            continue
        changed += max(i2 - i1, j2 - j1)
        out.extend(meant[j1:j2])
        fixes.append({"heard": heard_part, "intended": meant_part})
    if not fixes or changed > max(MIN_ALLOWED_CHANGES, MAX_CHANGED_FRACTION * len(heard)):
        return "", []
    return " ".join(out), fixes
