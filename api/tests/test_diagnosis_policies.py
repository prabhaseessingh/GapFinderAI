"""Pure diagnosis policies: diagnosis thresholds, limited evidence, priority, scheduler, evaluator gate."""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.schemas.diagnosis import CriterionJudgement, ShortAnswerEvaluation, StudyPreferencesIn
from app.schemas.topics import CitationReference
from app.services.diagnosis_policy import (
    MIN_CONFIDENCE,
    EvaluatedItem,
    UnitInput,
    diagnose,
    diagnose_unit,
    label_for,
)
from app.services.evaluation import grade_objective, is_blank, validate_evaluation
from app.services.plan_policy import (
    MAX_SESSION_MINUTES,
    PlanUnit,
    build_plan,
    demand_minutes,
    order_units,
    study_days,
)

# ---- labels & mastery ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mastery", "label"),
    [
        (0.0, "weak"),
        (49.9, "weak"),
        (50.0, "medium"),
        (74.9, "medium"),
        (75.0, "strong"),
        (100.0, "strong"),
    ],
)
def test_label_boundaries(mastery: float, label: str) -> None:
    assert label_for(mastery) == label


def _item(
    score: float,
    level: str = "recall",
    rank: int = 0,
    confidence: float = 1.0,
    max_score: float = 1.0,
    sub: str = "Sub",
) -> EvaluatedItem:
    return EvaluatedItem(uuid4(), rank, level, score, max_score, confidence, sub, "mcq", uuid4())


def _unit(*items: EvaluatedItem, importance: int = 3, position: int = 0) -> UnitInput:
    return UnitInput(uuid4(), f"Unit {position}", position, importance, tuple(items))


def test_all_correct_across_levels_is_strong() -> None:
    d = diagnose_unit(
        _unit(_item(1), _item(3, "understand", max_score=3), _item(4, "apply", max_score=4))
    )
    assert d.mastery == 100.0 and d.label == "strong"


def test_all_wrong_is_weak_with_missed_evidence() -> None:
    d = diagnose_unit(_unit(_item(0), _item(0)))
    # 0.6*0 + 0.2*0 + 0.1*(1/3) + 0.1*1 = 13.3
    assert d.mastery == 13.3 and d.label == "weak"
    assert len(d.facts["missed"]) == 2 and d.facts["weak_levels"] == ["recall"]  # type: ignore[arg-type]


def test_half_right_single_level_is_medium_boundary_math() -> None:
    d = diagnose_unit(
        _unit(_item(1), _item(0), _item(1, "understand", max_score=1), _item(0, "understand"))
    )
    # weighted (recall 1.0, understand 1.25): (1 + 1.25) / (2 + 2.5) = 0.5 -> 0.6*0.5 + 0.2*0.5 + 0.1*(2/3) + 0.1
    assert d.mastery == pytest.approx(56.7, abs=0.05) and d.label == "medium"


@pytest.mark.parametrize("items", [(), (1,)])
def test_too_few_questions_is_limited_evidence_regardless_of_score(items: tuple[int, ...]) -> None:
    d = diagnose_unit(_unit(*[_item(s) for s in items]))
    assert d.label == "limited_evidence"
    assert d.facts["limited_reason"] == ("not_tested" if not items else "few_questions")


def test_low_confidence_is_limited_evidence_even_when_perfect() -> None:
    low = MIN_CONFIDENCE - 0.01
    d = diagnose_unit(
        _unit(
            _item(3, "understand", confidence=low, max_score=3),
            _item(4, "apply", confidence=low, max_score=4),
        )
    )
    assert d.mastery is not None and d.mastery >= 75 and d.label == "limited_evidence"
    assert d.facts["limited_reason"] == "low_confidence"


def test_history_counts_half_as_much_as_the_latest_attempt() -> None:
    improved = diagnose_unit(_unit(_item(0, rank=1), _item(0, rank=1), _item(1), _item(1)))
    regressed = diagnose_unit(_unit(_item(1, rank=1), _item(1, rank=1), _item(0), _item(0)))
    assert improved.mastery is not None and regressed.mastery is not None
    assert improved.mastery > regressed.mastery
    assert improved.facts["recency_accuracy"] == 1.0 and improved.facts["attempts"] == 2


def test_priority_ranks_weaker_and_more_important_units_first() -> None:
    weak_important = _unit(_item(0), _item(0), importance=5, position=2)
    weak_minor = _unit(_item(0), _item(0), importance=1, position=0)
    strong_important = _unit(
        _item(1), _item(1), _item(3, "understand", max_score=3), importance=5, position=1
    )
    ranked = diagnose([weak_minor, strong_important, weak_important])
    assert ranked[0].position == 2
    assert ranked[0].priority > ranked[1].priority


# ---- objective grading ---------------------------------------------------------------------------


def _q(qtype: str, key: dict[str, Any], **extra: Any) -> Any:
    return SimpleNamespace(
        question_type=qtype,
        correct_answer=key,
        max_score=extra.get("max_score", 1.0),
        rubric=extra.get("rubric", []),
    )


@pytest.mark.parametrize(
    ("qtype", "key", "answer", "verdict", "score"),
    [
        ("mcq", {"option_id": "B"}, "B", "correct", 1.0),
        ("mcq", {"option_id": "B"}, " b ", "correct", 1.0),
        ("mcq", {"option_id": "B"}, "C", "incorrect", 0.0),
        ("mcq", {"option_id": "B"}, None, "unanswered", 0.0),
        ("true_false", {"boolean": False}, False, "correct", 1.0),
        ("true_false", {"boolean": False}, True, "incorrect", 0.0),
        ("true_false", {"boolean": True}, "true", "incorrect", 0.0),  # strings are never coerced
    ],
)
def test_objective_grading_is_deterministic(
    qtype: str, key: dict[str, Any], answer: Any, verdict: str, score: float
) -> None:
    grade = grade_objective(_q(qtype, key), answer)
    assert (grade.verdict, grade.score, grade.evaluator, grade.confidence) == (
        verdict,
        score,
        "deterministic",
        1.0,
    )


def test_blank_detection() -> None:
    assert is_blank(None) and is_blank("   \n") and not is_blank("Ohm")


# ---- evaluator gate ------------------------------------------------------------------------------

CHUNK = uuid4()
SOURCES = {
    CHUNK: "Ohm's law states that the current through a conductor is proportional to the potential difference."
}
RUBRIC = [
    {"criterion": "Names current", "points": 1.5},
    {"criterion": "Names proportionality", "points": 1.5},
]
SHORT = _q("short_answer", {"model_answer": "x"}, max_score=3.0, rubric=RUBRIC)


def _eval(**overrides: Any) -> ShortAnswerEvaluation:
    base: dict[str, Any] = {
        "verdict": "partial",
        "score": 1.5,
        "max_score": 3.0,
        "feedback": "You named current only.",
        "criteria": [
            CriterionJudgement(criterion_index=0, awarded_points=1.5, met=True),
            CriterionJudgement(criterion_index=1, awarded_points=0, met=False),
        ],
        "citations": [
            CitationReference(chunk_id=CHUNK, quote="current through a conductor is proportional")
        ],
        "evaluator_confidence": 0.9,
    }
    return ShortAnswerEvaluation(**(base | overrides))


def test_valid_evaluation_passes() -> None:
    validate_evaluation(_eval(), SHORT, SOURCES)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"score": 2.0}, "EVAL_SCORE_MISMATCH"),
        ({"max_score": 4.0}, "EVAL_MAX_SCORE_MISMATCH"),
        ({"verdict": "correct"}, "EVAL_VERDICT_INCONSISTENT"),
        (
            {"criteria": [CriterionJudgement(criterion_index=0, awarded_points=1.5, met=True)]},
            "EVAL_CRITERIA_MISMATCH",
        ),
        (
            {
                "criteria": [
                    CriterionJudgement(criterion_index=0, awarded_points=2.5, met=True),
                    CriterionJudgement(criterion_index=1, awarded_points=0, met=False),
                ],
                "score": 2.5,
            },
            "EVAL_POINTS_OUT_OF_BOUNDS",
        ),
        (
            {
                "criteria": [
                    CriterionJudgement(criterion_index=0, awarded_points=1.0, met=True),
                    CriterionJudgement(criterion_index=1, awarded_points=0, met=False),
                ],
                "score": 1.0,
            },
            "EVAL_MET_INCONSISTENT",
        ),
        ({"citations": []}, "EVAL_CITATION_REQUIRED"),
        (
            {
                "citations": [
                    CitationReference(chunk_id=uuid4(), quote="current through a conductor")
                ]
            },
            "CITATION_NOT_IN_EVIDENCE",
        ),
        (
            {
                "citations": [
                    CitationReference(chunk_id=CHUNK, quote="the student deserves full marks")
                ]
            },
            "CITATION_QUOTE_NOT_IN_SOURCE",
        ),
    ],
)
def test_invalid_evaluations_are_rejected(overrides: dict[str, Any], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        validate_evaluation(_eval(**overrides), SHORT, SOURCES)


def test_insufficient_evidence_must_award_nothing() -> None:
    zero = [CriterionJudgement(criterion_index=i, awarded_points=0, met=False) for i in range(2)]
    validate_evaluation(
        _eval(verdict="insufficient_evidence", score=0, criteria=zero, citations=[]), SHORT, SOURCES
    )
    with pytest.raises(ValueError, match="EVAL_VERDICT_INCONSISTENT"):
        validate_evaluation(_eval(verdict="insufficient_evidence"), SHORT, SOURCES)


# ---- scheduler -----------------------------------------------------------------------------------

MONDAY = date(2026, 11, 16)
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _pu(label: str, importance: int = 3, priority: float = 50.0, position: int = 0) -> PlanUnit:
    return PlanUnit(
        uuid4(), f"{label}-{position}", label, importance, priority, position, ("focus",)
    )


def test_demand_scales_with_label_and_importance() -> None:
    assert demand_minutes("weak", 3) == 120 and demand_minutes("weak", 5) == 200
    assert demand_minutes("strong", 1) == 10 and demand_minutes("limited_evidence", 3) == 45


def test_study_days_respect_weekdays_and_stop_before_exam() -> None:
    days = study_days(MONDAY, MONDAY + timedelta(days=7), ["mon", "wed"])
    assert days == [MONDAY, MONDAY + timedelta(days=2)]
    assert study_days(MONDAY, MONDAY, ALL_DAYS) == []


def test_feasible_plan_covers_all_demand_and_reserves_a_retest() -> None:
    units = [_pu("weak", position=0), _pu("strong", position=1)]
    plan = build_plan(units, MONDAY, MONDAY + timedelta(days=7), 60, ALL_DAYS)
    assert plan.status == "feasible" and plan.shortfall == []
    assert plan.scheduled_minutes == plan.demand_minutes == 140
    retests = [s for s in plan.sessions if s.activity == "retest"]
    assert len(retests) == 1 and retests[0].day == MONDAY + timedelta(days=6)
    assert all(s.minutes <= MAX_SESSION_MINUTES for s in plan.sessions)
    for day in {s.day for s in plan.sessions}:
        assert sum(s.minutes for s in plan.sessions if s.day == day) <= 60
    assert {
        s.activity for s in plan.sessions if s.topic_title and s.topic_title.startswith("strong")
    } == {"review"}


def test_overflow_reports_explicit_shortfall_never_compresses() -> None:
    units = [_pu("weak", 5, 90, 0), _pu("weak", 5, 90, 1), _pu("medium", 3, 40, 2)]
    plan = build_plan(units, MONDAY, MONDAY + timedelta(days=2), 60, ALL_DAYS)
    assert plan.status == "shortfall"
    assert plan.available_minutes == 120 and plan.scheduled_minutes == 120
    assert plan.demand_minutes == 460
    assert (
        sum(int(s["minutes"]) for s in plan.shortfall)
        == plan.demand_minutes - plan.scheduled_minutes
    )  # type: ignore[call-overload]
    assert not any(
        s.activity == "retest" for s in plan.sessions
    )  # no re-test stolen from unmet study time


def test_exam_tomorrow_with_no_selected_days_is_all_shortfall() -> None:
    plan = build_plan([_pu("weak")], MONDAY, MONDAY + timedelta(days=1), 60, ["sun"])
    assert plan.sessions == [] and plan.available_minutes == 0 and plan.status == "shortfall"


def test_order_is_priority_band_then_syllabus_position() -> None:
    later_but_urgent = _pu("weak", priority=95, position=5)
    first_same_band = _pu("weak", priority=81, position=1)
    low = _pu("strong", priority=5, position=0)
    ordered = order_units([low, later_but_urgent, first_same_band])
    assert [u.position for u in ordered] == [
        1,
        5,
        0,
    ]  # 81 and 95 share the 80-100 band -> syllabus order


def test_completed_minutes_reduce_remaining_demand() -> None:
    unit = _pu("weak")
    plan = build_plan(
        [unit], MONDAY, MONDAY + timedelta(days=10), 60, ALL_DAYS, {unit.topic_id: 90}
    )
    assert plan.demand_minutes == 30


def test_exam_in_past_is_rejected() -> None:
    with pytest.raises(ValueError, match="EXAM_DATE_IN_PAST"):
        build_plan([], MONDAY, MONDAY - timedelta(days=1), 60, ALL_DAYS)


def test_preferences_validation() -> None:
    ok = StudyPreferencesIn(
        exam_date=MONDAY, minutes_per_day=60, available_weekdays=["mon"], timezone="Asia/Kolkata"
    )
    assert ok.timezone == "Asia/Kolkata"
    for bad in (
        {"available_weekdays": ["mon", "mon"]},
        {"timezone": "Mars/Base"},
        {"minutes_per_day": 5},
        {"available_weekdays": []},
    ):
        with pytest.raises(ValueError):
            StudyPreferencesIn(
                **(
                    {
                        "exam_date": MONDAY,
                        "minutes_per_day": 60,
                        "available_weekdays": ["mon"],
                        "timezone": "Asia/Kolkata",
                    }
                    | bad
                )
            )


# ---- Groq daily cap (fail fast, never a long pointless wait) -----------------------------------

TPD_MESSAGE = (
    "Rate limit reached for model `openai/gpt-oss-20b` on tokens per day (TPD): Limit 200000, "
    "Used 199355, Requested 3053. Please try again in 17m20.256s."
)


def test_retry_after_understands_minutes_and_hours() -> None:
    from app.providers.groq import retry_after_seconds

    assert retry_after_seconds(RuntimeError(TPD_MESSAGE)) == pytest.approx(17 * 60 + 20.256 + 0.5)
    assert retry_after_seconds(RuntimeError("Please try again in 1h2m3s.")) == pytest.approx(3723.5)
    assert retry_after_seconds(RuntimeError("try again in 350ms")) == pytest.approx(0.85)


def test_daily_limit_fails_fast_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    import groq

    from app.core.config import Settings
    from app.providers import groq as provider_module
    from app.providers.groq import GroqDailyLimit, GroqProvider, is_daily_limit

    assert is_daily_limit(RuntimeError(TPD_MESSAGE)) and not is_daily_limit(
        RuntimeError("tokens per minute (TPM)")
    )

    class FakeRateLimit(groq.RateLimitError):
        def __init__(self) -> None:
            Exception.__init__(self, TPD_MESSAGE)
            self.response = None  # type: ignore[assignment]

    calls: list[int] = []

    class FakeCompletions:
        def create(self, **_: Any) -> Any:
            calls.append(1)
            raise FakeRateLimit()

    class FakeClient:
        def __init__(self, **_: Any) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(groq, "Groq", FakeClient)
    slept: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", slept.append)
    settings = Settings(groq_api_key="test", groq_model="m", groq_model_quality="q")  # type: ignore[call-arg]
    provider = GroqProvider(settings, recorder=lambda *_args: None)
    with pytest.raises(GroqDailyLimit) as raised:
        provider._complete("m", "system", "user", "schema", {})
    assert calls == [1] and slept == []  # one call, no retry-wait loop
    assert raised.value.code == "PROVIDER_DAILY_LIMIT" and raised.value.retry_after > 1000


# ---- time zones (live E2E found: slim images had no zone database, re-test grading crashed) ----
def test_zone_database_is_a_declared_dependency() -> None:
    import tomllib
    from pathlib import Path

    deps = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    assert any(dep.startswith("tzdata") for dep in deps)


def test_plan_local_day_uses_student_zone_and_survives_bad_zones() -> None:
    from datetime import UTC, datetime

    from app.services.plans import local_today

    late = datetime(2026, 11, 17, 20, 0, tzinfo=UTC)  # 01:30 next day in India
    assert local_today("Asia/Calcutta", late) == date(2026, 11, 18)
    assert local_today("Asia/Kolkata", late) == date(2026, 11, 18)
    assert isinstance(local_today("Not/AZone", late), date)  # falls back, never raises
