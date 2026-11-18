"""Deterministic diagnostic blueprint. Pure functions: no I/O, no LLM.

Rules:
* Coverage is allocated by top-level **unit**: every selected unit gets >= 2 questions (the
  diagnosis minimum), extra slots follow unit importance (largest remainder), and a unit's slots
  rotate across its sub-topics (highest importance first).
* If there are more units than questions/2, the highest-importance units are tested first; the
  rest are recorded as `not_tested` (never silently dropped).
* Question type follows cognitive level: recall -> MCQ or true/false (2:1), understand/apply ->
  typed short answer. A unit's slots cycle recall -> understand -> apply -> recall ...
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal
from uuid import UUID

QUIZ_POLICY_VERSION = "quiz-blueprint-2026-11-17"
MIN_QUESTIONS_PER_UNIT = 2
COGNITIVE_CYCLE: tuple[str, ...] = ("recall", "understand", "apply")
RECALL_TYPE_CYCLE: tuple[str, ...] = ("mcq", "mcq", "true_false")
SCORE_BY_TYPE = {"mcq": 1.0, "true_false": 1.0}
SHORT_ANSWER_SCORE = {"understand": 3.0, "apply": 4.0}

QuestionType = Literal["mcq", "true_false", "short_answer"]


@dataclass(frozen=True)
class Leaf:
    topic_id: UUID
    title: str
    importance: int
    position: int


@dataclass(frozen=True)
class UnitCandidate:
    topic_id: UUID
    title: str
    importance: int
    position: int
    leaves: tuple[Leaf, ...]  # sub-topics with evidence (or the unit itself)


@dataclass(frozen=True)
class Slot:
    position: int
    unit_id: UUID
    unit_title: str
    topic_id: UUID
    topic_title: str
    cognitive_level: str
    question_type: str
    max_score: float


@dataclass
class Blueprint:
    question_count: int
    slots: list[Slot]
    not_tested: list[dict[str, str]] = field(default_factory=list)
    policy_version: str = QUIZ_POLICY_VERSION

    def as_json(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "question_count": self.question_count,
            "slots": [
                {k: str(v) if isinstance(v, UUID) else v for k, v in asdict(s).items()}
                for s in self.slots
            ],
            "not_tested": self.not_tested,
        }


class NoEligibleUnits(ValueError):
    pass


def allocate(units: Sequence[UnitCandidate], question_count: int) -> dict[UUID, int]:
    if question_count not in (5, 10, 15):
        raise ValueError("question_count must be 5, 10 or 15")
    eligible = [u for u in units if u.leaves]
    if not eligible:
        raise NoEligibleUnits("INSUFFICIENT_WORKSPACE_EVIDENCE")
    chosen = sorted(eligible, key=lambda u: (-u.importance, u.position, u.title))
    chosen = chosen[: max(1, question_count // MIN_QUESTIONS_PER_UNIT)]
    counts = {u.topic_id: MIN_QUESTIONS_PER_UNIT for u in chosen}
    remaining = question_count - MIN_QUESTIONS_PER_UNIT * len(chosen)
    if remaining < 0:  # a single eligible unit and question_count < 2 cannot happen (min 5)
        raise ValueError("invalid allocation")
    total = sum(u.importance for u in chosen)
    shares = [(u, remaining * u.importance / total) for u in chosen]
    for unit, share in shares:
        counts[unit.topic_id] += int(share)
    leftover = remaining - sum(int(share) for _, share in shares)
    ranked = sorted(
        shares, key=lambda item: (-(item[1] - int(item[1])), -item[0].importance, item[0].position)
    )
    for unit, _ in ranked[:leftover]:
        counts[unit.topic_id] += 1
    return counts


def build_blueprint(units: Sequence[UnitCandidate], question_count: int) -> Blueprint:
    counts = allocate(units, question_count)
    by_id = {u.topic_id: u for u in units}
    slots: list[Slot] = []
    recall_seen = 0
    ordered_units = sorted((by_id[i] for i in counts), key=lambda u: (u.position, u.title))
    for unit in ordered_units:
        leaves = sorted(unit.leaves, key=lambda leaf: (-leaf.importance, leaf.position, leaf.title))
        for index in range(counts[unit.topic_id]):
            leaf = leaves[index % len(leaves)]
            level = COGNITIVE_CYCLE[index % len(COGNITIVE_CYCLE)]
            if level == "recall":
                qtype = RECALL_TYPE_CYCLE[recall_seen % len(RECALL_TYPE_CYCLE)]
                recall_seen += 1
                score = SCORE_BY_TYPE[qtype]
            else:
                qtype, score = "short_answer", SHORT_ANSWER_SCORE[level]
            slots.append(
                Slot(
                    len(slots),
                    unit.topic_id,
                    unit.title,
                    leaf.topic_id,
                    leaf.title,
                    level,
                    qtype,
                    score,
                )
            )
    not_tested = [
        {
            "topic_id": str(u.topic_id),
            "title": u.title,
            "reason": "no_evidence" if not u.leaves else "question_budget",
        }
        for u in sorted(units, key=lambda u: u.position)
        if u.topic_id not in counts
    ]
    return Blueprint(question_count, slots, not_tested)
