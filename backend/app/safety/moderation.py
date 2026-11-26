"""Content moderation: is a text harmful (hate, harassment, sexual, self-harm, violence...)?

Uses OpenAI's moderation endpoint, which is free and reuses OPENAI_API_KEY. Several texts go in ONE request
(the learner's words and the tutor's reply), so a turn pays a single round trip.

Without the key (tests, a clone without OpenAI) the NullModerator answers "not checked": the app works the
same, only unmoderated. What to do with a verdict is decided by app.safety.guard, not here.
"""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from app.config import settings

logger = logging.getLogger("app.safety")

# Categories that call for a caring answer instead of a plain "let's change the subject".
SELF_HARM = frozenset({"self-harm", "self-harm/intent", "self-harm/instructions"})


@dataclass(frozen=True)
class Verdict:
    flagged: bool = False
    categories: tuple[str, ...] = field(default_factory=tuple)
    checked: bool = True  # False: nobody looked at it (moderation off or failed)

    @property
    def self_harm(self) -> bool:
        return bool(SELF_HARM.intersection(self.categories))


class ModerationUnavailable(Exception):
    """The moderation service did not answer (timeout, network, quota, bad key)."""


class Moderator(Protocol):
    def check(self, texts: list[str]) -> list[Verdict]:
        """One verdict per text, in the same order."""
        ...


class NullModerator:
    """Moderation off: nothing is checked."""

    def check(self, texts: list[str]) -> list[Verdict]:
        return [Verdict(checked=False) for _ in texts]


class OpenAIModerator:
    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        import openai

        self.model = model
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def check(self, texts: list[str]) -> list[Verdict]:
        # An empty text has nothing to moderate (and the API refuses it): it is answered here.
        to_send = [(i, text) for i, text in enumerate(texts) if text and text.strip()]
        verdicts = [Verdict() for _ in texts]
        if not to_send:
            return verdicts
        try:
            response = self._client.moderations.create(model=self.model, input=[text for _, text in to_send])
        except Exception as exc:
            raise ModerationUnavailable(type(exc).__name__) from exc
        for (i, _), result in zip(to_send, response.results, strict=True):
            flags = result.categories.model_dump(by_alias=True)
            categories = tuple(sorted(name for name, on in flags.items() if on))
            verdicts[i] = Verdict(flagged=bool(result.flagged), categories=categories)
        return verdicts


@lru_cache
def get_moderator() -> Moderator:
    key = settings.openai_api_key.get_secret_value().strip() if settings.openai_api_key else ""
    if not settings.moderation_enabled or not key:
        logger.info("moderation_off reason=%s", "disabled" if not settings.moderation_enabled else "no_openai_key")
        return NullModerator()
    return OpenAIModerator(key, settings.moderation_model, settings.moderation_timeout_seconds)
