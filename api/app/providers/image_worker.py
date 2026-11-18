"""Client for the dedicated Cloudflare image Worker (infra/cloudflare-image-worker).

Requests are server-only and signed: HMAC-SHA256 over "<unix timestamp>.<raw JSON body>", sent as
X-GF-Timestamp / X-GF-Signature. The body carries the explanation id, a fresh nonce and a bounded
prompt; the Worker fixes the model itself and rejects unsigned, stale, replayed or oversized calls.
"""

import hashlib
import hmac
import json
import secrets
import time

import httpx

from app.core.config import Settings

MAX_PROMPT_CHARACTERS = 1000


class VisualNotConfigured(RuntimeError):
    code = "VISUAL_NOT_CONFIGURED"


class VisualProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def build_request(explanation_id: str, prompt: str, nonce: str | None = None) -> bytes:
    if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARACTERS:
        raise VisualProviderError("PROMPT_INVALID")
    payload = {
        "explanation_id": explanation_id,
        "nonce": nonce or secrets.token_hex(16),
        "prompt": prompt,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


class ImageWorkerClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if not settings.visual_configured:
            raise VisualNotConfigured()
        self._url = str(settings.cloudflare_image_worker_url)
        self._secret = str(settings.cloudflare_image_worker_shared_secret)
        self._transport = transport

    def render(self, explanation_id: str, prompt: str) -> bytes:
        body = build_request(explanation_id, prompt)
        timestamp = int(time.time())
        headers = {
            "content-type": "application/json",
            "x-gf-timestamp": str(timestamp),
            "x-gf-signature": sign(self._secret, timestamp, body),
        }
        with httpx.Client(timeout=90, transport=self._transport) as client:
            response = client.post(self._url, content=body, headers=headers)
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith(
            "image/"
        ):
            raise VisualProviderError(
                {
                    401: "VISUAL_AUTH_FAILED",
                    409: "VISUAL_REPLAY_REJECTED",
                    413: "PROMPT_INVALID",
                    429: "VISUAL_RATE_LIMITED",
                }.get(response.status_code, "VISUAL_PROVIDER_ERROR")
            )
        return response.content
