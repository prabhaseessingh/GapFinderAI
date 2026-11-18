from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

MaterialRole = Literal["syllabus", "textbook", "notes", "past_paper"]
DocumentState = Literal[
    "uploaded", "scanning", "extracting", "chunking", "embedding", "mapping", "ready", "failed"
]
AcceptedMime = Literal[
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]
# Supabase Free Storage's platform limit; the app adds no lower limit of its own.
SUPABASE_FILE_LIMIT_BYTES = 50 * 1024 * 1024


class UploadIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    material_role: MaterialRole
    filename: str = Field(min_length=1, max_length=255)
    mime_type: AcceptedMime
    byte_size: PositiveInt
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class UploadIntentOut(BaseModel):
    document_id: UUID
    storage_path: str
    tus_endpoint: str
    bucket: str


class ConfirmUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    material_role: MaterialRole
    filename: str
    mime_type: str
    byte_size: int
    version: int
    state: DocumentState
    failure_code: str | None
    processing_attempts: int
    page_count: int | None
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    id: UUID
    chunk_index: int
    page_start: int | None
    page_end: int | None
    heading_path: list[str]
    text: str
    source_language: str


class DocumentSourceOut(BaseModel):
    document: DocumentOut
    chunks: list[ChunkOut]
