import hashlib
import uuid
from typing import Any

import pytest
from app.db.models import Chunk, Document, JobRun, Workspace
from app.db.session import SessionLocal
from sqlalchemy import func, select, text
from tasks import ingest

pytestmark = pytest.mark.usefixtures("migrated")
SYLLABUS = b"# Unit 1 Cells\nCells are the unit of life.\n# Unit 2 Genetics\nGenes carry traits.\nGenes carry traits."


@pytest.fixture()
def document(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        ingest, "embed_texts", lambda texts: [[0.1] * 384 for _ in texts]
    )
    monkeypatch.setattr(ingest, "_download", lambda _key: SYLLABUS)
    monkeypatch.setattr(
        ingest.get_settings(), "groq_api_key", None
    )  # tests choose explicitly
    sent: list[tuple[str, list[str], str]] = []
    monkeypatch.setattr(
        ingest,
        "send_task",
        lambda _r, task, args, _c, key: sent.append((task, args, key)),
    )
    with SessionLocal() as session:
        student = uuid.uuid4()
        session.execute(text("INSERT INTO auth.users (id) VALUES (:i)"), {"i": student})
        session.execute(
            text("INSERT INTO profiles (id) VALUES (:i) ON CONFLICT DO NOTHING"),
            {"i": student},
        )
        workspace = Workspace(student_id=student, title="W", selected_locale="en")
        session.add(workspace)
        session.flush()
        doc = Document(
            workspace_id=workspace.id,
            student_id=student,
            material_role="syllabus",
            filename="s.txt",
            storage_key=f"k/{uuid.uuid4()}",
            mime_type="text/plain",
            byte_size=len(SYLLABUS),
            checksum_sha256=hashlib.sha256(SYLLABUS).hexdigest(),
            state="scanning",
        )
        session.add(doc)
        session.commit()
        yield doc.id, sent


def _run(document_id: uuid.UUID) -> str:
    return ingest.process_document.apply(args=[str(document_id)]).get()  # type: ignore[no-any-return]


def test_pipeline_reaches_mapping_and_queues_topic_proposal(
    document: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, sent = document
    monkeypatch.setattr(ingest.get_settings(), "groq_api_key", "k")
    monkeypatch.setattr(ingest.get_settings(), "groq_model", "m")
    assert _run(document_id) == "mapping"
    with SessionLocal() as session:
        chunks = session.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
        ).all()
        assert [c.heading_path for c in chunks] == [
            ["Unit 1 Cells"],
            ["Unit 2 Genetics"],
        ]
        assert (
            session.scalar(
                select(func.count()).where(
                    Chunk.document_id == document_id, Chunk.embedding.is_not(None)
                )
            )
            == 2
        )
        job = session.scalar(
            select(JobRun).where(JobRun.idempotency_key == f"{document_id}:v1")
        )
        assert job is not None and job.state == "succeeded" and job.attempts == 1
    assert sent and sent[0][0] == "gapfinder.propose_topic_map"


def test_rerun_is_idempotent_and_does_not_duplicate_chunks(document: Any) -> None:
    document_id, _ = document
    assert (
        _run(document_id) == "ready"
    )  # Groq not configured in tests → straight to ready
    with SessionLocal() as session:
        session.execute(
            text("UPDATE documents SET state = 'scanning' WHERE id = :d"),
            {"d": document_id},
        )
        session.commit()
    assert _run(document_id) == "ready"
    with SessionLocal() as session:
        assert (
            session.scalar(select(func.count()).where(Chunk.document_id == document_id))
            == 2
        )
        assert session.get(Document, document_id).processing_attempts == 2  # type: ignore[union-attr]


def test_checksum_mismatch_fails_with_safe_code(
    document: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, _ = document
    monkeypatch.setattr(ingest, "_download", lambda _key: b"tampered bytes")
    assert _run(document_id) == "failed"
    with SessionLocal() as session:
        failed = session.get(Document, document_id)
        assert failed is not None and failed.failure_code == "CHECKSUM_MISMATCH"
        assert (
            session.scalar(select(func.count()).where(Chunk.document_id == document_id))
            == 0
        )


def test_terminal_documents_are_not_reprocessed(document: Any) -> None:
    document_id, _ = document
    _run(document_id)
    assert _run(document_id) == "ready"


def test_advisory_lock_is_released_even_after_many_commits() -> None:
    from tasks.common import advisory_lock

    with SessionLocal() as session:
        with advisory_lock(session, "lock-test") as first:
            assert first
            session.commit()  # job sessions commit repeatedly while holding the lock
            with SessionLocal() as other, advisory_lock(other, "lock-test") as second:
                assert not second  # held elsewhere
        with SessionLocal() as other, advisory_lock(other, "lock-test") as third:
            assert third  # released on the connection that took it
