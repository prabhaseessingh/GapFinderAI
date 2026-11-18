"""process_document: scanning → extracting → chunking → embedding → (mapping →) ready | failed."""

import asyncio
import hashlib
import logging
from typing import Any
from uuid import UUID

import httpx
from app.core.config import get_settings
from app.db.models import Chunk, Document
from app.db.session import SessionLocal
from app.providers.embeddings import EMBEDDING_LABEL, EmbeddingClient, EmbeddingError
from app.services.jobs import (
    PROCESS_DOCUMENT,
    PROPOSE_TOPIC_MAP,
    SEGMENT_PAST_PAPER,
    QueueUnavailable,
    send_task,
    upsert_job,
)
from app.services.states import PROCESSING_STATES
from app.services.storage import SupabaseStorage
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from tasks.common import advisory_lock, bind_correlation, job_done, job_running
from tasks.extraction import (
    ChunkDraft,
    ExtractionError,
    chunk_pages,
    detect_source_language,
    extract,
    verify_signature,
)

from worker.app import celery_app

logger = logging.getLogger("gapfinder.ingest")
MAX_TRANSIENT_RETRIES = 3


class TransientError(Exception):
    pass


def embedding_label() -> str:
    """Stored in chunks.embedding_model so a future model change is detectable."""
    return EMBEDDING_LABEL


def embed_texts(texts: list[str], kind: str = "document") -> list[list[float]]:
    """Open-source Qwen3-Embedding-0.6B via the signed Cloudflare Worker (same model locally and on Render)."""
    try:
        return EmbeddingClient(get_settings()).embed(texts, kind)
    except EmbeddingError as error:
        raise ExtractionError(error.code) from error


def embed_query(text: str) -> list[float]:
    return embed_texts([text], "query")[0]


def _set_state(session: Session, document: Document, state: str) -> None:
    document.state = state
    document.updated_at = func.now()
    session.commit()


def _download(storage_key: str) -> bytes:
    try:
        return asyncio.run(SupabaseStorage(get_settings()).download(storage_key))
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (400, 404):
            raise ExtractionError("SOURCE_FILE_MISSING") from error
        raise TransientError("STORAGE_UNAVAILABLE") from error
    except httpx.HTTPError as error:
        raise TransientError("STORAGE_UNAVAILABLE") from error


def store_chunks(
    session: Session,
    document: Document,
    drafts: list[ChunkDraft],
    vectors: list[list[float]],
    model: str,
) -> None:
    """Replace this document version's chunks and vectors in one transaction (idempotent)."""
    session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    session.execute(
        insert(Chunk),
        [
            {
                "document_id": document.id,
                "workspace_id": document.workspace_id,
                "chunk_index": draft.chunk_index,
                "text_content": draft.text,
                "source_language": detect_source_language(draft.text),
                "heading_path": list(draft.heading_path),
                "page_start": draft.page,
                "page_end": draft.page,
                "char_start": draft.char_start,
                "char_end": draft.char_end,
                "content_hash": draft.content_hash,
                "embedding": "[" + ",".join(map(str, vector)) + "]",
                "embedding_model": model,
            }
            for draft, vector in zip(drafts, vectors, strict=True)
        ],
    )


def _trigger_mapping(session: Session, document: Document) -> bool:
    """Syllabus → topic proposal; past paper → segmentation. Returns False if nothing queued."""
    settings = get_settings()
    if (
        document.material_role not in ("syllabus", "past_paper")
        or not settings.groq_configured
    ):
        return False
    if document.material_role == "syllabus":
        task, key = (
            PROPOSE_TOPIC_MAP,
            f"{document.workspace_id}:auto:{document.id}:v{document.version}",
        )
        args = [str(document.workspace_id), str(document.id)]
    else:
        task, key, args = (
            SEGMENT_PAST_PAPER,
            f"{document.id}:v{document.version}",
            [str(document.id)],
        )
    job = upsert_job(
        session,
        task_name=task,
        idempotency_key=key,
        student_id=document.student_id,
        workspace_id=document.workspace_id,
        correlation_id=None,
    )
    session.commit()
    try:
        send_task(settings.redis_url, task, args, job.correlation_id, key)
    except QueueUnavailable:
        job_done(session, task, key, "failed", "QUEUE_UNAVAILABLE")
        return False
    return True


def run_pipeline(session: Session, document: Document) -> str:
    settings = get_settings()
    document.processing_attempts += 1
    document.failure_code = None
    _set_state(session, document, "scanning")
    raw = _download(document.storage_key)
    if hashlib.sha256(raw).hexdigest() != document.checksum_sha256:
        raise ExtractionError("CHECKSUM_MISMATCH")
    verify_signature(document.mime_type, raw)

    _set_state(session, document, "extracting")
    pages = extract(document.mime_type, raw, settings.ocr_languages)
    document.page_count = sum(1 for page in pages if page.page is not None) or None

    _set_state(session, document, "chunking")
    drafts = chunk_pages(pages)
    if not drafts:
        raise ExtractionError("EMPTY_DOCUMENT")

    _set_state(session, document, "embedding")
    try:
        vectors = embed_texts([draft.text for draft in drafts])
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError("EMBEDDING_FAILED") from error
    store_chunks(session, document, drafts, vectors, embedding_label())
    document.state = (
        "mapping" if document.material_role in ("syllabus", "past_paper") else "ready"
    )
    document.updated_at = func.now()
    session.commit()
    if document.state == "mapping" and not _trigger_mapping(session, document):
        _set_state(session, document, "ready")
    return document.state


@celery_app.task(
    name=PROCESS_DOCUMENT, bind=True, max_retries=MAX_TRANSIENT_RETRIES, acks_late=True
)
def process_document(self: Any, document_id: str, job_key: str | None = None) -> str:
    bind_correlation(self)
    with SessionLocal() as session:
        document = session.scalar(
            select(Document).where(Document.id == UUID(document_id))
        )
        if not document:
            return "missing"  # deleted while queued
        if document.state not in PROCESSING_STATES:
            return document.state  # duplicate delivery after a terminal state
        key = f"{document.id}:v{document.version}"
        with advisory_lock(session, f"document:{document.id}") as acquired:
            if not acquired:
                return "busy"
            upsert_job(
                session,
                task_name=PROCESS_DOCUMENT,
                idempotency_key=key,
                student_id=document.student_id,
                workspace_id=document.workspace_id,
                state="running",
            )
            job_running(session, PROCESS_DOCUMENT, key)
            try:
                state = run_pipeline(session, document)
                job_done(
                    session, PROCESS_DOCUMENT, key, "succeeded", result={"state": state}
                )
                return state
            except (TransientError, OperationalError) as error:
                session.rollback()
                code = (
                    str(error)
                    if isinstance(error, TransientError)
                    else "DATABASE_UNAVAILABLE"
                )
                if self.request.retries < MAX_TRANSIENT_RETRIES:
                    job_done(session, PROCESS_DOCUMENT, key, "queued", code)
                    raise self.retry(countdown=10 * 2**self.request.retries) from error
                return _fail(session, document_id, key, code)
            except ExtractionError as error:
                session.rollback()
                return _fail(session, document_id, key, error.code)
            except Exception:
                session.rollback()
                logger.exception("Unexpected processing failure for %s", document_id)
                return _fail(session, document_id, key, "PROCESSING_ERROR")


def _fail(session: Session, document_id: str, key: str, code: str) -> str:
    document = session.scalar(select(Document).where(Document.id == UUID(document_id)))
    if document:
        document.state = "failed"
        document.failure_code = code
        document.updated_at = func.now()
        session.commit()
    job_done(session, PROCESS_DOCUMENT, key, "failed", code)
    return "failed"
