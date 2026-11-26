"""What every eval set shares: the run's identity, its spending, retries, failure reasons and the result file.

COST. The LLM and speech calls go through the app's provider router, so a run can be completed when a free
provider runs out (it falls back to OpenAI, which is paid). Every run therefore:
  1. estimates its cost BEFORE sending anything, assuming every call is answered by the paid provider;
  2. refuses to start if the estimate is above ``--max-cost`` (default 2 USD), and
  3. runs with its own spending cap equal to ``--max-cost``: once the router's own estimate of what was spent
     reaches it, the paid provider is skipped, so a wrong estimate cannot turn into an unbounded bill.
The router state is the run's own (not the API process's): its breakers, daily counters and spending start at
zero and are not written to the database.

FAILURES. A case whose call fails for a transient reason (every provider out of quota or overloaded, a model
answer that does not validate, a timeout) is retried with growing waits. A case that still fails is written to
the result as failed, with its reason; it is never dropped, and the metrics say how many cases they cover.
"""

import json
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from app.config import Settings
from app.llm.errors import LLMAuthError, LLMError, LLMOutputError, LLMRateLimitError, LLMTimeoutError
from app.providers.errors import LLMExhausted, STTExhausted
from app.providers.state import ProviderState
from app.providers.types import Usage
from app.stt.errors import NoSpeechError, STTError

BACKEND_DIR = Path(__file__).resolve().parents[2]
EVALS_DIR = BACKEND_DIR / "evals"
RESULTS_DIR = BACKEND_DIR / "results" / "evals"
REVIEWS_DIR = BACKEND_DIR / "results" / "reviews"

DEFAULT_MAX_COST_USD = 2.0
# Waits before each retry of a failed case (seconds). The router has already tried every provider once per attempt.
RETRY_WAITS_S = (10.0, 30.0, 60.0)
MAX_PROVIDER_WAIT_S = 120.0

T = TypeVar("T")


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- cost ------------------------------------------------------------------------------------------------------


def llm_call_cost(cfg: Settings, prompt_chars: int, completion_tokens: int) -> float:
    """What one LLM call would cost on the paid provider (about 4 characters per token)."""
    usage = Usage(prompt_tokens=prompt_chars // 4, completion_tokens=completion_tokens)
    return (usage.prompt_tokens * cfg.price_openai_llm_input_per_m + usage.completion_tokens * cfg.price_openai_llm_output_per_m) / 1_000_000


def stt_cost(cfg: Settings, seconds: float) -> float:
    return seconds / 60 * cfg.price_openai_stt_per_minute


@dataclass
class Plan:
    """What a run is going to send, decided before sending anything."""

    eval_set: str
    calls: int
    estimated_cost_usd: float
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [f"[{self.eval_set}] {self.calls} calls, estimated cost at most ${self.estimated_cost_usd:.4f}"]
        lines += [f"  - {note}" for note in self.notes]
        return "\n".join(lines)


def over_limit(plans: list[Plan], max_cost: float) -> str | None:
    """Why the run must not start (the estimate is above the limit), or None."""
    total = sum(p.estimated_cost_usd for p in plans)
    if total > max_cost:
        return (
            f"Estimated cost ${total:.2f} is above the limit of ${max_cost:.2f}. Nothing was sent. "
            "If you accept that cost, run again with a higher --max-cost."
        )
    return None


class Tracker:
    """The run's own router state, with a spending cap of ``budget_usd``, and what each call did.

    ``cfg`` is a copy of the settings: the router builds fresh providers from it, so the API process's
    breakers and counters are neither used nor changed.
    """

    def __init__(self, cfg: Settings, budget_usd: float, llm_order: str | None = None) -> None:
        update: dict[str, Any] = {"paid_budget_usd": budget_usd, "paid_budget_period": "total"}
        if llm_order:
            update["llm_analysis_order"] = llm_order
        self.cfg = cfg.model_copy(update=update)
        self.state = ProviderState(self.cfg)
        self.calls: list[dict[str, Any]] = []

    def collect(self) -> list[dict[str, Any]]:
        """The provider attempts recorded since the last collect (one dict per attempt)."""
        _, calls = self.state.drain()
        self.calls.extend(calls)
        return calls

    def summary(self) -> dict[str, Any]:
        self.collect()
        served = Counter(f"{c['provider']}:{c['model']}" for c in self.calls if c["outcome"] == "ok")
        attempts = Counter(f"{c['provider']}:{c['outcome']}" for c in self.calls)
        return {
            "actual_cost_usd": round(sum(c["cost_usd"] for c in self.calls), 6),
            "served_by": dict(served),  # provider:model -> calls it answered
            "provider_attempts": dict(attempts),  # provider:outcome -> count (429s and 503s included)
            "fallback_calls": sum(1 for c in self.calls if c["outcome"] == "ok" and c["fallback_from"]),
        }


def served_by(calls: list[dict[str, Any]]) -> str | None:
    ok = [c for c in calls if c["outcome"] == "ok"]
    return f"{ok[-1]['provider']}:{ok[-1]['model']}" if ok else None


# --- failures and retries --------------------------------------------------------------------------------------


@dataclass
class Failure:
    reason: str  # exhausted, rate_limited, provider_error, timeout, bad_output, auth, no_speech, unexpected_error
    retryable: bool


def classify_llm_failure(exc: Exception) -> Failure:
    if isinstance(exc, LLMExhausted):
        return Failure("exhausted", True)  # every provider out of quota, overloaded or over the run's budget
    if isinstance(exc, LLMOutputError):
        return Failure("bad_output", True)
    if isinstance(exc, LLMAuthError):
        return Failure("auth", False)
    if isinstance(exc, LLMRateLimitError):
        return Failure("rate_limited", True)
    if isinstance(exc, LLMTimeoutError):
        return Failure("timeout", True)
    if isinstance(exc, LLMError):
        return Failure("provider_error", True)
    return Failure("unexpected_error", False)


def classify_stt_failure(exc: Exception) -> Failure:
    if isinstance(exc, NoSpeechError):
        return Failure("no_speech", False)
    if isinstance(exc, STTExhausted):
        return Failure("exhausted", True)
    if isinstance(exc, STTError):
        if exc.kind == "auth":
            return Failure("auth", False)
        if exc.kind == "invalid_input":
            return Failure("bad_input", False)
        return Failure("timeout" if exc.kind == "timeout" else "provider_error", True)
    return Failure("unexpected_error", False)


@dataclass
class Attempted:
    value: Any = None
    failure: str | None = None
    error: str | None = None
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.failure is None


def with_retries(
    call: Callable[[], T],
    classify: Callable[[Exception], Failure],
    *,
    waits: tuple[float, ...] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Attempted:
    """Run ``call``; on a transient failure wait and try again. Never raises: a failure is returned with its reason."""
    # Resolved at call time (not as default values), so the module settings can be changed (tests).
    waits = RETRY_WAITS_S if waits is None else waits
    sleep = time.sleep if sleep is None else sleep
    attempts = 0
    for wait in (*waits, None):
        attempts += 1
        try:
            return Attempted(value=call(), attempts=attempts)
        except Exception as exc:  # noqa: BLE001 - every failure is reported, none is dropped
            failure = classify(exc)
            last = Attempted(failure=failure.reason, error=f"{type(exc).__name__}: {exc}"[:300], attempts=attempts)
            if not failure.retryable or wait is None:
                return last
            hinted = getattr(exc, "retry_after", None) or 0.0
            sleep(min(max(wait, float(hinted)), MAX_PROVIDER_WAIT_S))
    return last  # pragma: no cover - the loop always returns


def failure_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(r["failure"] for r in rows if r.get("failure")))


# --- the result file -------------------------------------------------------------------------------------------


def write_result(result: dict[str, Any], results_dir: Path = RESULTS_DIR) -> Path:
    """``<set>-<run_id>.json``: the summary, the metrics and every case (failed ones included)."""
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{result['set']}-{result['run_id']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def base_result(eval_set: str, run_id: str, started_at: str, plan: Plan, rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    failed = [r for r in rows if r.get("failure")]
    return {
        "set": eval_set,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": now_iso(),
        "estimated_cost_usd": round(plan.estimated_cost_usd, 6),
        "cases": len(rows),
        "failed": len(failed),
        "failure_reasons": failure_counts(rows),
        **extra,
        "rows": rows,
    }


def latest_result(eval_set: str, results_dir: Path = RESULTS_DIR) -> dict[str, Any] | None:
    """The newest result of a set (run ids start with the UTC time, so the name sorts by date)."""
    files = sorted(results_dir.glob(f"{eval_set}-2*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None
