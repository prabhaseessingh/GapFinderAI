from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_title(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Topic title cannot be blank")
    return value


class CitationReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    quote: str = Field(min_length=1, max_length=1200)


# ---- Groq output schemas (validated again locally) ---------------------------------------------


class ProposedTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    parent_title: str | None
    citations: list[CitationReference] = Field(min_length=1, max_length=6)

    @field_validator("title")
    @classmethod
    def title_has_text(cls, value: str) -> str:
        return _clean_title(value)


class TopicProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[ProposedTopic] = Field(min_length=1, max_length=60)


class SegmentedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    label: str | None = Field(max_length=40)
    quote: str = Field(min_length=3, max_length=2000)
    marks: float | None
    year: int | None


class PastPaperSegmentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[SegmentedQuestion] = Field(max_length=80)


class QuestionTopicAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: UUID
    topic_ids: list[UUID] = Field(max_length=3)


class PastPaperMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[QuestionTopicAssignment]


class QuoteTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    translation: str = Field(min_length=1)


class QuoteTranslations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: list[QuoteTranslation]


# ---- API schemas -------------------------------------------------------------------------------


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    title: str
    status: Literal["draft", "approved"]
    importance: int
    importance_source: Literal["default", "past_papers", "student"]
    importance_basis: dict[str, Any]
    position: int
    origin: Literal["proposal", "manual"]
    citation_count: int = 0
    past_paper_question_count: int = 0


class CitationOut(BaseModel):
    """Citation contract (topic/past-paper flavour)."""

    chunk_id: UUID
    document_id: UUID
    document_name: str
    document_version: int
    material_role: str
    page_start: int | None
    page_end: int | None
    heading_path: list[str]
    original_quote: str
    source_language: str
    translated_quote: str | None = None
    translation_locale: str | None = None
    score: float


class PastPaperQuestionOut(BaseModel):
    id: UUID
    document_id: UUID
    document_name: str
    label: str | None
    question_text: str
    page: int | None
    marks: float | None
    year: int | None
    topic_ids: list[UUID]


class UpdateTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: UUID | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    reset_importance: bool = False

    @field_validator("title")
    @classmethod
    def optional_title_has_text(cls, value: str | None) -> str | None:
        return None if value is None else _clean_title(value)


class CreateTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    title: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def title_has_text(cls, value: str) -> str:
        return _clean_title(value)


class JobStatusOut(BaseModel):
    task: str
    state: Literal["none", "queued", "running", "succeeded", "failed"]
    error_code: str | None = None
    updated_at: str | None = None
    result: dict[str, Any] = {}
