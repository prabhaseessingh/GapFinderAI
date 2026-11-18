"""Contracts: grounded explanation (Groq output, re-validated locally), visual brief,
and the Explain / voice / asset / limits API shapes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.shared import Locale
from app.schemas.topics import CitationOut, CitationReference

Origin = Literal["typed", "voice", "topic", "report", "question"]


# ---- Groq outputs ---------------------------------------------------------------------------------


class GroundedExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(max_length=4000)
    citations: list[CitationReference] = Field(max_length=4)
    insufficient_workspace_evidence: bool
    suggested_next_action: Literal["upload_material", "select_material", "none"]


class VisualElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    citation: CitationReference


class VisualRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=60)
    relation: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=60)


class VisualBrief(BaseModel):
    """Only citation-backed entities and relations between them; nothing else reaches the image model."""

    model_config = ConfigDict(extra="forbid")
    visualizable: bool
    kind: Literal["process", "structure", "comparison", "cycle", "none"]
    title: str = Field(max_length=80)
    elements: list[VisualElement] = Field(max_length=8)
    relations: list[VisualRelation] = Field(max_length=10)


# ---- API -----------------------------------------------------------------------------------------


class CreateExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    question: str = Field(min_length=3, max_length=1000)
    locale: Locale
    topic_id: UUID | None = None
    origin: Origin = "typed"


class AssetOut(BaseModel):
    id: UUID
    explanation_id: UUID
    kind: Literal["audio", "illustration", "source_figure"]
    state: Literal["queued", "rendering", "ready", "not_eligible", "failed"]
    failure_code: str | None
    mime_type: str | None
    url: str | None = None  # short-lived signed URL, present only when ready
    meta: dict[str, object] = {}


class ExplanationOut(BaseModel):
    id: UUID
    workspace_id: UUID
    topic_id: UUID | None
    question: str
    locale: str
    origin: Origin
    state: Literal["queued", "running", "answered", "insufficient", "failed"]
    answer: str | None
    citations: list[CitationOut]
    next_action: str | None
    failure_code: str | None
    created_at: datetime
    assets: list[AssetOut] = []
    voice_available: bool = False
    voice_reason: str | None = None
    visual_available: bool = False
    visual_reason: str | None = None


class ExplanationSummaryOut(BaseModel):
    id: UUID
    question: str
    state: str
    origin: Origin
    created_at: datetime


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    locale: Locale
    mime_type: str = Field(max_length=60)
    audio_base64: str = Field(min_length=16, max_length=3_000_000)


class TranscribeOut(BaseModel):
    text: str


class UsageOut(BaseModel):
    action: Literal["diagnostic", "explain", "voice", "visual"]
    used: int
    limit: int
    resets_at: datetime


class LimitsOut(BaseModel):
    timezone: str
    actions: list[UsageOut]


class ProviderStatusOut(BaseModel):
    groq: bool
    voice: bool
    visual: bool
