"""Embedding client: signed /embed calls, batching, MRL truncation to 384 + normalisation, retries, failures."""

import json
import math
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.providers.embeddings import (
    BATCH,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_LABEL,
    EmbeddingClient,
    EmbeddingError,
    truncate_normalise,
)
from app.providers.image_worker import sign

SECRET = "s" * 64


def settings(**overrides: Any) -> Settings:
    values = {
        "cloudflare_image_worker_url": "https://w.example.workers.dev/",
        "cloudflare_image_worker_shared_secret": SECRET,
    } | overrides
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def vector(first: float) -> list[float]:
    # 1024 dims like the model; only the first 384 may influence the stored vector.
    return [first, 2.0] + [0.0] * 382 + [100.0] * 640


class Recorder:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses = statuses or []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return httpx.Response(status, json={"error": "X"})
        texts = json.loads(request.content)["texts"]
        return httpx.Response(200, json={"data": [vector(float(i + 1)) for i in range(len(texts))]})


def client(recorder: Recorder) -> EmbeddingClient:
    return EmbeddingClient(
        settings(), transport=httpx.MockTransport(recorder), sleep=lambda _s: None
    )


def test_signed_batched_calls_to_embed_route() -> None:
    recorder = Recorder()
    vectors = client(recorder).embed([f"chunk {i}" for i in range(BATCH + 5)])
    assert len(vectors) == BATCH + 5 and all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    assert [len(json.loads(r.content)["texts"]) for r in recorder.requests] == [BATCH, 5]
    for request in recorder.requests:
        assert str(request.url) == "https://w.example.workers.dev/embed"
        body = json.loads(request.content)
        assert set(body) == {"kind", "texts"} and body["kind"] == "document"
        timestamp = int(request.headers["x-gf-timestamp"])
        assert request.headers["x-gf-signature"] == sign(SECRET, timestamp, request.content)


def test_queries_use_query_kind() -> None:
    recorder = Recorder()
    client(recorder).embed(["why does current double?"], "query")
    assert json.loads(recorder.requests[0].content)["kind"] == "query"


def test_truncates_to_384_and_normalises_ignoring_later_dimensions() -> None:
    out = truncate_normalise(vector(2.0))
    assert len(out) == EMBEDDING_DIMENSIONS
    assert math.isclose(sum(v * v for v in out), 1.0, rel_tol=1e-9)
    assert math.isclose(out[0], 2 / math.sqrt(8)) and math.isclose(out[1], 2 / math.sqrt(8))
    with pytest.raises(EmbeddingError):
        truncate_normalise([1.0] * 100)  # too short
    with pytest.raises(EmbeddingError):
        truncate_normalise([0.0] * 1024)  # zero vector


def test_rate_limits_and_outages_are_retried_then_succeed() -> None:
    recorder = Recorder([429, 503, 200])
    assert len(client(recorder).embed(["x"])) == 1
    assert len(recorder.requests) == 3


def test_auth_failures_are_not_retried() -> None:
    recorder = Recorder([401, 200])
    with pytest.raises(EmbeddingError) as error:
        client(recorder).embed(["x"])
    assert error.value.code == "EMBEDDING_FAILED" and len(recorder.requests) == 1


def test_persistent_outage_fails_after_bounded_attempts() -> None:
    recorder = Recorder([503, 503, 503, 503, 503])
    with pytest.raises(EmbeddingError):
        client(recorder).embed(["x"])
    assert len(recorder.requests) == 4


def test_wrong_vector_count_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [vector(1.0)]})  # one vector for two texts

    with pytest.raises(EmbeddingError):
        EmbeddingClient(settings(), transport=httpx.MockTransport(handler)).embed(["a", "b"])


def test_blank_texts_are_sent_as_a_placeholder_not_rejected() -> None:
    recorder = Recorder()
    client(recorder).embed(["   ", "real"])
    assert json.loads(recorder.requests[0].content)["texts"] == [".", "real"]


def test_not_configured_is_explicit() -> None:
    with pytest.raises(EmbeddingError) as error:
        EmbeddingClient(settings(cloudflare_image_worker_url=None))
    assert error.value.code == "EMBEDDING_RUNTIME_UNAVAILABLE"


def test_label_names_model_and_dimensions() -> None:
    assert EMBEDDING_LABEL == "cloudflare/@cf/qwen/qwen3-embedding-0.6b/384"
