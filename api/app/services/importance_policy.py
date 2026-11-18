"""Deterministic exam-importance policy. Pure functions; no I/O, no LLM.

* No segmented past-paper questions in the workspace → neutral importance 3 ("default").
* Otherwise each topic's weight = Σ marks of mapped questions (a question without stated marks
  counts as 1). importance = 1 + round(4 × weight / max_weight), so the most-examined topic is 5
  and a topic never seen in past papers is 1.
* A question mapped to a subtopic also counts (once) toward its parent unit.
* A student override always wins and is never recomputed.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

IMPORTANCE_POLICY_VERSION = "importance-2026-11-17"
NEUTRAL_IMPORTANCE = 3
UNSTATED_MARKS_WEIGHT = 1.0


@dataclass(frozen=True)
class MappedQuestion:
    topic_id: UUID
    marks: float | None
    year: int | None


@dataclass(frozen=True)
class ImportanceDecision:
    importance: int
    source: str
    basis: dict[str, Any]


def compute_importance(
    topic_ids: Iterable[UUID],
    mapped: Iterable[MappedQuestion],
    *,
    workspace_question_count: int,
    student_overrides: Mapping[UUID, int] | None = None,
) -> dict[UUID, ImportanceDecision]:
    overrides = dict(student_overrides or {})
    stats: dict[UUID, dict[str, Any]] = {}
    for item in mapped:
        entry = stats.setdefault(item.topic_id, {"questions": 0, "weight": 0.0, "years": set()})
        entry["questions"] += 1
        entry["weight"] += item.marks if item.marks and item.marks > 0 else UNSTATED_MARKS_WEIGHT
        if item.year:
            entry["years"].add(item.year)
    max_weight = max((entry["weight"] for entry in stats.values()), default=0.0)

    decisions: dict[UUID, ImportanceDecision] = {}
    for topic_id in topic_ids:
        entry = stats.get(topic_id, {"questions": 0, "weight": 0.0, "years": set()})
        basis = {
            "policy_version": IMPORTANCE_POLICY_VERSION,
            "past_paper_questions": entry["questions"],
            "weighted_marks": round(entry["weight"], 2),
            "years": sorted(entry["years"]),
            "workspace_past_paper_questions": workspace_question_count,
        }
        if topic_id in overrides:
            decisions[topic_id] = ImportanceDecision(overrides[topic_id], "student", basis)
        elif workspace_question_count == 0 or max_weight == 0:
            decisions[topic_id] = ImportanceDecision(NEUTRAL_IMPORTANCE, "default", basis)
        else:
            value = 1 + round(4 * entry["weight"] / max_weight)
            decisions[topic_id] = ImportanceDecision(max(1, min(5, value)), "past_papers", basis)
    return decisions
