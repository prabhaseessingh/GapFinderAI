from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.topics import CitationOut, CitationReference

QuestionType = Literal["mcq", "true_false", "short_answer"]
CognitiveLevel = Literal["recall", "understand", "apply"]


# ---- Groq output, re-validated locally ----------------------------------------------------------


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-E]$")
    text: str = Field(min_length=1, max_length=400)


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion: str = Field(min_length=3, max_length=400)
    points: float = Field(gt=0, le=10)


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: QuestionType
    cognitive_level: CognitiveLevel
    prompt: str = Field(min_length=10, max_length=1200)
    options: list[QuestionOption] | None
    correct_option_id: str | None
    correct_boolean: bool | None
    model_answer: str | None
    rubric: list[RubricCriterion]
    max_score: float = Field(gt=0, le=10)
    explanation: str = Field(min_length=5, max_length=1500)
    citations: list[CitationReference] = Field(min_length=1, max_length=3)


# ---- API -----------------------------------------------------------------------------------------


class CreateQuizRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    kind: Literal["diagnostic", "retest"] = "diagnostic"
    question_count: Literal[5, 10, 15] = 10
    topic_ids: list[UUID] | None = Field(default=None, max_length=200)
    timer_mode: Literal["untimed", "timed"] = "untimed"
    time_limit_minutes: int | None = Field(default=None, ge=1, le=240)

    @model_validator(mode="after")
    def timer_is_consistent(self) -> "CreateQuizRequest":
        if (self.timer_mode == "timed") != (self.time_limit_minutes is not None):
            raise ValueError("time_limit_minutes is required for timed quizzes only")
        return self


class QuizSummaryOut(BaseModel):
    id: UUID
    workspace_id: UUID
    state: Literal["blueprint_draft", "generating", "ready", "generation_failed"]
    kind: Literal["diagnostic", "retest"] = "diagnostic"
    question_count: int
    locale: str
    timer_mode: Literal["untimed", "timed"]
    time_limit_seconds: int | None
    failure_code: str | None
    created_at: datetime
    not_tested: list[dict[str, str]] = []
    unit_titles: list[str] = []
    latest_attempt_id: UUID | None = None
    latest_attempt_state: str | None = None
    latest_attempt_score: float | None = None
    progress_done: int = 0


class StudentQuestionOut(BaseModel):
    """What a student sees while answering: never the key, rubric, explanation or citations."""

    model_config = ConfigDict(extra="forbid")
    id: UUID
    position: int
    topic_title: str
    question_type: QuestionType
    cognitive_level: CognitiveLevel
    prompt: str
    options: list[QuestionOption] | None
    max_score: float


class ReviewQuestionOut(StudentQuestionOut):
    """After submission only: the key and the cited source evidence."""

    model_config = ConfigDict(extra="forbid")
    correct_option_id: str | None
    correct_boolean: bool | None
    model_answer: str | None
    rubric: list[RubricCriterion]
    explanation: str | None
    citations: list[CitationOut]
    # Evaluation (present once graded)
    score: float | None = None
    verdict: str | None = None
    evaluator: str | None = None
    confidence: float | None = None
    feedback: str | None = None
    criteria: list[dict[str, Any]] = []
    evaluation_citations: list[CitationOut] = []


Answer = str | bool | None


class SubmitResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Answer = None


class AttemptOut(BaseModel):
    id: UUID
    quiz_id: UUID
    workspace_id: UUID
    state: str
    started_at: datetime
    deadline_at: datetime | None
    submitted_at: datetime | None
    submit_reason: str | None
    elapsed_seconds: int | None
    server_now: datetime
    timer_mode: Literal["untimed", "timed"]
    questions: list[StudentQuestionOut] | list[ReviewQuestionOut]
    answers: dict[str, Any]
    quiz_kind: str = "diagnostic"
    failure_code: str | None = None
    score: float | None = None
    max_score: float | None = None
    report_id: UUID | None = None
