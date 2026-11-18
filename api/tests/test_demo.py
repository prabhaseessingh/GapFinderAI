"""Demo snapshot export -> per-student copy (new IDs, private files, one copy, isolated)."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    Chunk,
    Document,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    Topic,
    TopicChunkLink,
)
from app.services import demo
from tests.factories import make_document, make_topic, make_workspace
from tests.helpers import FakeStorage, auth_headers, make_student

pytestmark = pytest.mark.integration


@pytest.fixture()
def snapshot(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    owner = make_student(db)
    ws = make_workspace(db, owner, "seed")
    notes = make_document(
        db, ws, "notes", chunks=["Ohm's law: V = I R.", "Resistors in series add up."], seed=90
    )
    paper = make_document(db, ws, "past_paper", chunks=["Q1. State Ohm's law. (2 marks)"], seed=95)
    unit = make_topic(db, ws, "Electricity", status="approved")
    child = make_topic(db, ws, "Ohm's law", status="approved", parent=unit)
    chunk = db.scalar(select(Chunk).where(Chunk.document_id == notes.id, Chunk.chunk_index == 0))
    paper_chunk = db.scalar(select(Chunk).where(Chunk.document_id == paper.id))
    assert chunk is not None and paper_chunk is not None
    db.add(TopicChunkLink(topic_id=child.id, chunk_id=chunk.id, quote="Ohm's law"))
    question = PastPaperQuestion(
        workspace_id=ws.id,
        document_id=paper.id,
        document_version=1,
        chunk_id=paper_chunk.id,
        position=0,
        question_label="Q1",
        question_text="State Ohm's law.",
        marks=2,
        year=2025,
    )
    db.add(question)
    db.flush()
    db.add(PastPaperQuestionTopic(question_id=question.id, topic_id=child.id))
    db.commit()
    data = demo.export_snapshot(db, ws.id)
    for doc in data["documents"]:  # the files the copy uploads
        raw = f"demo file {doc['filename']}".encode()
        (tmp_path / doc["filename"]).write_bytes(raw)
        doc["checksum_sha256"] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path)
    monkeypatch.setattr(demo, "load_snapshot", lambda: data)
    return {"data": data, "source_ws": ws.id}


def test_export_keeps_structure(snapshot: dict[str, Any]) -> None:
    data = snapshot["data"]
    assert data["version"] == demo.DEMO_VERSION and len(data["documents"]) == 2
    assert [t["parent"] is None for t in data["topics"]] == [True, False]  # parents first
    assert all(c["embedding"] for d in data["documents"] for c in d["chunks"])
    assert data["past_paper_questions"][0]["topics"] and data["links"][0]["quote"] == "Ohm's law"


def test_try_demo_copies_into_the_students_own_account(
    client: Any, db: Session, snapshot: dict[str, Any], storage: FakeStorage
) -> None:
    student = make_student(db)
    headers = auth_headers(student)
    created = client.post("/workspaces/demo", headers=headers)
    assert created.status_code == 201, created.text
    ws = created.json()
    assert ws["demo_source"] == demo.DEMO_VERSION and ws["title"] == demo.DEMO_TITLE
    assert (
        client.post("/workspaces/demo", headers=headers).json()["id"] == ws["id"]
    )  # one copy per student
    docs = list(db.scalars(select(Document).where(Document.workspace_id == ws["id"])))
    assert {d.state for d in docs} == {"ready"} and all(d.student_id == student for d in docs)
    assert all(
        d.storage_key.startswith(f"workspaces/{ws['id']}/documents/")
        and d.storage_key in storage.objects
        for d in docs
    )
    topics = list(db.scalars(select(Topic).where(Topic.workspace_id == ws["id"])))
    assert len(topics) == 2 and {t.status for t in topics} == {"approved"}
    child = next(t for t in topics if t.parent_id)
    assert child.parent_id in {t.id for t in topics}  # parent remapped to the new IDs
    assert (
        db.scalar(
            select(func.count())
            .select_from(TopicChunkLink)
            .where(TopicChunkLink.topic_id == child.id)
        )
        == 1
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(PastPaperQuestion)
            .where(PastPaperQuestion.workspace_id == ws["id"])
        )
        == 1
    )
    vectors = db.execute(
        text("SELECT count(*) FROM chunks WHERE workspace_id = :w AND embedding IS NOT NULL"),
        {"w": ws["id"]},
    ).scalar()
    assert vectors == 3
    source_ids = set(
        db.scalars(select(Topic.id).where(Topic.workspace_id == snapshot["source_ws"]))
    )
    assert not source_ids & {t.id for t in topics}  # fresh IDs, nothing shared with the seed
    # Isolation and the normal contracts work on the copy.
    listed = client.get("/workspaces", headers=headers).json()
    assert [w["demo_source"] for w in listed] == [demo.DEMO_VERSION]
    stranger = auth_headers(make_student(db))
    assert client.get(f"/topics/workspace/{ws['id']}", headers=stranger).status_code == 404
    assert len(client.get(f"/topics/workspace/{ws['id']}", headers=headers).json()) == 2
    assert client.delete(f"/workspaces/{ws['id']}", headers=headers).status_code == 204
    assert (
        client.post("/workspaces/demo", headers=headers).status_code == 201
    )  # can start over after deleting


def test_demo_built_with_another_embedding_model_is_refused(
    client: Any, db: Session, snapshot: dict[str, Any], storage: FakeStorage
) -> None:
    snapshot["data"]["documents"][0]["chunks"][0]["embedding_model"] = (
        "sentence-transformers/old-model"
    )
    response = client.post("/workspaces/demo", headers=auth_headers(make_student(db)))
    assert response.status_code == 503
    assert all("/documents/" not in k for k in storage.objects)


def test_changed_demo_files_are_refused(
    client: Any, db: Session, snapshot: dict[str, Any], storage: FakeStorage
) -> None:
    snapshot["data"]["documents"][0]["checksum_sha256"] = "0" * 64
    response = client.post("/workspaces/demo", headers=auth_headers(make_student(db)))
    assert response.status_code == 503
    assert storage.objects == {} or all(
        "/documents/" not in k for k in storage.objects
    )  # nothing orphaned
