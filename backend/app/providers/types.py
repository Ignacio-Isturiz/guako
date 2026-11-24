"""Plain types shared by the router pieces (no I/O, no provider SDKs)."""

from dataclasses import dataclass
from enum import Enum


class FailureKind(str, Enum):
    """Why a provider call failed, as far as the router cares."""

    RATE_LIMITED = "rate_limited"  # 429: quota or rate limit
    UNAVAILABLE = "unavailable"  # 503, 5xx, network
    TIMEOUT = "timeout"
    AUTH = "auth"  # bad or missing key: waiting will not help
    BAD_OUTPUT = "bad_output"  # the model answered, but not in the requested shape: not the provider's health
    FATAL = "fatal"  # our own bad input (empty text, unsupported file): no provider can fix it, re-raise


@dataclass(frozen=True)
class Classified:
    kind: FailureKind
    retry_after: float | None = None  # seconds the provider asked to wait
    quota: bool = False  # the account is out of credit/quota
    # What a failed call consumed anyway (a model that answered badly still billed its tokens).
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class Usage:
    """What one successful call consumed. Only the fields that apply to the capability are filled."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    audio_seconds_in: float = 0.0  # speech to text: audio listened to
    audio_seconds_out: float = 0.0  # text to speech: audio produced
    chars: int = 0  # text to speech: characters spoken
    from_cache: bool = False  # served from the local cache: no provider request happened


# Outcomes written to the log and to provider_calls.
OK = "ok"
CACHE_HIT = "cache_hit"
SKIPPED_BREAKER = "skipped_breaker"
SKIPPED_BUDGET = "skipped_budget"
SKIPPED_CAP = "skipped_cap"
