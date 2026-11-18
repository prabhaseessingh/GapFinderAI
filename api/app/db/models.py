"""SQLAlchemy models. They mirror the Alembic schema exactly so `alembic check` stays clean."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    cast,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import CHAR, UserDefinedType

from app.db.base import Base

EMBEDDING_DIMENSIONS = 384


class Vector(UserDefinedType[list[float]]):
    """Minimal pgvector column type; values are written with explicit SQL casts."""

    cache_ok = True

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_expression(self, bindvalue: Any) -> Any:
        return cast(bindvalue, self)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    selected_locale: Mapped[str] = mapped_column(Text, server_default="en")
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy_policy_version: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        Index("workspaces_student_id_idx", "student_id"),
        Index(
            "workspaces_one_demo_idx",
            "student_id",
            unique=True,
            postgresql_where=text("demo_source IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(120))
    selected_locale: Mapped[str] = mapped_column(Text, server_default="en")
    demo_source: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "checksum_sha256", "version"),
        Index("documents_workspace_state_idx", "workspace_id", "state"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    material_role: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    mime_type: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(CHAR(64))
    version: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    state: Mapped[str] = mapped_column(Text, server_default="uploaded", default="uploaded")
    failure_code: Mapped[str | None] = mapped_column(Text)
    processing_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="chunks_document_index_key"),
        Index("chunks_workspace_idx", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text_content: Mapped[str] = mapped_column(Text)
    source_language: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}", default=list)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), deferred=True
    )
    embedding_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (Index("topics_workspace_position_idx", "workspace_id", "position"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), server_default="draft", default="draft")
    importance: Mapped[int] = mapped_column(Integer, server_default="3", default=3)
    importance_source: Mapped[str] = mapped_column(
        String(20), server_default="default", default="default"
    )
    importance_basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    position: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    origin: Mapped[str] = mapped_column(String(20), server_default="proposal", default="proposal")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class TopicChunkLink(Base):
    __tablename__ = "topic_chunk_links"
    __table_args__ = (
        Index("topic_chunk_links_chunk_idx", "chunk_id"),
        CheckConstraint("confidence >= 0 AND confidence <= 1"),
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(REAL, server_default="1.0", default=1.0)
    method: Mapped[str] = mapped_column(String(20), server_default="proposal", default="proposal")
    manual_override: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    quote: Mapped[str | None] = mapped_column(Text)


class PastPaperQuestion(Base):
    __tablename__ = "past_paper_questions"
    __table_args__ = (
        UniqueConstraint("document_id", "document_version", "position"),
        Index("past_paper_questions_workspace_idx", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    document_version: Mapped[int] = mapped_column(Integer)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    question_label: Mapped[str | None] = mapped_column(String(40))
    question_text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    marks: Mapped[float | None] = mapped_column(REAL)
    year: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class PastPaperQuestionTopic(Base):
    __tablename__ = "past_paper_question_topics"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("past_paper_questions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    method: Mapped[str] = mapped_column(String(20), server_default="model", default="model")


class CitationTranslation(Base):
    __tablename__ = "citation_translations"
    __table_args__ = (UniqueConstraint("chunk_id", "quote_hash", "target_locale"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE")
    )
    quote_hash: Mapped[str] = mapped_column(CHAR(64))
    target_locale: Mapped[str] = mapped_column(Text)
    translated_text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    operation: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(40))
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", default=list
    )
    outcome: Mapped[str] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    correlation_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("task_name", "idempotency_key"),
        Index("job_runs_workspace_idx", "workspace_id", "task_name", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    task_name: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), server_default="queued", default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    correlation_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(60))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    correlation_id: Mapped[str] = mapped_column(String(80))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = _created()


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        Index("quizzes_workspace_idx", "workspace_id", text("created_at DESC")),
        CheckConstraint("question_count IN (5, 10, 15)"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default="blueprint_draft", default="blueprint_draft"
    )
    question_count: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(Text)
    timer_mode: Mapped[str] = mapped_column(String(10), server_default="untimed", default="untimed")
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    blueprint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    policy_version: Mapped[str] = mapped_column(String(40))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(12), server_default="diagnostic", default="diagnostic")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position"),
        UniqueConstraint("quiz_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL")
    )
    topic_title: Mapped[str] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(20))
    cognitive_level: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB)
    correct_answer: Mapped[Any] = mapped_column(JSONB)
    rubric: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    explanation: Mapped[str | None] = mapped_column(Text)
    max_score: Mapped[float] = mapped_column(REAL)
    citations: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    validation_status: Mapped[str] = mapped_column(
        String(20), server_default="passed", default="passed"
    )
    created_at: Mapped[datetime] = _created()


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        Index("attempts_quiz_idx", "quiz_id", text("created_at DESC")),
        Index(
            "attempts_one_open_idx",
            "quiz_id",
            "student_id",
            unique=True,
            postgresql_where=text("state = 'in_progress'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default="in_progress", default="in_progress"
    )
    started_at: Mapped[datetime] = _created()
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submit_reason: Mapped[str | None] = mapped_column(String(20))
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attempts.id", ondelete="CASCADE")
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    answer: Mapped[Any] = mapped_column(JSONB, nullable=True)
    score: Mapped[float | None] = mapped_column(REAL)
    max_score: Mapped[float | None] = mapped_column(REAL)
    verdict: Mapped[str | None] = mapped_column(String(30))
    evaluator: Mapped[str | None] = mapped_column(String(20))
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(REAL)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _created()


class GapReport(Base):
    __tablename__ = "gap_reports"
    __table_args__ = (UniqueConstraint("workspace_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attempts.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(String(40))
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = _created()


class TopicMasterySnapshot(Base):
    __tablename__ = "topic_mastery_snapshots"
    __table_args__ = (Index("topic_mastery_snapshots_report_idx", "report_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gap_reports.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL")
    )
    topic_title: Mapped[str] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(20))
    mastery: Mapped[float | None] = mapped_column(REAL)
    confidence: Mapped[float] = mapped_column(REAL)
    priority: Mapped[float] = mapped_column(REAL)
    importance: Mapped[int] = mapped_column(Integer)
    evaluated_questions: Mapped[int] = mapped_column(Integer)
    facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = _created()


class StudyPreferences(Base):
    __tablename__ = "study_preferences"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    exam_date: Mapped[date] = mapped_column(Date)
    minutes_per_day: Mapped[int] = mapped_column(Integer)
    available_weekdays: Mapped[list[str]] = mapped_column(ARRAY(Text))
    timezone: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class RevisionPlan(Base):
    __tablename__ = "revision_plans"
    __table_args__ = (UniqueConstraint("workspace_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gap_reports.id", ondelete="CASCADE")
    )
    preferences_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("study_preferences.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))
    demand_minutes: Mapped[int] = mapped_column(Integer)
    scheduled_minutes: Mapped[int] = mapped_column(Integer)
    available_minutes: Mapped[int] = mapped_column(Integer)
    shortfall: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    policy_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = _created()


class RevisionSession(Base):
    __tablename__ = "revision_sessions"
    __table_args__ = (UniqueConstraint("plan_id", "day", "sequence"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("revision_plans.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    day: Mapped[date] = mapped_column(Date)
    sequence: Mapped[int] = mapped_column(Integer)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL")
    )
    topic_title: Mapped[str | None] = mapped_column(String(160))
    focus: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}", default=list)
    activity: Mapped[str] = mapped_column(String(10))
    minutes: Mapped[int] = mapped_column(Integer)


class SessionCompletion(Base):
    __tablename__ = "session_completions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("revision_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    completed_at: Mapped[datetime] = _created()


class Explanation(Base):
    __tablename__ = "explanations"
    __table_args__ = (Index("explanations_workspace_idx", "workspace_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(12), server_default="typed", default="typed")
    state: Mapped[str] = mapped_column(String(14), server_default="queued", default="queued")
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    next_action: Mapped[str | None] = mapped_column(String(20))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"
    __table_args__ = (UniqueConstraint("explanation_id", "kind", "config_hash"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    explanation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("explanations.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(14))
    state: Mapped[str] = mapped_column(String(14), server_default="queued", default="queued")
    config_hash: Mapped[str] = mapped_column(CHAR(64))
    storage_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
