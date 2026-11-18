from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_storage
from app.core.auth import Actor, require_actor
from app.core.errors import not_found, provider_unavailable
from app.schemas.workspaces import CreateWorkspaceRequest, RenameWorkspaceRequest, WorkspaceOut
from app.services.explain import asset_storage_keys
from app.services.jobs import audit
from app.services.storage import ASSET_BUCKET, SupabaseStorage
from app.services.workspaces import (
    create_workspace,
    delete_workspace_rows,
    list_workspaces,
    rename_workspace,
    workspace_storage_keys,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
def list_owned_workspaces(
    actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> list[WorkspaceOut]:
    return [
        WorkspaceOut.model_validate(w, from_attributes=True)
        for w in list_workspaces(session, actor.user_id)
    ]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_owned_workspace(
    request: CreateWorkspaceRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> WorkspaceOut:
    workspace = create_workspace(session, actor.user_id, request)
    audit(
        session,
        action="workspace.create",
        resource_type="workspace",
        student_id=actor.user_id,
        workspace_id=workspace.id,
        resource_id=workspace.id,
    )
    session.commit()
    session.refresh(workspace)
    return WorkspaceOut.model_validate(workspace, from_attributes=True)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def rename_owned_workspace(
    workspace_id: UUID,
    request: RenameWorkspaceRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> WorkspaceOut:
    try:
        workspace = rename_workspace(session, actor.user_id, workspace_id, request)
    except LookupError as error:
        raise not_found("Workspace") from error
    audit(
        session,
        action="workspace.rename",
        resource_type="workspace",
        student_id=actor.user_id,
        workspace_id=workspace_id,
        resource_id=workspace_id,
    )
    session.commit()
    session.refresh(workspace)
    return WorkspaceOut.model_validate(workspace, from_attributes=True)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_owned_workspace(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
) -> Response:
    """Removes original files first, then every database row (cascade). Irreversible."""
    try:
        keys = workspace_storage_keys(session, actor.user_id, workspace_id)
    except LookupError as error:
        raise not_found("Workspace") from error
    assets = asset_storage_keys(session, workspace_id)
    try:
        if keys:
            await storage.delete_many(keys)
        if assets:
            await storage.delete_many(assets, bucket=ASSET_BUCKET)
    except httpx.HTTPError as error:
        raise provider_unavailable(
            "Files could not be deleted right now; nothing was removed."
        ) from error
    delete_workspace_rows(session, actor.user_id, workspace_id)
    audit(
        session,
        action="workspace.delete",
        resource_type="workspace",
        student_id=actor.user_id,
        resource_id=workspace_id,
        metadata={"files": len(keys), "assets": len(assets)},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/demo", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def try_demo(
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
) -> WorkspaceOut:
    """Copy the demo workspace into the student's own account (one copy per student)."""
    from app.db.models import Profile
    from app.services.demo import create_demo_workspace

    locale = (
        session.scalar(select(Profile.selected_locale).where(Profile.id == actor.user_id)) or "en"
    )
    workspace = create_demo_workspace(session, actor.user_id, storage, locale)
    audit(
        session,
        action="workspace.demo",
        resource_type="workspace",
        student_id=actor.user_id,
        workspace_id=workspace.id,
        resource_id=workspace.id,
    )
    session.commit()
    return WorkspaceOut.model_validate(workspace, from_attributes=True)
