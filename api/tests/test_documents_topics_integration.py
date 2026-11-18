"""Documents, topics and retrieval behaviour against a real (local) Postgres."""

import hashlib
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Document, JobRun, PastPaperQuestion, PastPaperQuestionTopic, Topic
from app.schemas.topics import CitationReference, ProposedTopic, TopicProposal
from app.services.retrieval import retrieve_evidence, retrieve_syllabus_evidence
from app.services.topics import recompute_importance, replace_draft_proposal
from tests.factories import make_document, make_topic, make_workspace, unit_vector
from tests.helpers import FakeStorage, auth_headers, make_student

pytestmark = pytest.mark.integration


def _proposal(chunk_id: Any, *titles: tuple[str, str | None]) -> TopicProposal:
    return TopicProposal(
        topics=[
            ProposedTopic(
                title=t, parent_title=p, citations=[CitationReference(chunk_id=chunk_id, quote=t)]
            )
            for t, p in titles
        ]
    )


def test_upload_confirm_queues_processing_and_tracks_job(
    client: Any, db: Session, storage: FakeStorage, queue: list[Any]
) -> None:
    student = make_student(db)
    headers = auth_headers(student)
    ws = client.post(
        "/workspaces", json={"title": "Chem", "selected_locale": "hi-IN"}, headers=headers
    ).json()
    checksum = hashlib.sha256(b"hello").hexdigest()
    intent = client.post(
        "/documents/upload-intent",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "material_role": "notes",
            "filename": "n.txt",
            "mime_type": "text/plain",
            "byte_size": 5,
            "checksum_sha256": checksum,
        },
    ).json()
    assert intent["storage_path"].startswith(
        f"workspaces/{ws['id']}/documents/{intent['document_id']}/v1/"
    )
    # Confirm before the object exists → clear INVALID_STATE, nothing queued.
    missing = client.post(
        f"/documents/{intent['document_id']}/confirm",
        json={"checksum_sha256": checksum},
        headers=headers,
    )
    assert missing.status_code == 409 and missing.json()["error"]["code"] == "INVALID_STATE"
    storage.objects[intent["storage_path"]] = 5
    confirmed = client.post(
        f"/documents/{intent['document_id']}/confirm",
        json={"checksum_sha256": checksum},
        headers=headers,
    )
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "scanning"
    assert queue == [
        ("gapfinder.process_document", [intent["document_id"]], f"{intent['document_id']}:v1")
    ]
    job = db.scalar(select(JobRun).where(JobRun.task_name == "gapfinder.process_document"))
    assert job is not None and job.state == "queued"
    # Same bytes again → refused, not duplicated.
    again = client.post(
        "/documents/upload-intent",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "material_role": "notes",
            "filename": "copy.txt",
            "mime_type": "text/plain",
            "byte_size": 5,
            "checksum_sha256": checksum,
        },
    )
    assert again.status_code == 409


def test_supabase_limit_is_explained_without_lower_app_limit(client: Any, db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    body = {
        "workspace_id": str(ws.id),
        "material_role": "textbook",
        "filename": "big.pdf",
        "mime_type": "application/pdf",
        "checksum_sha256": "b" * 64,
    }
    ok = client.post(
        "/documents/upload-intent",
        json=body | {"byte_size": 50 * 1024 * 1024},
        headers=auth_headers(student),
    )
    assert ok.status_code == 201
    too_big = client.post(
        "/documents/upload-intent",
        json=body | {"byte_size": 50 * 1024 * 1024 + 1, "checksum_sha256": "c" * 64},
        headers=auth_headers(student),
    )
    assert too_big.status_code == 413
    assert "Supabase" in too_big.json()["error"]["message"]


def test_workspace_delete_removes_files_then_rows(
    client: Any, db: Session, storage: FakeStorage
) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    document = make_document(db, ws, chunks=["text"])
    document_id, storage_key = document.id, document.storage_key
    response = client.delete(f"/workspaces/{ws.id}", headers=auth_headers(student))
    assert response.status_code == 204
    assert storage.deleted == [storage_key]
    db.expunge_all()
    assert db.get(Document, document_id) is None
    assert (
        db.execute(
            text("SELECT count(*) FROM chunks WHERE workspace_id = :w"), {"w": ws.id}
        ).scalar()
        == 0
    )


def test_reproposal_keeps_approved_and_manual_children(db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    doc = make_document(db, ws, "syllabus", chunks=["Cells Genetics Ecology Evolution"])
    evidence = retrieve_syllabus_evidence(db, student, ws.id)
    chunk_id = evidence[0].chunk_id
    replace_draft_proposal(
        db, ws.id, _proposal(chunk_id, ("Cells", None), ("Genetics", None)), evidence
    )
    cells = db.scalar(select(Topic).where(Topic.title == "Cells", Topic.workspace_id == ws.id))
    genetics = db.scalar(
        select(Topic).where(Topic.title == "Genetics", Topic.workspace_id == ws.id)
    )
    assert cells and genetics
    cells.status = "approved"
    manual_child = make_topic(db, ws, "My genetics notes", origin="manual", parent=genetics)
    db.commit()

    replace_draft_proposal(
        db,
        ws.id,
        _proposal(chunk_id, ("Cells", None), ("Genetics", None), ("Ecology", None)),
        evidence,
    )
    titles = sorted(db.scalars(select(Topic.title).where(Topic.workspace_id == ws.id)))
    assert titles == ["Cells", "Ecology", "Genetics", "My genetics notes"]  # no duplicate "Cells"
    db.refresh(manual_child)
    new_genetics = db.scalar(
        select(Topic).where(Topic.title == "Genetics", Topic.workspace_id == ws.id)
    )
    assert manual_child.parent_id == new_genetics.id  # survived and re-attached
    assert doc.id


def test_proposal_rejects_uncited_or_foreign_quotes(db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    make_document(db, ws, "syllabus", chunks=["Cells and tissues"])
    evidence = retrieve_syllabus_evidence(db, student, ws.id)
    with pytest.raises(ValueError, match="INVALID_TOPIC_CITATION"):
        replace_draft_proposal(
            db, ws.id, _proposal(evidence[0].chunk_id, ("Quantum gravity", None)), evidence
        )


def test_topic_tree_stays_two_levels_and_acyclic(client: Any, db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    headers = auth_headers(student)
    a = client.post(
        "/topics", json={"workspace_id": str(ws.id), "title": "A"}, headers=headers
    ).json()
    b = client.post(
        "/topics",
        json={"workspace_id": str(ws.id), "title": "B", "parent_id": a["id"]},
        headers=headers,
    ).json()
    c = client.post(
        "/topics", json={"workspace_id": str(ws.id), "title": "C"}, headers=headers
    ).json()
    assert (
        client.post(
            "/topics",
            json={"workspace_id": str(ws.id), "title": "D", "parent_id": b["id"]},
            headers=headers,
        ).status_code
        == 409
    )  # third level
    assert (
        client.patch(f"/topics/{a['id']}", json={"parent_id": c["id"]}, headers=headers).status_code
        == 409
    )
    assert (
        client.patch(f"/topics/{a['id']}", json={"parent_id": a["id"]}, headers=headers).status_code
        == 409
    )
    assert (
        client.patch(f"/topics/{c['id']}", json={"parent_id": a["id"]}, headers=headers).status_code
        == 200
    )


def test_importance_is_deterministic_and_student_override_wins(client: Any, db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    paper = make_document(
        db, ws, "past_paper", chunks=["Q1 Explain osmosis (6 marks)", "Q2 Define a cell"]
    )
    chunks = list(
        db.scalars(
            text("SELECT id FROM chunks WHERE document_id = :d ORDER BY chunk_index").bindparams(
                d=paper.id
            )
        )
    )
    osmosis = make_topic(db, ws, "Osmosis", status="approved")
    cells = make_topic(db, ws, "Cells", status="approved")
    unseen = make_topic(db, ws, "Ecology", status="approved")
    recompute_importance(db, ws.id)
    db.commit()
    assert {t.importance for t in (osmosis, cells, unseen)} == {3}  # no past-paper questions yet
    q1 = PastPaperQuestion(
        workspace_id=ws.id,
        document_id=paper.id,
        document_version=1,
        chunk_id=chunks[0],
        position=0,
        question_text="Explain osmosis",
        marks=6,
        year=2023,
    )
    q2 = PastPaperQuestion(
        workspace_id=ws.id,
        document_id=paper.id,
        document_version=1,
        chunk_id=chunks[1],
        position=1,
        question_text="Define a cell",
        marks=None,
        year=2023,
    )
    db.add_all([q1, q2])
    db.flush()
    db.add_all(
        [
            PastPaperQuestionTopic(question_id=q1.id, topic_id=osmosis.id),
            PastPaperQuestionTopic(question_id=q2.id, topic_id=cells.id),
        ]
    )
    recompute_importance(db, ws.id)
    db.commit()
    for topic in (osmosis, cells, unseen):
        db.refresh(topic)
    assert (osmosis.importance, cells.importance, unseen.importance) == (5, 2, 1)
    assert osmosis.importance_source == "past_papers"
    assert osmosis.importance_basis["weighted_marks"] == 6
    updated = client.patch(
        f"/topics/{unseen.id}", json={"importance": 4}, headers=auth_headers(student)
    ).json()
    assert (updated["importance"], updated["importance_source"]) == (4, "student")
    reset = client.patch(
        f"/topics/{unseen.id}", json={"reset_importance": True}, headers=auth_headers(student)
    ).json()
    assert (reset["importance"], reset["importance_source"]) == (1, "past_papers")


def test_citations_show_exact_quote_and_location(client: Any, db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    doc = make_document(db, ws, "syllabus", chunks=["Unit 2: Cell division, mitosis and meiosis."])
    chunk_id = db.execute(
        text("SELECT id FROM chunks WHERE document_id = :d"), {"d": doc.id}
    ).scalar()
    topic = make_topic(db, ws, "mitosis", chunk_id=chunk_id)
    citations = client.get(
        f"/topics/{topic.id}/citations?locale=en", headers=auth_headers(student)
    ).json()
    assert citations[0]["original_quote"] == "mitosis"
    assert citations[0]["page_start"] == 1 and citations[0]["heading_path"] == ["Unit 1"]
    assert citations[0]["translated_quote"] is None


def test_retrieval_threshold_refuses_unrelated_vectors_and_diversifies(db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    make_document(db, ws, "notes", chunks=[f"alpha note {i}" for i in range(8)], seed=10)
    make_document(db, ws, "textbook", chunks=[f"alpha book {i}" for i in range(8)], seed=40)
    unrelated = [float(x) for x in unit_vector(300)[1:-1].split(",")]
    assert retrieve_evidence(db, student, ws.id, "zzzz", query_embedding=unrelated).insufficient
    bundle = retrieve_evidence(db, student, ws.id, "alpha", limit=6)
    by_doc: dict[str, int] = {}
    for item in bundle.items:
        by_doc[item.document_name] = by_doc.get(item.document_name, 0) + 1
    assert len(bundle.items) == 6 and max(by_doc.values()) <= 3


def test_parent_unit_inherits_subtopic_past_paper_evidence(db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    paper = make_document(db, ws, "past_paper", chunks=["Q1 Snell's law (3 marks)"])
    chunk = db.execute(
        text("SELECT id FROM chunks WHERE document_id = :d"), {"d": paper.id}
    ).scalar()
    unit = make_topic(db, ws, "Unit 1: Light", status="approved")
    sub = make_topic(db, ws, "Snell's law", status="approved", parent=unit)
    other = make_topic(db, ws, "Unit 2: Electricity", status="approved")
    question = PastPaperQuestion(
        workspace_id=ws.id,
        document_id=paper.id,
        document_version=1,
        chunk_id=chunk,
        position=0,
        question_text="Snell's law",
        marks=3,
        year=2024,
    )
    db.add(question)
    db.flush()
    db.add_all(
        [
            PastPaperQuestionTopic(question_id=question.id, topic_id=sub.id),
            PastPaperQuestionTopic(question_id=question.id, topic_id=unit.id),
        ]
    )  # mapped to both
    recompute_importance(db, ws.id)
    db.commit()
    for topic in (unit, sub, other):
        db.refresh(topic)
    assert unit.importance_basis["past_paper_questions"] == 1  # counted once, not twice
    assert (unit.importance, sub.importance, other.importance) == (5, 5, 1)
