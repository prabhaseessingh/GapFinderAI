"""Demo workspace.

The demo material in `api/demo/*.txt` is original and written for GapFinder. A snapshot of a
workspace built from it by the real pipeline (upload -> extract -> chunk -> embed -> topic proposal
-> approval -> past-paper segmentation/mapping) is stored in `api/demo/snapshot.json` by
`scripts/seed_demo.py`. "Try the demo" copies that snapshot into a fresh, clearly marked workspace
in the signed-in student's own account: their files, rows and IDs are new, so isolation, quizzes,
reports and Explain work exactly as for their own uploads — without any AI call at copy time.
"""

import asyncio
import contextlib
import hashlib
import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    Chunk,
    Document,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    Topic,
    TopicChunkLink,
    Workspace,
)
from app.providers.embeddings import EMBEDDING_LABEL
from app.services.storage import BUCKET, SupabaseStorage
from app.services.workspaces import ensure_profile

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo"
SNAPSHOT_PATH = DEMO_DIR / "snapshot.json"
DEMO_VERSION = "gapfinder-demo-v1"
DEMO_TITLE = "Demo: Class 10 Science"


def read_demo_file(filename: str) -> bytes:
    """Demo material bytes with LF line endings, so a Windows checkout (CRLF) hashes the same."""
    return (DEMO_DIR / filename).read_bytes().replace(b"\r\n", b"\n")


# ---- export (used by scripts/seed_demo.py) -------------------------------------------------------


def export_snapshot(session: Session, workspace_id: UUID) -> dict[str, Any]:
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.filename)
        )
    )
    out_docs = []
    chunk_ref: dict[UUID, tuple[str, int]] = {}
    for document in documents:
        if document.state != "ready":
            raise RuntimeError(f"{document.filename} is {document.state}, not ready")
        rows = (
            session.execute(
                text(
                    "SELECT id, chunk_index, text_content, source_language, heading_path, page_start, page_end, "
                    "char_start, char_end, content_hash, embedding::text AS embedding, embedding_model "
                    "FROM chunks WHERE document_id = :d ORDER BY chunk_index"
                ),
                {"d": document.id},
            )
            .mappings()
            .all()
        )
        for row in rows:
            chunk_ref[row["id"]] = (document.filename, row["chunk_index"])
        out_docs.append(
            {
                "filename": document.filename,
                "material_role": document.material_role,
                "mime_type": document.mime_type,
                "checksum_sha256": document.checksum_sha256,
                "byte_size": document.byte_size,
                "page_count": document.page_count,
                "chunks": [
                    {
                        k: (list(v) if k == "heading_path" else v)
                        for k, v in row.items()
                        if k != "id"
                    }
                    for row in rows
                ],
            }
        )
    topics = list(
        session.scalars(
            select(Topic)
            .where(Topic.workspace_id == workspace_id)
            .order_by(Topic.parent_id.is_not(None), Topic.position)
        )
    )
    topic_ids = {t.id for t in topics}
    links = session.scalars(select(TopicChunkLink).where(TopicChunkLink.topic_id.in_(topic_ids)))
    questions = list(
        session.scalars(
            select(PastPaperQuestion)
            .where(PastPaperQuestion.workspace_id == workspace_id)
            .order_by(PastPaperQuestion.position)
        )
    )
    question_topics = session.scalars(
        select(PastPaperQuestionTopic).where(
            PastPaperQuestionTopic.question_id.in_([q.id for q in questions])
        )
    )
    by_question: dict[UUID, list[dict[str, str]]] = {}
    for qt in question_topics:
        by_question.setdefault(qt.question_id, []).append(
            {"topic": str(qt.topic_id), "method": qt.method}
        )
    return {
        "version": DEMO_VERSION,
        "documents": out_docs,
        "topics": [
            {
                "id": str(t.id),
                "parent": str(t.parent_id) if t.parent_id else None,
                "title": t.title,
                "status": t.status,
                "importance": t.importance,
                "importance_source": t.importance_source,
                "importance_basis": t.importance_basis,
                "position": t.position,
                "origin": t.origin,
            }
            for t in topics
        ],
        "links": [
            {
                "topic": str(link.topic_id),
                "chunk": list(chunk_ref[link.chunk_id]),
                "confidence": link.confidence,
                "method": link.method,
                "manual_override": link.manual_override,
                "quote": link.quote,
            }
            for link in links
            if link.chunk_id in chunk_ref
        ],
        "past_paper_questions": [
            {
                "chunk": list(chunk_ref[q.chunk_id]),
                "position": q.position,
                "question_label": q.question_label,
                "question_text": q.question_text,
                "page": q.page,
                "marks": q.marks,
                "year": q.year,
                "topics": by_question.get(q.id, []),
            }
            for q in questions
        ],
    }


# ---- copy into a student's account ---------------------------------------------------------------


@lru_cache
def load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise AppError(
            503, "PROVIDER_UNAVAILABLE", "The demo workspace is not available on this server yet."
        )
    data: dict[str, Any] = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return data


def existing_demo(session: Session, student_id: UUID) -> Workspace | None:
    return session.scalar(
        select(Workspace).where(
            Workspace.student_id == student_id, Workspace.demo_source.is_not(None)
        )
    )


def create_demo_workspace(
    session: Session, student_id: UUID, storage: SupabaseStorage, locale: str
) -> Workspace:
    """One demo per student: a second request returns the existing copy."""
    ensure_profile(session, student_id)
    found = existing_demo(session, student_id)
    if found is not None:
        return found
    snapshot = load_snapshot()
    if any(
        c.get("embedding_model") != EMBEDDING_LABEL
        for d in snapshot["documents"]
        for c in d["chunks"]
    ):
        # Vectors from another model would silently break retrieval for this student's demo.
        raise AppError(
            503,
            "PROVIDER_UNAVAILABLE",
            "The demo was built with another embedding model; re-embed it.",
        )
    workspace = Workspace(
        student_id=student_id, title=DEMO_TITLE, selected_locale=locale, demo_source=DEMO_VERSION
    )
    session.add(workspace)
    session.flush()
    chunk_ids: dict[tuple[str, int], UUID] = {}
    uploaded: list[str] = []
    try:
        for doc in snapshot["documents"]:
            raw = read_demo_file(doc["filename"])
            if hashlib.sha256(raw).hexdigest() != doc["checksum_sha256"]:
                raise AppError(
                    503,
                    "PROVIDER_UNAVAILABLE",
                    "The demo material changed; reseed the demo snapshot.",
                )
            document_id = uuid.uuid4()
            key = f"workspaces/{workspace.id}/documents/{document_id}/v1/{doc['filename']}"
            storage.upload_sync(key, raw, doc["mime_type"], bucket=BUCKET)
            uploaded.append(key)
            session.add(
                Document(
                    id=document_id,
                    workspace_id=workspace.id,
                    student_id=student_id,
                    material_role=doc["material_role"],
                    filename=doc["filename"],
                    storage_key=key,
                    mime_type=doc["mime_type"],
                    byte_size=len(raw),
                    checksum_sha256=doc["checksum_sha256"],
                    state="ready",
                    page_count=doc["page_count"],
                )
            )
            session.flush()
            for chunk in doc["chunks"]:
                chunk_id = uuid.uuid4()
                chunk_ids[(doc["filename"], chunk["chunk_index"])] = chunk_id
                session.add(
                    Chunk(
                        id=chunk_id,
                        document_id=document_id,
                        workspace_id=workspace.id,
                        chunk_index=chunk["chunk_index"],
                        text_content=chunk["text_content"],
                        source_language=chunk["source_language"],
                        heading_path=chunk["heading_path"],
                        page_start=chunk["page_start"],
                        page_end=chunk["page_end"],
                        char_start=chunk["char_start"],
                        char_end=chunk["char_end"],
                        content_hash=chunk["content_hash"],
                        embedding_model=chunk["embedding_model"],
                    )
                )
                session.flush()
                if chunk["embedding"]:
                    session.execute(
                        text("UPDATE chunks SET embedding = CAST(:v AS vector) WHERE id = :id"),
                        {"v": chunk["embedding"], "id": chunk_id},
                    )
        topic_ids: dict[str, UUID] = {}
        for topic in snapshot["topics"]:  # parents are exported before children
            new_id = uuid.uuid4()
            topic_ids[topic["id"]] = new_id
            session.add(
                Topic(
                    id=new_id,
                    workspace_id=workspace.id,
                    parent_id=topic_ids[topic["parent"]] if topic["parent"] else None,
                    title=topic["title"],
                    status=topic["status"],
                    importance=topic["importance"],
                    importance_source=topic["importance_source"],
                    importance_basis=topic["importance_basis"],
                    position=topic["position"],
                    origin=topic["origin"],
                )
            )
            session.flush()
        for link in snapshot["links"]:
            session.add(
                TopicChunkLink(
                    topic_id=topic_ids[link["topic"]],
                    chunk_id=chunk_ids[(link["chunk"][0], link["chunk"][1])],
                    confidence=link["confidence"],
                    method=link["method"],
                    manual_override=link["manual_override"],
                    quote=link["quote"],
                )
            )
        documents = {
            d.filename: d
            for d in session.scalars(select(Document).where(Document.workspace_id == workspace.id))
        }
        for question in snapshot["past_paper_questions"]:
            filename, index = question["chunk"]
            row = PastPaperQuestion(
                workspace_id=workspace.id,
                document_id=documents[filename].id,
                document_version=1,
                chunk_id=chunk_ids[(filename, index)],
                position=question["position"],
                question_label=question["question_label"],
                question_text=question["question_text"],
                page=question["page"],
                marks=question["marks"],
                year=question["year"],
            )
            session.add(row)
            session.flush()
            for qt in question["topics"]:
                session.add(
                    PastPaperQuestionTopic(
                        question_id=row.id, topic_id=topic_ids[qt["topic"]], method=qt["method"]
                    )
                )
        session.commit()
    except Exception:
        session.rollback()
        if uploaded:  # no orphaned files if the copy fails half-way (route runs in a worker thread)
            with contextlib.suppress(Exception):
                asyncio.run(storage.delete_many(uploaded))
        raise
    session.refresh(workspace)
    return workspace
