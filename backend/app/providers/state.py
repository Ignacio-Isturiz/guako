"""Shared, process-wide router state: circuit breakers, daily counters, spending, and the usage buffer.

Providers are blocking and run in worker threads while the database is asynchronous, so nothing here
touches the database: calls are accumulated in memory (thread-safe) and ``usage.flush_usage`` writes them
in the background. At startup ``usage.load_baseline`` reads today's counters and the period's spending back.

Limit: one process. With several workers each would keep its own breakers and counters.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.config import Settings, settings
from app.providers.breaker import BreakerConfig, CircuitBreaker
from app.providers.budget import Budget, utc_today
from app.providers.context import get_call_context
from app.providers.pricing import Pricing
from app.providers.types import CACHE_HIT, OK, Usage

logger = logging.getLogger("app.providers")

_SKIPS = {"skipped_breaker", "skipped_budget", "skipped_cap"}
_ZERO = {
    "requests": 0, "successes": 0, "failures": 0, "rate_limited": 0, "as_fallback": 0,
    "prompt_tokens": 0, "completion_tokens": 0, "audio_seconds_in": 0.0, "audio_seconds_out": 0.0,
    "chars": 0, "cost_usd": 0.0,
}  # fmt: skip


@dataclass
class CallRecord:
    capability: str  # llm, stt, tts
    use: str  # conversation, analysis
    provider: str
    model: str
    outcome: str  # ok, cache_hit, rate_limited, unavailable, timeout, auth, bad_output, skipped_*
    latency_ms: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    fallback_from: str | None = None


class ProviderState:
    def __init__(self, cfg: Settings, *, clock: Callable[[], float] = time.monotonic, today: Callable[[], date] = utc_today) -> None:
        self.cfg = cfg
        self.clock = clock
        self.today = today
        self.pricing = Pricing(cfg)
        self.budget = Budget(cfg.paid_budget_usd, cfg.paid_budget_period, cfg.paid_budget_warn_fraction, today)
        self._breaker_cfg = BreakerConfig(
            failure_threshold=cfg.breaker_failure_threshold,
            cooldown_seconds=cfg.breaker_cooldown_seconds,
            max_cooldown_seconds=cfg.breaker_max_cooldown_seconds,
            quota_wait_seconds=cfg.breaker_quota_wait_seconds,
            max_open_seconds=cfg.breaker_max_open_seconds,
        )
        self._caps = cfg.daily_caps
        self._lock = threading.Lock()
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}
        self._requests_today: dict[tuple[date, str, str], int] = {}
        self._agg: dict[tuple[date, str, str, str], dict] = {}
        self._calls: list[dict] = []

    # --- decisions -------------------------------------------------------------------------------

    def breaker(self, provider: str, capability: str) -> CircuitBreaker:
        with self._lock:
            key = (provider, capability)
            if key not in self._breakers:
                self._breakers[key] = CircuitBreaker(provider, capability, self._breaker_cfg, self.clock)
            return self._breakers[key]

    def cap_reached(self, provider: str, capability: str) -> bool:
        """Has this provider used up its own daily limit for this capability (cache hits do not count)?"""
        cap = self._caps.get((provider, capability))
        if cap is None:
            return False
        with self._lock:
            return self._requests_today.get((self.today(), provider, capability), 0) >= cap

    # --- recording -------------------------------------------------------------------------------

    def record(self, rec: CallRecord) -> None:
        ctx = get_call_context()
        self._log(rec, ctx)
        if rec.outcome in _SKIPS or rec.outcome == CACHE_HIT:
            return  # skipped calls and cache hits are only logged: nothing was requested from the provider
        day = self.today()
        with self._lock:
            agg = self._agg.setdefault((day, rec.provider, rec.capability, rec.use), dict(_ZERO))
            agg["requests"] += 1
            if rec.outcome == OK:
                agg["successes"] += 1
                agg["as_fallback"] += 1 if rec.fallback_from else 0
            elif rec.outcome == "rate_limited":
                agg["rate_limited"] += 1
            else:
                agg["failures"] += 1
            u = rec.usage
            agg["prompt_tokens"] += u.prompt_tokens
            agg["completion_tokens"] += u.completion_tokens
            agg["audio_seconds_in"] += u.audio_seconds_in
            agg["audio_seconds_out"] += u.audio_seconds_out
            agg["chars"] += u.chars
            agg["cost_usd"] += rec.cost_usd
            if rec.outcome != "rate_limited":  # a 429 was not served, so it does not use the day's quota
                key = (day, rec.provider, rec.capability)
                self._requests_today[key] = self._requests_today.get(key, 0) + 1
            self._calls.append(
                {
                    "capability": rec.capability, "use": rec.use, "provider": rec.provider, "model": rec.model[:64],
                    "outcome": rec.outcome, "latency_ms": rec.latency_ms,
                    "prompt_tokens": u.prompt_tokens or None, "completion_tokens": u.completion_tokens or None,
                    "audio_seconds": (u.audio_seconds_in or u.audio_seconds_out) or None, "chars": u.chars or None,
                    "cost_usd": rec.cost_usd, "fallback_from": rec.fallback_from,
                    "session_id": ctx.get("session_id"), "turn_id": ctx.get("turn_id"),
                }
            )  # fmt: skip
        self.budget.record(rec.cost_usd)

    def _log(self, rec: CallRecord, ctx: dict) -> None:
        """One structured line per call. Never the prompt, the text, the audio or any key."""
        level = logging.INFO if rec.outcome in (OK, CACHE_HIT) or rec.outcome in _SKIPS else logging.WARNING
        u = rec.usage
        logger.log(
            level,
            "provider_call capability=%s use=%s provider=%s model=%s outcome=%s latency_ms=%d prompt_tokens=%d "
            "completion_tokens=%d audio_s=%.1f chars=%d cost_usd=%.6f fallback_from=%s session=%s turn=%s",
            rec.capability, rec.use, rec.provider, rec.model, rec.outcome, rec.latency_ms, u.prompt_tokens,
            u.completion_tokens, u.audio_seconds_in or u.audio_seconds_out, u.chars, rec.cost_usd, rec.fallback_from,
            ctx.get("session_id"), ctx.get("turn_id"),
        )  # fmt: skip

    # --- persistence hooks -----------------------------------------------------------------------

    def drain(self) -> tuple[dict[tuple[date, str, str, str], dict], list[dict]]:
        """Take what was recorded since the last drain (the flusher writes it to the database)."""
        with self._lock:
            agg, calls = self._agg, self._calls
            self._agg, self._calls = {}, []
        return agg, calls

    def put_back(self, agg: dict, calls: list[dict]) -> None:
        """A flush failed: keep the numbers for the next try."""
        with self._lock:
            for key, values in agg.items():
                mine = self._agg.setdefault(key, dict(_ZERO))
                for name, value in values.items():
                    mine[name] += value
            self._calls = calls + self._calls

    def load_baseline(self, requests_today: dict[tuple[str, str], int], period_spent: float) -> None:
        """Today's request counters and the period's spending as the database has them (at startup)."""
        day = self.today()
        with self._lock:
            for (provider, capability), count in requests_today.items():
                self._requests_today[(day, provider, capability)] = count
        self.budget.load_baseline(period_spent)

    def snapshot(self) -> dict:
        with self._lock:
            breakers = [b.snapshot() for b in self._breakers.values()]
            counters = {f"{p}:{c}": n for (d, p, c), n in self._requests_today.items() if d == self.today()}
        caps = [{"provider": p, "capability": c, "daily_cap": n, "used_today": counters.get(f"{p}:{c}", 0)} for (p, c), n in self._caps.items()]
        return {"budget": self.budget.snapshot(), "breakers": breakers, "daily_caps": caps}


_state: ProviderState | None = None
_state_lock = threading.Lock()


def get_state() -> ProviderState:
    """The process-wide state, built from the app settings on first use."""
    global _state
    with _state_lock:
        if _state is None:
            _state = ProviderState(settings)
        return _state


def reset_state(state: ProviderState | None = None) -> None:
    """Replace (or clear) the process-wide state. For tests."""
    global _state
    with _state_lock:
        _state = state
