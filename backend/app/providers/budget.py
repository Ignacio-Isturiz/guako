"""Spending cap for paid providers: warn at 80 %, stop using them at 100 %, and keep using the free ones.

The amount spent is our own estimate (see pricing.py), held in memory and loaded from provider_usage at
startup. The period is a day, a calendar month (UTC) or the whole life of the account ("total").
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime

logger = logging.getLogger("app.providers")


def utc_today() -> date:
    return datetime.now(UTC).date()


class Budget:
    def __init__(
        self,
        limit_usd: float,
        period: str,
        warn_fraction: float = 0.8,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self.limit = limit_usd
        self.period = period
        self.warn_fraction = warn_fraction
        self._today = today
        self._lock = threading.Lock()
        self._spent: dict[str, float] = {}
        self._warned: set[str] = set()
        self._stopped: set[str] = set()

    def key(self) -> str:
        day = self._today()
        return {"day": day.isoformat(), "month": day.strftime("%Y-%m")}.get(self.period, "total")

    def period_start(self) -> date | None:
        """First day that counts in the current period (None = from the beginning)."""
        day = self._today()
        return {"day": day, "month": day.replace(day=1)}.get(self.period)

    def load_baseline(self, spent: float) -> None:
        """Amount already spent in the current period (from the database, at startup)."""
        with self._lock:
            self._spent[self.key()] = spent

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent.get(self.key(), 0.0)

    def can_spend(self, estimate: float = 0.0) -> bool:
        """False once the cap is reached, or if this call would cross it. A cap of 0 disables paid providers."""
        return self.limit > 0 and self.spent + estimate <= self.limit

    def record(self, cost: float) -> None:
        if cost <= 0:
            return
        with self._lock:
            key = self.key()
            total = self._spent[key] = self._spent.get(key, 0.0) + cost
            warn = total >= self.warn_fraction * self.limit and key not in self._warned
            stop = total >= self.limit and key not in self._stopped
            if warn:
                self._warned.add(key)
            if stop:
                self._stopped.add(key)
        if warn:
            logger.warning("budget_warning spent_usd=%.4f limit_usd=%.2f period=%s", total, self.limit, self.period)
        if stop:
            logger.error("budget_exhausted spent_usd=%.4f limit_usd=%.2f period=%s paid providers are now skipped", total, self.limit, self.period)

    def status(self) -> str:
        spent = self.spent
        if self.limit <= 0 or spent >= self.limit:
            return "exhausted"
        return "warning" if spent >= self.warn_fraction * self.limit else "ok"

    def snapshot(self) -> dict:
        return {
            "limit_usd": self.limit,
            "period": self.period,
            "period_key": self.key(),
            "spent_usd": round(self.spent, 6),
            "warn_at_usd": round(self.warn_fraction * self.limit, 6),
            "status": self.status(),
        }
