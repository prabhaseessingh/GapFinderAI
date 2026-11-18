"""Daily per-student fair-use limits.

Counters live in Redis, keyed by student, action and the student's local date; they expire a
little after the student's next local midnight. FastAPI checks and increments BEFORE any provider
request. The limit state is shown transparently in the UI, never as a payment prompt.
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.errors import AppError

Action = Literal["diagnostic", "explain", "voice", "visual"]
DAILY_LIMITS: dict[Action, int] = {"diagnostic": 10, "explain": 20, "voice": 10, "visual": 10}
FALLBACK_TIMEZONE = "UTC"
EXPIRY_SLACK = timedelta(hours=2)


class Counter(Protocol):
    def incr_if_below(self, key: str, limit: int, expire_at: datetime) -> int | None:
        """Atomically add one unless the value is already >= limit; returns the new value or None."""

    def get(self, key: str) -> int: ...

    def decr(self, key: str) -> None: ...


_INCR_IF_BELOW = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current >= tonumber(ARGV[1]) then return -1 end
current = redis.call('INCR', KEYS[1])
redis.call('EXPIREAT', KEYS[1], ARGV[2])
return current
"""


class RedisCounter:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
        self._script = self._client.register_script(_INCR_IF_BELOW)

    def incr_if_below(self, key: str, limit: int, expire_at: datetime) -> int | None:
        value = int(self._script(keys=[key], args=[limit, int(expire_at.timestamp())]))
        return None if value < 0 else value

    def get(self, key: str) -> int:
        raw = self._client.get(key)
        if raw is None:
            return 0
        return int(raw.decode() if isinstance(raw, bytes) else str(raw))

    def decr(self, key: str) -> None:
        if self.get(key) > 0:
            self._client.decr(key)


class MemoryCounter:
    """In-process counter for tests."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def incr_if_below(self, key: str, limit: int, expire_at: datetime) -> int | None:
        if self.values.get(key, 0) >= limit:
            return None
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def get(self, key: str) -> int:
        return self.values.get(key, 0)

    def decr(self, key: str) -> None:
        if self.values.get(key, 0) > 0:
            self.values[key] -= 1


def zone(timezone: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone or FALLBACK_TIMEZONE)
    except Exception:  # noqa: BLE001 - an unknown stored zone falls back, never blocks the student
        return ZoneInfo(FALLBACK_TIMEZONE)


def local_day_window(timezone: str | None, now: datetime | None = None) -> tuple[str, datetime]:
    """(local date label, next local midnight as an aware datetime)."""
    tz = zone(timezone)
    local = (now or datetime.now(UTC)).astimezone(tz)
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return local.date().isoformat(), midnight


def counter_key(student_id: UUID, action: Action, day: str) -> str:
    return f"fairuse:{student_id}:{action}:{day}"


@dataclass(frozen=True)
class Usage:
    action: Action
    used: int
    limit: int
    resets_at: datetime


class FairUse:
    def __init__(
        self, counter: Counter, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._counter = counter
        self._clock = clock

    def consume(self, student_id: UUID, action: Action, timezone: str | None) -> Usage:
        day, resets_at = local_day_window(timezone, self._clock())
        limit = DAILY_LIMITS[action]
        try:
            value = self._counter.incr_if_below(
                counter_key(student_id, action, day), limit, resets_at + EXPIRY_SLACK
            )
        except Exception as error:
            raise AppError(
                503,
                "PROVIDER_UNAVAILABLE",
                "Usage limits can't be checked right now. Please try again.",
                retryable=True,
            ) from error
        if value is None:
            raise AppError(
                429,
                "RATE_LIMITED",
                f"You've used today's {limit} {action} requests. They reset at midnight.",
                retryable=False,
            )
        return Usage(action, value, limit, resets_at)

    def refund(self, student_id: UUID, action: Action, timezone: str | None) -> None:
        """Give a unit back when our side failed before any provider work (e.g. queue down)."""
        day, _ = local_day_window(timezone, self._clock())
        with contextlib.suppress(Exception):
            self._counter.decr(counter_key(student_id, action, day))

    def usage(self, student_id: UUID, timezone: str | None) -> list[Usage]:
        day, resets_at = local_day_window(timezone, self._clock())
        out = []
        for action, limit in DAILY_LIMITS.items():
            try:
                used = self._counter.get(counter_key(student_id, action, day))
            except Exception:  # noqa: BLE001
                used = 0
            out.append(Usage(action, min(used, limit), limit, resets_at))
        return out
