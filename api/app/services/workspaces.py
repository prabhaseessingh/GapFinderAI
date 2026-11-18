from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import Document, Workspace
from app.schemas.workspaces import CreateWorkspaceRequest, RenameWorkspaceRequest


def ensure_profile(session: Session, student_id: UUID) -> None:
    """Backfill profiles for students created before the auth trigger was installed."""
    session.execute(
        text("INSERT INTO profiles (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
        {"id": student_id},
    )


def list_workspaces(session: Session, student_id: UUID) -> list[Workspace]:
    ensure_profile(session, student_id)
    session.commit()
    return list(
        session.scalars(
            select(Workspace)
            .where(Workspace.student_id == student_id)
            .order_by(Workspace.updated_at.desc())
        )
    )


def require_workspace_owner(session: Session, student_id: UUID, workspace_id: UUID) -> Workspace:
    """Raises LookupError for unknown *and* foreign workspaces (no existence oracle)."""
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.student_id == student_id)
    )
    if not workspace:
        raise LookupError("Workspace was not found")
    return workspace


def create_workspace(
    session: Session, student_id: UUID, request: CreateWorkspaceRequest
) -> Workspace:
    ensure_profile(session, student_id)
    workspace = Workspace(
        student_id=student_id, title=request.title.strip(), selected_locale=request.selected_locale
    )
    session.add(workspace)
    session.flush()
    return workspace


def rename_workspace(
    session: Session, student_id: UUID, workspace_id: UUID, request: RenameWorkspaceRequest
) -> Workspace:
    workspace = require_workspace_owner(session, student_id, workspace_id)
    workspace.title = request.title.strip()
    workspace.updated_at = func.now()
    session.flush()
    return workspace


def workspace_storage_keys(session: Session, student_id: UUID, workspace_id: UUID) -> list[str]:
    require_workspace_owner(session, student_id, workspace_id)
    return list(
        session.scalars(
            select(Document.storage_key).where(
                Document.workspace_id == workspace_id, Document.student_id == student_id
            )
        )
    )


def delete_workspace_rows(session: Session, student_id: UUID, workspace_id: UUID) -> None:
    session.delete(require_workspace_owner(session, student_id, workspace_id))
    session.flush()
