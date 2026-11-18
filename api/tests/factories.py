"""Direct-to-DB fixtures for integration tests (bypass upload/worker)."""

import hashlib
import uuid
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Topic, TopicChunkLink, Workspace
from app.providers.embeddings import EMBEDDING_LABEL


def unit_vector(seed: int, dims: int = 384) -> str:
    values = [0.0] * dims
    values[seed % dims] = 1.0
    return "[" + ",".join(map(str, values)) + "]"


def make_workspace(session: Session, student_id: UUID, title: str = "Biology") -> Workspace:
    workspace = Workspace(student_id=student_id, title=title, selected_locale="en")
    session.add(workspace)
    session.commit()
    return workspace


def make_document(
    session: Session,
    workspace: Workspace,
    role: str = "notes",
    state: str = "ready",
    chunks: list[str] | None = None,
    seed: int = 0,
    language: str = "en",
) -> Document:
    document_id = uuid.uuid4()
    document = Document(
        id=document_id,
        workspace_id=workspace.id,
        student_id=workspace.student_id,
        material_role=role,
        filename=f"{role}-{seed}.txt",
        storage_key=f"workspaces/{workspace.id}/documents/{document_id}/v1/f.txt",
        mime_type="text/plain",
        byte_size=10,
        checksum_sha256=hashlib.sha256(document_id.bytes).hexdigest(),
        state=state,
    )
    session.add(document)
    session.flush()
    for index, body in enumerate(chunks or []):
        chunk_id = uuid.uuid4()
        session.add(
            Chunk(
                id=chunk_id,
                document_id=document.id,
                workspace_id=workspace.id,
                chunk_index=index,
                text_content=body,
                source_language=language,
                heading_path=["Unit 1"],
                page_start=1,
                page_end=1,
                char_start=0,
                char_end=len(body),
                content_hash=hashlib.sha256(body.encode()).hexdigest(),
                embedding_model=EMBEDDING_LABEL,
            )
        )
        session.flush()
        session.execute(
            text("UPDATE chunks SET embedding = CAST(:v AS vector) WHERE id = :id"),
            {"v": unit_vector(seed + index), "id": chunk_id},
        )
    session.commit()
    return document


def make_topic(
    session: Session,
    workspace: Workspace,
    title: str,
    *,
    status: str = "draft",
    origin: str = "proposal",
    parent: Topic | None = None,
    chunk_id: UUID | None = None,
) -> Topic:
    topic = Topic(
        workspace_id=workspace.id,
        title=title,
        status=status,
        origin=origin,
        parent_id=parent.id if parent else None,
    )
    session.add(topic)
    session.flush()
    if chunk_id:
        session.add(TopicChunkLink(topic_id=topic.id, chunk_id=chunk_id, quote=title))
    session.commit()
    return topic
