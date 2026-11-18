from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.shared import Locale


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    selected_locale: Locale

    @field_validator("title")
    @classmethod
    def title_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Workspace title cannot be blank")
        return value


class RenameWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def title_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Workspace title cannot be blank")
        return value


class WorkspaceOut(BaseModel):
    id: UUID
    title: str
    selected_locale: Locale
    demo_source: str | None = None
    created_at: datetime
    updated_at: datetime
