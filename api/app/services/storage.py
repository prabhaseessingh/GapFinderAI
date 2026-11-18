from dataclasses import dataclass

import httpx

from app.core.config import Settings

BUCKET = "workspace-materials"
ASSET_BUCKET = "workspace-assets"  # generated audio/illustrations (no student policies)


@dataclass(frozen=True)
class StorageObject:
    size: int
    content_type: str | None


def parse_object_metadata(payload: object, path: str) -> StorageObject | None:
    if isinstance(payload, list):
        objects = [item for item in payload if isinstance(item, dict)]
        payload = next(
            (item for item in objects if item.get("name") == path),
            objects[0] if len(objects) == 1 else None,
        )
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    size = payload.get("size", metadata.get("size"))
    if size is None:
        return None
    try:
        return StorageObject(
            size=int(size), content_type=payload.get("mimetype", metadata.get("mimetype"))
        )
    except (TypeError, ValueError):
        return None


class SupabaseStorage:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_service_role_key:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured")
        self._base_url = settings.storage_api_url
        self._headers = {
            "authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        }

    async def object_metadata(self, path: str) -> StorageObject | None:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{self._base_url}/object/info/{BUCKET}/{path}", headers=self._headers
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_object_metadata(response.json(), path)

    async def download(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{self._base_url}/object/{BUCKET}/{path}", headers=self._headers
            )
            response.raise_for_status()
            return response.content

    async def delete(self, path: str) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.delete(
                f"{self._base_url}/object/{BUCKET}/{path}", headers=self._headers
            )
        if response.status_code != 404:
            response.raise_for_status()

    async def signed_read_url(self, path: str, expires_in: int = 60, bucket: str = BUCKET) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self._base_url}/object/sign/{bucket}/{path}",
                headers=self._headers,
                json={"expiresIn": expires_in},
            )
            response.raise_for_status()
            signed_path = response.json()["signedURL"]
        return f"{self._base_url}{signed_path}"

    def upload_sync(
        self, path: str, content: bytes, content_type: str, bucket: str = ASSET_BUCKET
    ) -> None:
        """Worker-side upload of a generated asset (overwrites a failed earlier attempt)."""
        response = httpx.post(
            f"{self._base_url}/object/{bucket}/{path}",
            content=content,
            timeout=60,
            headers=self._headers | {"content-type": content_type, "x-upsert": "true"},
        )
        response.raise_for_status()

    async def delete_many(self, paths: list[str], bucket: str = BUCKET) -> None:
        """Bulk-remove objects (used by document/workspace deletion). Missing objects are fine."""
        for start in range(0, len(paths), 500):
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(
                    "DELETE",
                    f"{self._base_url}/object/{bucket}",
                    headers=self._headers,
                    json={"prefixes": paths[start : start + 500]},
                )
            response.raise_for_status()

    @property
    def tus_endpoint(self) -> str:
        return f"{self._base_url}/upload/resumable"
