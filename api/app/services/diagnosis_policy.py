"""Deterministic diagnosis policy. Pure functions only.

mastery = 100 × (0.60·weighted_accuracy + 0.20·recency_accuracy + 0.10·cognitive_coverage
                 + 0.10·evaluation_confidence)
* weighted_accuracy: every evaluated question for the unit; each older attempt counts half as
  much as the next newer one; harder cognitive levels weigh more (apply > understand > recall).
* recency_accuracy: the unit's latest attempt only.
* cognitive_coverage: share of the three cognitive levels the unit has been tested at.
* evaluation_confidence: mean grader confidence (objective questions = 1).
Labels: Weak < 50 ≤ Medium < 75 ≤ Strong. "Limited evidence" wins when fewer than
MIN_EVALUATED_QUESTIONS_PER_TOPIC questions were evaluated or confidence < MIN_CONFIDENCE.
priority = (100 − mastery) × (importance / 3) × (0.5 + 0.5 × confidence)
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

DIAGNOSIS_POLICY_VERSION = "diagnosis-2026-11-17"
MIN_EVALUATED_QUESTIONS_PER_TOPIC = 2
MIN_CONFIDENCE = 0.6
WEAK_UPPER_EXCLUSIVE = 50.0
MEDIUM_UPPER_EXCLUSIVE = 75.0
HISTORY_DECAY = 0.5
LEVEL_WEIGHT = {"recall": 1.0, "understand": 1.25, "apply": 1.5}
LEVELS = ("recall", "understand", "apply")
NEUTRAL_IMPORTANCE = 3.0
W_ACCURACY, W_RECENCY, W_COVERAGE, W_CONFIDENCE = 0.60, 0.20, 0.10, 0.10


@dataclass(frozen=True)
class EvaluatedItem:
    question_id: UUID
    attempt_rank: int  # 0 = the most recent attempt that tested this unit
    cognitive_level: str
    score: float
    max_score: float
    confidence: float
    subtopic: str
    question_type: str
    attempt_id: UUID | None = None


@dataclass(frozen=True)
class UnitInput:
    topic_id: UUID
    title: str
    position: int
    importance: int
    items: tuple[EvaluatedItem, ...] = ()


@dataclass
class UnitDiagnosis:
    topic_id: UUID
    title: str
    position: int
    importance: int
    label: str
    mastery: float | None
    confidence: float
    priority: float
    evaluated_questions: int
    facts: dict[str, Any] = field(default_factory=dict)


def label_for(mastery: float) -> str:
    if mastery < WEAK_UPPER_EXCLUSIVE:
        return "weak"
    if mastery < MEDIUM_UPPER_EXCLUSIVE:
        return "medium"
    return "strong"


def _ratio(items: Iterable[EvaluatedItem], weighted: bool) -> float | None:
    numerator = denominator = 0.0
    for item in items:
        weight = (
            (HISTORY_DECAY**item.attempt_rank) * LEVEL_WEIGHT.get(item.cognitive_level, 1.0)
            if weighted
            else 1.0
        )
        numerator += weight * item.score
        denominator += weight * item.max_score
    return numerator / denominator if denominator else None


def diagnose_unit(unit: UnitInput) -> UnitDiagnosis:
    items = unit.items
    latest = [i for i in items if i.attempt_rank == 0]
    weighted = _ratio(items, weighted=True)
    recency = _ratio(latest, weighted=False)
    coverage = len({i.cognitive_level for i in items} & set(LEVELS)) / len(LEVELS)
    confidence = sum(i.confidence for i in items) / len(items) if items else 0.0
    mastery = None
    if weighted is not None and recency is not None:
        mastery = round(
            100
            * (
                W_ACCURACY * weighted
                + W_RECENCY * recency
                + W_COVERAGE * coverage
                + W_CONFIDENCE * confidence
            ),
            1,
        )
    limited = (
        len(items) < MIN_EVALUATED_QUESTIONS_PER_TOPIC
        or confidence < MIN_CONFIDENCE
        or mastery is None
    )
    label = "limited_evidence" if limited else label_for(mastery)  # type: ignore[arg-type]
    gap = 100.0 - (mastery if mastery is not None else 50.0)  # unknown mastery: assume a mid gap
    priority = round(gap * (unit.importance / NEUTRAL_IMPORTANCE) * (0.5 + 0.5 * confidence), 2)

    by_level: dict[str, list[float]] = {}
    by_sub: dict[str, list[float]] = {}
    for item in latest or items:
        by_level.setdefault(item.cognitive_level, []).append(
            item.score / item.max_score if item.max_score else 0
        )
        by_sub.setdefault(item.subtopic, []).append(
            item.score / item.max_score if item.max_score else 0
        )
    facts = {
        "policy_version": DIAGNOSIS_POLICY_VERSION,
        "latest_correct": round(sum(i.score for i in latest), 2),
        "latest_max": round(sum(i.max_score for i in latest), 2),
        "latest_questions": len(latest),
        "all_questions": len(items),
        "attempts": len({i.attempt_rank for i in items}),
        "weighted_accuracy": None if weighted is None else round(weighted, 3),
        "recency_accuracy": None if recency is None else round(recency, 3),
        "coverage": round(coverage, 3),
        "level_accuracy": {lvl: round(sum(v) / len(v), 2) for lvl, v in by_level.items()},
        "weak_levels": sorted(lvl for lvl, v in by_level.items() if sum(v) / len(v) < 0.5),
        "subtopics": [
            {"title": t, "accuracy": round(sum(v) / len(v), 2)} for t, v in by_sub.items()
        ],
        "missed": [
            {
                "question_id": str(i.question_id),
                "attempt_id": str(i.attempt_id) if i.attempt_id else None,
            }
            for i in latest
            if i.score < i.max_score
        ],
        "limited_reason": None
        if not limited
        else (
            "not_tested"
            if not items
            else "few_questions"
            if len(items) < MIN_EVALUATED_QUESTIONS_PER_TOPIC
            else "low_confidence"
        ),
    }
    return UnitDiagnosis(
        unit.topic_id,
        unit.title,
        unit.position,
        unit.importance,
        label,
        mastery,
        round(confidence, 3),
        priority,
        len(items),
        facts,
    )


def diagnose(units: Sequence[UnitInput]) -> list[UnitDiagnosis]:
    """All approved units, ranked: highest priority first, syllabus order breaks ties."""
    diagnoses = [diagnose_unit(unit) for unit in units]
    return sorted(diagnoses, key=lambda d: (-d.priority, d.position, d.title))


def overall_score(items: Iterable[tuple[float, float]]) -> float | None:
    pairs = list(items)
    total = sum(m for _, m in pairs)
    return round(100 * sum(s for s, _ in pairs) / total, 1) if total else None
