from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.shared import Locale

PRIVACY_POLICY_VERSION = "2026-11-17.v1"


class ProfileOut(BaseModel):
    id: UUID
    display_name: str | None
    selected_locale: Locale
    privacy_accepted_at: datetime | None
    privacy_policy_version: str | None
    timezone: str | None = None
    current_privacy_policy_version: str = PRIVACY_POLICY_VERSION

    @property
    def privacy_current(self) -> bool:
        return self.privacy_policy_version == PRIVACY_POLICY_VERSION


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=80)
    selected_locale: Locale | None = None
    accept_privacy_policy_version: str | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as error:
            raise ValueError("unknown timezone") from error
        return value
