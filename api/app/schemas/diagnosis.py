"""Contracts: short-answer evaluator output (Groq, re-validated locally) and the
Gap Report / study preferences / revision plan / progress API shapes."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.topics import CitationOut, CitationReference

Label = Literal["weak", "medium", "strong", "limited_evidence"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---- Groq output ---------------------------------------------------------------------------------


class CriterionJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_index: int = Field(ge=0, le=9)
    awarded_points: float = Field(ge=0, le=10)
    met: bool


class ShortAnswerEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["correct", "partial", "incorrect", "insufficient_evidence"]
    criteria: list[CriterionJudgement] = Field(min_length=1, max_length=4)
    score: float = Field(ge=0, le=10)
    max_score: float = Field(gt=0, le=10)
    feedback: str = Field(min_length=5, max_length=1200)
    citations: list[CitationReference] = Field(max_length=3)
    evaluator_confidence: float = Field(ge=0, le=1)


# ---- Gap Report ----------------------------------------------------------------------------------


class MissedQuestionOut(BaseModel):
    question_id: UUID
    attempt_id: UUID
    prompt: str
    question_type: str
    cognitive_level: str
    topic_title: str
    score: float | None
    max_score: float
    verdict: str | None
    feedback: str | None
    citations: list[CitationOut]


class UnitReportOut(BaseModel):
    topic_id: UUID | None
    title: str
    position: int
    label: Label
    mastery: float | None
    confidence: float
    priority: float
    importance: int
    importance_source: str | None = None
    evaluated_questions: int
    facts: dict[str, object]
    reasons: list[str]  # stable reason codes the UI renders in the selected language
    action: Literal["study", "review", "retest", "gather_evidence"]
    missed: list[MissedQuestionOut] = []
    previous_label: Label | None = None
    previous_mastery: float | None = None


class GapReportOut(BaseModel):
    id: UUID
    workspace_id: UUID
    version: int
    attempt_id: UUID | None
    quiz_kind: str | None
    policy_version: str
    created_at: datetime
    summary: dict[str, object]
    units: list[UnitReportOut]
    previous_report_id: UUID | None = None


class ReportVersionOut(BaseModel):
    id: UUID
    version: int
    created_at: datetime
    attempt_id: UUID | None
    quiz_kind: str | None
    overall_score: float | None


# ---- availability & plans ------------------------------------------------------------------------


class StudyPreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_date: date
    minutes_per_day: int = Field(ge=10, le=720)
    available_weekdays: list[Weekday] = Field(min_length=1, max_length=7)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("available_weekdays")
    @classmethod
    def unique_days(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("weekdays must be unique")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as error:
            raise ValueError("unknown timezone") from error
        return value


class StudyPreferencesOut(StudyPreferencesIn):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    created_at: datetime


class PlanSessionOut(BaseModel):
    id: UUID
    day: date
    sequence: int
    topic_id: UUID | None
    topic_title: str | None
    focus: list[str]
    activity: Literal["study", "review", "retest"]
    minutes: int
    completed_at: datetime | None


class RevisionPlanOut(BaseModel):
    id: UUID
    version: int
    report_id: UUID
    report_version: int
    preferences: StudyPreferencesOut
    status: Literal["feasible", "shortfall"]
    demand_minutes: int
    scheduled_minutes: int
    available_minutes: int
    shortfall: list[dict[str, object]]
    policy_version: str
    created_at: datetime
    sessions: list[PlanSessionOut]
    is_latest: bool = True


class PlanVersionOut(BaseModel):
    id: UUID
    version: int
    report_version: int
    status: str
    created_at: datetime


class PlanStateOut(BaseModel):
    preferences: StudyPreferencesOut | None
    plan: RevisionPlanOut | None
    next_action: Literal["take_diagnostic", "set_availability", "none"]


# ---- progress ------------------------------------------------------------------------------------


class ProgressPoint(BaseModel):
    report_id: UUID
    version: int
    created_at: datetime
    quiz_kind: str | None
    overall_score: float | None
    units: dict[str, float | None]  # topic title -> mastery (None = limited evidence)
    labels: dict[str, str]


class ProgressOut(BaseModel):
    reports: list[ProgressPoint]
    unit_titles: list[str]
    completion: dict[str, int]  # sessions planned/completed and minutes in the latest plan
