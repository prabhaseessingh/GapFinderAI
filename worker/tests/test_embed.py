"""Worker embedding entry points: query vs document kind, error mapping, stored label."""

from typing import Any, ClassVar

import pytest
from app.providers.embeddings import EMBEDDING_LABEL, EmbeddingError
from tasks import ingest
from tasks.extraction import ExtractionError


class FakeClient:
    calls: ClassVar[list[tuple[list[str], str]]] = []
    fail: ClassVar[str | None] = None

    def __init__(self, _settings: Any) -> None:
        if FakeClient.fail:
            raise EmbeddingError(FakeClient.fail)

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        FakeClient.calls.append((texts, kind))
        return [[1.0] + [0.0] * 383 for _ in texts]


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.calls, FakeClient.fail = [], None
    monkeypatch.setattr(ingest, "EmbeddingClient", FakeClient)


def test_documents_and_queries_use_their_kind() -> None:
    assert len(ingest.embed_texts(["a", "b"])) == 2
    assert len(ingest.embed_query("why?")) == 384
    assert FakeClient.calls == [(["a", "b"], "document"), (["why?"], "query")]


def test_missing_worker_is_a_visible_extraction_failure() -> None:
    FakeClient.fail = "EMBEDDING_RUNTIME_UNAVAILABLE"
    with pytest.raises(ExtractionError) as error:
        ingest.embed_texts(["x"])
    assert str(error.value) == "EMBEDDING_RUNTIME_UNAVAILABLE"


def test_stored_label_is_the_model_label() -> None:
    assert ingest.embedding_label() == EMBEDDING_LABEL
