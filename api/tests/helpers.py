"""Shared test helpers (imported as `tests.helpers` everywhere so there is one signing key)."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import text
from sqlalchemy.orm import Session

_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


def make_student(session: Session) -> uuid.UUID:
    student_id = uuid.uuid4()
    session.execute(text("INSERT INTO auth.users (id) VALUES (:id)"), {"id": student_id})
    session.execute(
        text("INSERT INTO profiles (id) VALUES (:id) ON CONFLICT DO NOTHING"), {"id": student_id}
    )
    session.commit()
    return student_id


def token_for(
    student_id: uuid.UUID, *, expires_in: int = 600, metadata: dict[str, Any] | None = None
) -> str:
    from app.core.config import get_settings

    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(student_id),
            "aud": settings.supabase_jwt_audience,
            "iss": settings.supabase_jwt_issuer,
            "iat": now,
            "exp": now + expires_in,
            "user_metadata": metadata or {},
        },
        _PRIVATE_KEY,
        algorithm="ES256",
        headers={"kid": "test"},
    )


class _FakeJwks:
    def get_signing_key_from_jwt(self, _token: str) -> Any:
        return type("Key", (), {"key": _PRIVATE_KEY.public_key()})()


@dataclass
class FakeStorage:
    objects: dict[str, int] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    _base_url: str = "https://test.supabase.local/storage/v1"

    @property
    def tus_endpoint(self) -> str:
        return f"{self._base_url}/upload/resumable"

    async def object_metadata(self, path: str) -> Any:
        from app.services.storage import StorageObject

        return (
            StorageObject(size=self.objects[path], content_type=None)
            if path in self.objects
            else None
        )

    async def delete(self, path: str) -> None:
        self.deleted.append(path)
        self.objects.pop(path, None)

    async def delete_many(self, paths: list[str], bucket: str = "workspace-materials") -> None:
        for path in paths:
            await self.delete(path)

    def upload_sync(
        self, path: str, content: bytes, content_type: str, bucket: str = "workspace-assets"
    ) -> None:
        self.objects[path] = len(content)

    async def signed_read_url(
        self, path: str, expires_in: int = 60, bucket: str = "workspace-materials"
    ) -> str:
        return f"{self._base_url}/object/sign/x/{path}?token=t"


def auth_headers(student_id: uuid.UUID) -> dict[str, str]:
    return {"authorization": f"Bearer {token_for(student_id)}"}
