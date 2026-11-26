"""The guard of each tutor reply: what the learner said and what Guako answers, checked before it is spoken.

Runs after the LLM and before the voice, in this order:
1. prompt injection: the learner's words are scanned for attempts to give the model orders (only recorded:
   the prompt already treats them as speech, never as instructions);
2. clean-up: the reply is read aloud, so markdown and emojis are removed;
3. instruction leak: if the reply repeats a passage of the tutor's instructions, it is replaced;
4. moderation (one request for both texts): a harmful learner message or a harmful reply is answered with a
   fixed safe line; self-harm gets a caring line instead of "let's change the subject".

Every finding becomes an event (kind, who, categories: never the text) that the API saves in
``safety_events`` and that Langfuse shows on the turn.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from app import observability
from app.config import settings
from app.prompts import template_text
from app.safety.moderation import ModerationUnavailable, Moderator, Verdict, get_moderator
from app.safety.text import injection_signals

logger = logging.getLogger("app.safety")

# Fixed lines, short and simple enough for any level (they are spoken by the tutor's voice).
SAFE_REPLIES = {
    "self_harm": "I'm really sorry you feel this way. Please talk to someone you trust or a local helpline today. "
    "I'm here if you want to keep chatting.",
    "learner_flagged": "Let's keep our chat kind and respectful. Shall we go back to our scene?",
    "tutor_flagged": "Sorry, let me start again. Where were we in our scene?",
    "leak": "I'd rather stay in our scene. So, where were we?",
    "unchecked": "Let's get back to our scene. What would you like to say?",
}

# Passages of 8 words in a row shared with the instructions count as a leak.
_LEAK_WINDOW = 8
_WORD = re.compile(r"[a-z0-9']+")
_MARKDOWN = re.compile(r"[*_#`~|>]+|^\s*[-•]\s+", re.MULTILINE)
_SPACES = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([?.!,;:])")


@dataclass
class GuardResult:
    reply: str
    events: list[dict] = field(default_factory=list)

    @property
    def replaced(self) -> bool:
        return any(event.get("replaced") for event in self.events)


def clean_spoken(text: str) -> str:
    """The reply as it will be spoken: no markdown, no emojis, single spaces."""
    without_marks = _MARKDOWN.sub("", text)
    kept = "".join(
        ch for ch in without_marks
        if unicodedata.category(ch) not in ("So", "Cs", "Co") and not 0xFE00 <= ord(ch) <= 0xFE0F
    )  # fmt: skip
    return _SPACE_BEFORE_PUNCT.sub(r"\1", _SPACES.sub(" ", kept)).strip()


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    return {tuple(words[i : i + _LEAK_WINDOW]) for i in range(len(words) - _LEAK_WINDOW + 1)}


@lru_cache
def _instruction_shingles(prompt_name: str, version: int) -> frozenset[tuple[str, ...]]:
    # The template WITHOUT the scene and the part: echoing the learner's own scene is not a leak.
    template = re.sub(r"\{[a-z_]+\}", " ", template_text(prompt_name, version))
    return frozenset(_shingles(template))


def leaks_instructions(reply: str, prompt_name: str, version: int) -> bool:
    return bool(_shingles(reply) & _instruction_shingles(prompt_name, version))


def _event(kind: str, source: str, *, categories: list[str] | None = None, replaced: bool = False) -> dict:
    return {"kind": kind, "source": source, "categories": categories or [], "replaced": replaced}


def guard_reply(
    learner_text: str | None,
    reply: str,
    *,
    prompt: tuple[str, int],
    moderator: Moderator | None = None,
) -> GuardResult:
    """The reply to speak, and what was found. ``prompt`` = (name, version) of the tutor's instructions."""
    moderator = moderator or get_moderator()
    events: list[dict] = []

    signals = injection_signals(learner_text)
    if signals:
        events.append(_event("injection_attempt", "learner", categories=signals))

    final = clean_spoken(reply) or SAFE_REPLIES["unchecked"]
    if leaks_instructions(final, *prompt):
        events.append(_event("instruction_leak", "tutor", replaced=True))
        final = SAFE_REPLIES["leak"]

    with observability.span("moderation") as traced:
        try:
            learner_verdict, reply_verdict = moderator.check([learner_text or "", final])
        except ModerationUnavailable as exc:
            logger.warning("moderation_unavailable error=%s fail_closed=%s", exc, settings.moderation_fail_closed)
            learner_verdict = reply_verdict = Verdict(checked=False)
            events.append(_event("moderation_unavailable", "service", replaced=settings.moderation_fail_closed))
            if settings.moderation_fail_closed:
                final = SAFE_REPLIES["unchecked"]
        traced.update(
            output={
                "learner": list(learner_verdict.categories) if learner_verdict.flagged else "ok",
                "tutor": list(reply_verdict.categories) if reply_verdict.flagged else "ok",
                "checked": learner_verdict.checked,
            }
        )

    if learner_verdict.flagged:
        events.append(_event("moderation", "learner", categories=list(learner_verdict.categories), replaced=True))
        final = SAFE_REPLIES["self_harm" if learner_verdict.self_harm else "learner_flagged"]
    elif reply_verdict.flagged:
        events.append(_event("moderation", "tutor", categories=list(reply_verdict.categories), replaced=True))
        final = SAFE_REPLIES["tutor_flagged"]

    if events:
        observability.score("safety_events", len(events), comment=",".join(e["kind"] for e in events))
    for event in events:
        logger.warning(
            "safety_event kind=%s source=%s categories=%s replaced=%s",
            event["kind"], event["source"], ",".join(event["categories"]), event["replaced"],
        )  # fmt: skip
    return GuardResult(final, events)


def check_scene(*texts: str | None, moderator: Moderator | None = None) -> list[dict]:
    """The scene and the part of a new session: an order to the model or harmful content have no place there.

    Returns the events found (empty = fine). The moderation failing does not block creating a session.
    """
    moderator = moderator or get_moderator()
    present = [text for text in texts if text and text.strip()]
    events = [_event("injection_attempt", "scene", categories=s) for s in (injection_signals(t) for t in present) if s]
    try:
        verdicts = moderator.check(present)
    except ModerationUnavailable as exc:
        logger.warning("moderation_unavailable scene error=%s", exc)
        verdicts = []
    events += [_event("moderation", "scene", categories=list(v.categories)) for v in verdicts if v.flagged]
    return events
