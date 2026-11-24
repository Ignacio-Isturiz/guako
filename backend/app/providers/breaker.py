"""Circuit breaker: stop sending requests to a provider that keeps failing, and try it again later.

One breaker per (provider, capability), in memory. Closed = normal. Open = skipped until a deadline.
Half-open = the deadline passed and exactly one real request is let through as a probe: if it works the
breaker closes, if it fails the breaker opens again for twice as long.

Numbers (all from settings; the defaults are justified here):
- 3 consecutive transport failures open it: one hiccup should not trip it, but each failure costs the
  caller up to a full timeout before the next provider answers, so waiting for 5 is too slow.
- A 429 that asks to wait more than ``quota_wait_seconds`` means the quota is spent: open at once for
  that long (capped), because trying again before then only burns requests.
- First wait 30 s, doubling up to 10 min: per-minute limits clear in seconds, outages take minutes.
- An auth error opens it for the maximum (an hour): retrying cannot fix a bad key.
- Bad model output and our own bad input never count: they say nothing about the provider's health.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.providers.types import FailureKind

logger = logging.getLogger("app.providers")


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class BreakerConfig:
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    max_cooldown_seconds: float = 600.0
    quota_wait_seconds: float = 60.0
    max_open_seconds: float = 3600.0


class CircuitBreaker:
    def __init__(self, provider: str, capability: str, cfg: BreakerConfig, clock: Callable[[], float]) -> None:
        self.provider = provider
        self.capability = capability
        self._cfg = cfg
        self._clock = clock
        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        self._failures = 0  # consecutive
        self._reopened = 0  # times it re-opened without a success in between (drives the doubling wait)
        self._open_until = 0.0
        self._probing = False
        self._reason = ""

    # --- asking -------------------------------------------------------------------------------

    def allow(self) -> bool:
        """May a request go to this provider now? When it says yes after an open period, the caller is the probe."""
        with self._lock:
            if self._state is BreakerState.CLOSED:
                return True
            if self._state is BreakerState.OPEN:
                if self._clock() < self._open_until:
                    return False
                self._state = BreakerState.HALF_OPEN
                self._probing = True
                logger.info("breaker_half_open provider=%s capability=%s", self.provider, self.capability)
                return True
            if self._probing:  # half-open and a probe is already in flight
                return False
            self._probing = True
            return True

    def retry_in(self) -> float:
        """Seconds until a request may go through (0 if it may now)."""
        with self._lock:
            if self._state is BreakerState.OPEN:
                return max(self._open_until - self._clock(), 0.0)
            return 0.0

    # --- reporting ----------------------------------------------------------------------------

    def record_success(self) -> None:
        with self._lock:
            was = self._state
            self._state, self._failures, self._reopened, self._probing, self._reason = BreakerState.CLOSED, 0, 0, False, ""
        if was is not BreakerState.CLOSED:
            logger.info("breaker_closed provider=%s capability=%s", self.provider, self.capability)

    def release_probe(self) -> None:
        """The request that held the pass ended without saying anything about health (bad output, our input)."""
        with self._lock:
            if self._state is BreakerState.HALF_OPEN:
                self._probing = False

    def record_failure(self, kind: FailureKind, retry_after: float | None = None, quota: bool = False) -> None:
        with self._lock:
            probe_failed = self._state is BreakerState.HALF_OPEN
            self._probing = False
            self._failures += 1
            if kind is FailureKind.AUTH:
                seconds, reason = self._cfg.max_open_seconds, "auth"
            elif quota or (retry_after is not None and retry_after > self._cfg.quota_wait_seconds):
                seconds = min(retry_after or self._cfg.max_open_seconds, self._cfg.max_open_seconds)
                reason = "quota"
            elif probe_failed or self._failures >= self._cfg.failure_threshold:
                seconds = min(self._cfg.cooldown_seconds * 2**self._reopened, self._cfg.max_cooldown_seconds)
                reason = kind.value
            else:
                return  # not enough failures yet
            self._reopened += 1
            self._state = BreakerState.OPEN
            self._open_until = self._clock() + seconds
            self._reason = reason
        # Auth is an error (someone must fix the key); the rest is routine.
        level = logging.ERROR if reason == "auth" else logging.WARNING
        logger.log(level, "breaker_open provider=%s capability=%s reason=%s seconds=%.0f", self.provider, self.capability, reason, seconds)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "provider": self.provider,
                "capability": self.capability,
                "state": self._state.value,
                "consecutive_failures": self._failures,
                "reason": self._reason or None,
                "retry_in_seconds": round(max(self._open_until - self._clock(), 0.0), 1) if self._state is BreakerState.OPEN else 0.0,
            }
