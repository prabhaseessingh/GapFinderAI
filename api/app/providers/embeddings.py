"""Embeddings through the GapFinder Cloudflare Worker (POST /embed, HMAC-signed, server-only).

One open-source model everywhere (local and Render): Qwen3-Embedding-0.6B (Apache-2.0) on Workers AI.
It returns 1024 dimensions; it is trained with Matryoshka representation learning, so the first 384
dimensions, re-normalised, are a valid smaller embedding. 384 keeps the `chunks.embedding vector(384)`
column and its index unchanged. Every stored vector records EMBEDDING_LABEL so a future model change
is detectable.
"""

import json
import logging
import math
import time
from collections.abc import Callable

import httpx

from app.core.config import Settings
from app.providers.image_worker import sign

logger = logging.getLogger("gapfinder.embeddings")

EMBEDDING_DIMENSIONS = 384
EMBEDDING_LABEL = f"cloudflare/@cf/qwen/qwen3-embedding-0.6b/{EMBEDDING_DIMENSIONS}"
BATCH = 32  # Workers AI limit for this model
MAX_CHARACTERS = 8000  # Worker limit per text; chunks are far shorter
ATTEMPTS = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def truncate_normalise(vector: list[float]) -> list[float]:
    head = [float(v) for v in vector[:EMBEDDING_DIMENSIONS]]
    if len(head) != EMBEDDING_DIMENSIONS or not all(math.isfinite(v) for v in head):
        raise EmbeddingError("EMBEDDING_FAILED")
    norm = math.sqrt(sum(v * v for v in head))
    if norm == 0:
        raise EmbeddingError("EMBEDDING_FAILED")
    return [v / norm for v in head]


class EmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not settings.visual_configured:  # same Worker URL + shared secret as illustrations
            raise EmbeddingError("EMBEDDING_RUNTIME_UNAVAILABLE")
        self._url = str(settings.cloudflare_image_worker_url).rstrip("/") + "/embed"
        self._secret = str(settings.cloudflare_image_worker_shared_secret)
        self._transport = transport
        self._sleep = sleep

    def _post(self, client: httpx.Client, kind: str, texts: list[str]) -> list[list[float]]:
        body = json.dumps(
            {"kind": kind, "texts": texts}, ensure_ascii=False, separators=(",", ":")
        ).encode()
        for attempt in range(ATTEMPTS):
            timestamp = int(time.time())  # re-signed per attempt: stale timestamps are rejected
            headers = {
                "content-type": "application/json",
                "x-gf-timestamp": str(timestamp),
                "x-gf-signature": sign(self._secret, timestamp, body),
            }
            try:
                response = client.post(self._url, content=body, headers=headers)
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code == 200:
                data = response.json().get("data")
                if not isinstance(data, list) or len(data) != len(texts):
                    raise EmbeddingError("EMBEDDING_FAILED")
                return [truncate_normalise(row) for row in data]
            retryable = response is None or response.status_code in RETRY_STATUSES
            if not retryable or attempt == ATTEMPTS - 1:
                status = None if response is None else response.status_code
                logger.warning(
                    "Embedding Worker failed: HTTP %s after %d attempt(s)", status, attempt + 1
                )
                raise EmbeddingError("EMBEDDING_FAILED")
            self._sleep(min(2**attempt, 8))
        raise EmbeddingError("EMBEDDING_FAILED")  # unreachable

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if kind not in ("document", "query"):
            raise ValueError(kind)
        cleaned = [
            t.strip()[:MAX_CHARACTERS] or "." for t in texts
        ]  # the Worker rejects blank texts
        out: list[list[float]] = []
        with httpx.Client(timeout=60, transport=self._transport) as client:
            for start in range(0, len(cleaned), BATCH):
                out.extend(self._post(client, kind, cleaned[start : start + BATCH]))
        return out
