"""ProviderRouter: answers one capability with the first provider that is healthy, within quota and budget.

For each call it walks the configured order and, per provider:
  1. skips it if its circuit breaker is open (unless the answer is free, e.g. cached audio);
  2. skips it if it is paid and the spending cap is reached (or this call would cross it);
  3. skips it if it already used its own daily cap, so we move on before it answers 429;
  4. calls it; a 429, 503 or timeout is recorded and the next provider is tried.
Nothing is left unrecorded: every attempt and every skip becomes one ``provider_call`` log line, and the
attempts also feed the daily usage table.

If nobody answers it raises the error ``exhausted`` builds (callers may degrade); the exceptions are an
invalid model answer and a bad key on every provider, which are re-raised as they were.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from app import observability
from app.providers.pricing import is_paid
from app.providers.state import CallRecord, ProviderState
from app.providers.types import (
    CACHE_HIT,
    OK,
    SKIPPED_BREAKER,
    SKIPPED_BUDGET,
    SKIPPED_CAP,
    Classified,
    FailureKind,
    Usage,
)

T = TypeVar("T")


@dataclass
class Route:
    name: str  # groq, gemini, openai
    provider: Any

    @property
    def paid(self) -> bool:
        return is_paid(self.name)

    @property
    def model(self) -> str:
        return str(getattr(self.provider, "model", "unknown"))


class ProviderRouter(Generic[T]):
    def __init__(
        self,
        capability: str,
        use: str,
        routes: list[Route],
        state: ProviderState,
        classify: Callable[[Exception], Classified],
        exhausted: Callable[[float | None], Exception],
    ) -> None:
        self.capability = capability
        self.use = use
        self.routes = routes
        self.state = state
        self._classify = classify
        self._exhausted = exhausted
        # Route that answered last (informational: used by scripts to print the provider's name).
        self.last_route: Route | None = None
        self.used_fallback = False

    def run(
        self,
        invoke: Callable[[Route], tuple[T, Usage]],
        *,
        estimate: Callable[[Route], float] | None = None,
        free_hit: Callable[[Route], bool] | None = None,
    ) -> T:
        """``invoke`` makes the real call on a route and returns (value, usage)."""
        state, capability = self.state, self.capability
        failures: list[Classified] = []
        last_error: Exception | None = None
        fallback_from: str | None = None
        wait_hints: list[float] = []

        skipped: list[str] = []  # shown on the next attempt's trace: why the providers before it were passed over

        def skip(route: Route, outcome: str) -> None:
            skipped.append(f"{route.name}:{outcome}")
            state.record(CallRecord(capability, self.use, route.name, route.model, outcome))

        for route in self.routes:
            hit = bool(free_hit and free_hit(route))
            breaker = state.breaker(route.name, capability)
            if not hit:
                if not breaker.allow():
                    wait_hints.append(breaker.retry_in())
                    skip(route, SKIPPED_BREAKER)
                    continue
                # From here this call holds the breaker's pass (it may be the half-open probe).
                if route.paid and not state.budget.can_spend(estimate(route) if estimate else 0.0):
                    breaker.release_probe()
                    skip(route, SKIPPED_BUDGET)
                    continue
                if state.cap_reached(route.name, capability):
                    breaker.release_probe()
                    skip(route, SKIPPED_CAP)
                    continue

            started = time.perf_counter()
            error: Exception | None = None
            with observability.provider_call(
                capability, self.use, route.name, route.model, fallback_from=fallback_from, skipped=list(skipped)
            ) as traced:
                try:
                    value, usage = invoke(route)
                except Exception as exc:
                    error, failure = exc, self._classify(exc)
                    traced.failed(failure.kind.value)
                else:
                    cached = hit or usage.from_cache
                    cost = 0.0 if cached else state.pricing.cost(route.name, capability, usage)
                    traced.succeeded(
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                        cost=cost,
                        metadata={"cache_hit": cached} if cached else {},
                    )
            if error is not None:
                exc = error
                if failure.kind is FailureKind.FATAL:
                    if not hit:
                        breaker.release_probe()
                    raise exc
                latency = int((time.perf_counter() - started) * 1000)
                used = Usage(prompt_tokens=failure.prompt_tokens, completion_tokens=failure.completion_tokens)
                state.record(
                    CallRecord(
                        capability, self.use, route.name, route.model, failure.kind.value, latency, used,
                        state.pricing.cost(route.name, capability, used), fallback_from,
                    )
                )  # fmt: skip
                if not hit:
                    if failure.kind is FailureKind.BAD_OUTPUT:
                        breaker.release_probe()  # says nothing about the provider's health
                    else:
                        breaker.record_failure(failure.kind, failure.retry_after, failure.quota)
                if failure.retry_after:
                    wait_hints.append(failure.retry_after)
                failures.append(failure)
                last_error = exc
                fallback_from = route.name
                continue

            latency = int((time.perf_counter() - started) * 1000)
            self.last_route = route
            self.used_fallback = fallback_from is not None
            if cached:
                state.record(CallRecord(capability, self.use, route.name, route.model, CACHE_HIT, latency, usage))
            else:
                breaker.record_success()
                state.record(
                    CallRecord(
                        capability, self.use, route.name, route.model, OK, latency, usage, cost, fallback_from,
                    )
                )  # fmt: skip
            return value

        # Nobody answered.
        if last_error is not None and failures:
            last = failures[-1].kind
            only_auth = all(f.kind is FailureKind.AUTH for f in failures)
            if last is FailureKind.BAD_OUTPUT or only_auth:
                raise last_error  # an invalid answer or a bad key is not "everyone is busy"
        waits = [w for w in wait_hints if w and w > 0]
        raise self._exhausted(min(waits) if waits else None)
