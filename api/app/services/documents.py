import re
import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, invalid_state, not_found
from app.db.models import Chunk, Document
from app.schemas.documents import (
    SUPABASE_FILE_LIMIT_BYTES,
    ChunkOut,
    ConfirmUploadRequest,
    DocumentOut,
    DocumentSourceOut,
    UploadIntentOut,
    UploadIntentRequest,
)
from app.services.states import require_document_transition
from app.services.storage import BUCKET, SupabaseStorage
from app.services.workspaces import require_workspace_owner

SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]")


def _storage_key(workspace_id: UUID, document_id: UUID, filename: str, version: int = 1) -> str:
    safe_name = SAFE_FILENAME.sub("_", filename).strip(". ") or "material"
    return f"workspaces/{workspace_id}/documents/{document_id}/v{version}/{safe_name}"


def _owned_workspace(session: Session, student_id: UUID, workspace_id: UUID) -> None:
    try:
        require_workspace_owner(session, student_id, workspace_id)
    except LookupError as error:
        raise not_found("Workspace") from error


async def create_upload_intent(
    session: Session, student_id: UUID, request: UploadIntentRequest, storage: SupabaseStorage
) -> UploadIntentOut:
    if request.byte_size > SUPABASE_FILE_LIMIT_BYTES:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "The free storage provider (Supabase) accepts files up to 50 MB each. "
            "GapFinder adds no lower limit; please split or compress this file.",
        )
    _owned_workspace(session, student_id, request.workspace_id)
    existing = session.scalar(
        select(Document).where(
            Document.workspace_id == request.workspace_id,
            Document.student_id == student_id,
            Document.checksum_sha256 == request.checksum_sha256,
            Document.version == 1,
        )
    )
    if existing:
        if existing.state != "uploaded":
            raise invalid_state(
                f"This exact file is already in this workspace as “{existing.filename}”."
            )
        # An interrupted upload: restart it cleanly at the same reserved path.
        await storage.delete(existing.storage_key)
        existing.material_role = request.material_role
        session.commit()
        return UploadIntentOut(
            document_id=existing.id,
            storage_path=existing.storage_key,
            tus_endpoint=storage.tus_endpoint,
            bucket=BUCKET,
        )
    document_id = uuid.uuid4()
    storage_key = _storage_key(request.workspace_id, document_id, request.filename)
    session.add(
        Document(
            id=document_id,
            workspace_id=request.workspace_id,
            student_id=student_id,
            material_role=request.material_role,
            filename=request.filename,
            storage_key=storage_key,
            mime_type=request.mime_type,
            byte_size=request.byte_size,
            checksum_sha256=request.checksum_sha256,
            state="uploaded",
        )
    )
    session.commit()
    return UploadIntentOut(
        document_id=document_id,
        storage_path=storage_key,
        tus_endpoint=storage.tus_endpoint,
        bucket=BUCKET,
    )


async def confirm_upload(
    session: Session,
    student_id: UUID,
    document_id: UUID,
    request: ConfirmUploadRequest,
    storage: SupabaseStorage,
) -> Document:
    document = require_document_owner(session, student_id, document_id)
    if document.state != "uploaded":
        raise invalid_state("This upload was already confirmed.")
    if request.checksum_sha256 != document.checksum_sha256:
        raise invalid_state("The uploaded file does not match the announced file.")
    object_data = await storage.object_metadata(document.storage_key)
    if not object_data or object_data.size != document.byte_size:
        raise invalid_state(
            "The uploaded file could not be found in storage. Please upload it again."
        )
    require_document_transition(document.state, "scanning")
    document.state = "scanning"
    document.updated_at = func.now()
    session.flush()
    return document


def prepare_retry(session: Session, student_id: UUID, document_id: UUID) -> Document:
    document = require_document_owner(session, student_id, document_id)
    if document.state != "failed":
        raise invalid_state("Only a failed document can be retried.")
    require_document_transition(document.state, "scanning")
    document.state = "scanning"
    document.failure_code = None
    document.updated_at = func.now()
    session.flush()
    return document


def list_documents(session: Session, student_id: UUID, workspace_id: UUID) -> list[Document]:
    _owned_workspace(session, student_id, workspace_id)
    return list(
        session.scalars(
            select(Document)
            .where(Document.workspace_id == workspace_id, Document.student_id == student_id)
            .order_by(Document.created_at.desc())
        )
    )


def require_document_owner(session: Session, student_id: UUID, document_id: UUID) -> Document:
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.student_id == student_id)
    )
    if not document:
        raise not_found("Document")
    return document


def document_source(session: Session, student_id: UUID, document_id: UUID) -> DocumentSourceOut:
    """Extracted text with page/heading locations: the citation-verifiable source view."""
    document = require_document_owner(session, student_id, document_id)
    chunks = session.scalars(
        select(Chunk)
        .where(Chunk.document_id == document.id, Chunk.workspace_id == document.workspace_id)
        .order_by(Chunk.chunk_index)
    ).all()
    return DocumentSourceOut(
        document=as_document_out(document),
        chunks=[
            ChunkOut(
                id=c.id,
                chunk_index=c.chunk_index,
                page_start=c.page_start,
                page_end=c.page_end,
                heading_path=list(c.heading_path or []),
                text=c.text_content,
                source_language=c.source_language,
            )
            for c in chunks
        ],
    )


def as_document_out(document: Document) -> DocumentOut:
    return DocumentOut.model_validate(document, from_attributes=True)
