from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_storage
from app.core.auth import Actor, require_actor
from app.core.config import Settings, get_settings
from app.core.errors import provider_unavailable
from app.db.models import Document
from app.schemas.documents import (
    ConfirmUploadRequest,
    DocumentOut,
    DocumentSourceOut,
    UploadIntentOut,
    UploadIntentRequest,
)
from app.services.documents import (
    as_document_out,
    confirm_upload,
    create_upload_intent,
    document_source,
    list_documents,
    prepare_retry,
    require_document_owner,
)
from app.services.jobs import PROCESS_DOCUMENT, QueueUnavailable, audit, enqueue
from app.services.storage import SupabaseStorage
from app.services.topics import recompute_importance

router = APIRouter(prefix="/documents", tags=["documents"])


def _queue_processing(session: Session, document: Document, settings: Settings) -> None:
    """Persist job + publish; a broker outage leaves a visible, retryable failed document."""
    try:
        enqueue(
            session,
            settings.redis_url,
            task_name=PROCESS_DOCUMENT,
            idempotency_key=f"{document.id}:v{document.version}",
            args=[str(document.id)],
            student_id=document.student_id,
            workspace_id=document.workspace_id,
        )
    except QueueUnavailable:
        document.state = "failed"
        document.failure_code = "QUEUE_UNAVAILABLE"
        session.commit()


@router.post("/upload-intent", response_model=UploadIntentOut, status_code=status.HTTP_201_CREATED)
async def upload_intent(
    request: UploadIntentRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
) -> UploadIntentOut:
    try:
        return await create_upload_intent(session, actor.user_id, request, storage)
    except httpx.HTTPError as error:
        raise provider_unavailable("The upload service is temporarily unavailable.") from error


@router.post("/{document_id}/confirm", response_model=DocumentOut)
async def confirm(
    document_id: UUID,
    request: ConfirmUploadRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    try:
        document = await confirm_upload(session, actor.user_id, document_id, request, storage)
    except httpx.HTTPError as error:
        raise provider_unavailable("Storage could not verify the upload. Try again.") from error
    audit(
        session,
        action="document.confirm",
        resource_type="document",
        student_id=actor.user_id,
        workspace_id=document.workspace_id,
        resource_id=document.id,
        metadata={"role": document.material_role, "bytes": document.byte_size},
    )
    session.commit()
    _queue_processing(session, document, settings)
    session.refresh(document)
    return as_document_out(document)


@router.post("/{document_id}/retry-processing", response_model=DocumentOut)
def retry_processing(
    document_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    document = prepare_retry(session, actor.user_id, document_id)
    audit(
        session,
        action="document.retry",
        resource_type="document",
        student_id=actor.user_id,
        workspace_id=document.workspace_id,
        resource_id=document.id,
    )
    session.commit()
    _queue_processing(session, document, settings)
    session.refresh(document)
    return as_document_out(document)


@router.get("/workspace/{workspace_id}", response_model=list[DocumentOut])
def documents_for_workspace(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[DocumentOut]:
    return [as_document_out(item) for item in list_documents(session, actor.user_id, workspace_id)]


@router.get("/{document_id}/source", response_model=DocumentSourceOut)
def source(
    document_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> DocumentSourceOut:
    return document_source(session, actor.user_id, document_id)


@router.get("/{document_id}/preview-url")
async def preview_url(
    document_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
) -> dict[str, str]:
    """Short-lived (60 s) signed read URL, issued only after the ownership check."""
    document = require_document_owner(session, actor.user_id, document_id)
    try:
        return {"url": await storage.signed_read_url(document.storage_key)}
    except httpx.HTTPError as error:
        raise provider_unavailable("The file preview is temporarily unavailable.") from error


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
) -> Response:
    """Removes the original file, its chunks/vectors, links and past-paper questions."""
    document = require_document_owner(session, actor.user_id, document_id)
    try:
        await storage.delete(document.storage_key)
    except httpx.HTTPError as error:
        raise provider_unavailable(
            "The file could not be deleted right now; nothing was removed."
        ) from error
    workspace_id = document.workspace_id
    session.delete(document)
    session.flush()
    recompute_importance(session, workspace_id)
    audit(
        session,
        action="document.delete",
        resource_type="document",
        student_id=actor.user_id,
        workspace_id=workspace_id,
        resource_id=document_id,
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
