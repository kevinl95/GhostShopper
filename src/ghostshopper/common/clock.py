"""Clock protocol so time-dependent logic can be tested without sleeping."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware (UTC)."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds, for measuring elapsed time."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """Test helper: time moves only when `advance` is called."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._mono = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float = 0.0, *, days: float = 0.0) -> None:
        delta = timedelta(seconds=seconds, days=days)
        self._now += delta
        self._mono += delta.total_seconds()
