"""Deterministic revision scheduler. Pure functions only.

* Demand per unit = base minutes by label × (importance / 3): Weak 120, Medium 60,
  Limited evidence 45, Strong 20 (review).
* Order: priority band first (weaker × more important), then syllabus order as prerequisites.
* Each available day (selected weekdays, from today until the day before the exam) is filled with
  sessions of at most 45 minutes, one unit per session, round-robin across units with remaining
  demand so no single unit takes a whole day.
* With two or more days and enough spare time, the last day starts with a re-test session.
* Unmet demand is reported explicitly as a shortfall; nothing is silently compressed.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

PLAN_POLICY_VERSION = "plan-2026-11-17"
BASE_MINUTES = {"weak": 120, "medium": 60, "limited_evidence": 45, "strong": 20}
MAX_SESSION_MINUTES = 45
MIN_SESSION_MINUTES = 10
RETEST_MINUTES = 30
PRIORITY_BAND = 20.0
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class PlanUnit:
    topic_id: UUID
    title: str
    label: str
    importance: int
    priority: float
    position: int
    focus: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedSession:
    day: date
    sequence: int
    topic_id: UUID | None
    topic_title: str | None
    focus: tuple[str, ...]
    activity: str
    minutes: int


@dataclass
class Plan:
    sessions: list[PlannedSession]
    demand_minutes: int
    scheduled_minutes: int
    available_minutes: int
    shortfall: list[dict[str, object]] = field(default_factory=list)
    policy_version: str = PLAN_POLICY_VERSION

    @property
    def status(self) -> str:
        return "shortfall" if self.shortfall else "feasible"


def demand_minutes(label: str, importance: int) -> int:
    return int(math.ceil(BASE_MINUTES[label] * importance / 3 / 5) * 5)  # round up to 5 minutes


def study_days(today: date, exam_date: date, weekdays: Sequence[str]) -> list[date]:
    allowed = {WEEKDAYS.index(w) for w in weekdays}
    return [
        today + timedelta(days=i)
        for i in range((exam_date - today).days)
        if (today + timedelta(days=i)).weekday() in allowed
    ]


def order_units(units: Sequence[PlanUnit]) -> list[PlanUnit]:
    return sorted(
        units, key=lambda u: (-math.floor(u.priority / PRIORITY_BAND), u.position, u.title)
    )


def build_plan(
    units: Sequence[PlanUnit],
    today: date,
    exam_date: date,
    minutes_per_day: int,
    weekdays: Sequence[str],
    completed: dict[UUID, int] | None = None,
) -> Plan:
    if exam_date < today:
        raise ValueError("EXAM_DATE_IN_PAST")
    if not weekdays:
        raise ValueError("NO_AVAILABLE_WEEKDAYS")
    completed = completed or {}
    ordered = order_units(units)
    remaining = {
        u.topic_id: max(0, demand_minutes(u.label, u.importance) - completed.get(u.topic_id, 0))
        for u in ordered
    }
    total_demand = sum(remaining.values())
    days = study_days(today, exam_date, weekdays)
    # The re-test day is reserved only if it does not take time away from unmet study demand.
    reserve_retest = len(days) >= 2 and len(days) * minutes_per_day - RETEST_MINUTES >= total_demand
    sessions: list[PlannedSession] = []
    for index, day in enumerate(days):
        capacity = minutes_per_day
        sequence = 0
        if reserve_retest and index == len(days) - 1 and capacity >= MIN_SESSION_MINUTES:
            minutes = min(RETEST_MINUTES, capacity)
            sessions.append(PlannedSession(day, sequence, None, None, (), "retest", minutes))
            capacity -= minutes
            sequence += 1
        progressed = True
        while capacity >= MIN_SESSION_MINUTES and progressed:
            progressed = False
            for unit in ordered:
                need = remaining[unit.topic_id]
                if need <= 0 or capacity < min(MIN_SESSION_MINUTES, need):
                    continue
                minutes = min(MAX_SESSION_MINUTES, need, capacity)
                activity = "review" if unit.label == "strong" else "study"
                sessions.append(
                    PlannedSession(
                        day, sequence, unit.topic_id, unit.title, unit.focus, activity, minutes
                    )
                )
                remaining[unit.topic_id] -= minutes
                capacity -= minutes
                sequence += 1
                progressed = True
                if capacity < MIN_SESSION_MINUTES:
                    break
    study_minutes = sum(s.minutes for s in sessions if s.activity != "retest")
    shortfall = [
        {
            "topic_id": str(u.topic_id),
            "title": u.title,
            "label": u.label,
            "minutes": remaining[u.topic_id],
        }
        for u in ordered
        if remaining[u.topic_id] > 0
    ]
    return Plan(sessions, total_demand, study_minutes, len(days) * minutes_per_day, shortfall)
