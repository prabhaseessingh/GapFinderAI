"""Account deletion cascade (files first, then every row; access ends immediately)."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import Document, Explanation, GeneratedAsset, Profile, Topic, Workspace
from tests.factories import make_document, make_topic, make_workspace
from tests.helpers import FakeStorage, auth_headers, make_student

pytestmark = pytest.mark.integration


class StubAdmin:
    """Mirrors Supabase: deleting the auth user cascades to the profile and everything under it."""

    def __init__(self, db: Session, fail: bool = False) -> None:
        self.db, self.fail, self.deleted = db, fail, []

    def delete_user(self, user_id: UUID) -> None:
        if self.fail:
            raise ConnectionError("auth down")
        with self.db.get_bind().begin() as connection:
            connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id})
        self.deleted.append(user_id)


def _account(db: Session, storage: FakeStorage) -> dict[str, Any]:
    student = make_student(db)
    first, second = make_workspace(db, student, "Physics"), make_workspace(db, student, "Biology")
    for ws, seed in ((first, 60), (second, 70)):
        doc = make_document(
            db, ws, "notes", chunks=["Current is proportional to voltage."], seed=seed
        )
        storage.objects[doc.storage_key] = 10
        make_topic(db, ws, "Electricity", status="approved")
    explanation = Explanation(
        workspace_id=first.id,
        student_id=student,
        question="Explain current",
        locale="en",
        state="answered",
        answer="It relates current and voltage.",
    )
    db.add(explanation)
    db.flush()
    db.add(
        GeneratedAsset(
            explanation_id=explanation.id,
            workspace_id=first.id,
            student_id=student,
            kind="audio",
            state="ready",
            config_hash="a" * 64,
            storage_path=f"workspaces/{first.id}/assets/x.mp3",
        )
    )
    db.commit()
    return {"student": student, "workspaces": [first.id, second.id]}


def _counts(db: Session, student: UUID) -> list[int]:
    return [
        db.scalar(select(func.count()).select_from(model).where(column == student)) or 0
        for model, column in (
            (Profile, Profile.id),
            (Workspace, Workspace.student_id),
            (Document, Document.student_id),
            (Explanation, Explanation.student_id),
            (GeneratedAsset, GeneratedAsset.student_id),
        )
    ]


def test_account_deletion_removes_files_rows_and_access(
    client: Any, db: Session, storage: FakeStorage
) -> None:
    from app.api.deps import get_auth_admin
    from app.main import app

    account = _account(db, storage)
    other = make_student(db)
    other_ws = make_workspace(db, other, "Untouched")
    admin = StubAdmin(db)
    app.dependency_overrides[get_auth_admin] = lambda: admin
    headers = auth_headers(account["student"])
    assert (
        client.post("/profile/delete-account", headers=headers, json={"confirm": "yes"}).status_code
        == 422
    )
    assert all(n > 0 for n in _counts(db, account["student"]))
    assert (
        client.post(
            "/profile/delete-account", headers=headers, json={"confirm": "DELETE"}
        ).status_code
        == 204
    )
    assert admin.deleted == [account["student"]]
    db.expire_all()
    assert _counts(db, account["student"]) == [0, 0, 0, 0, 0]
    assert (
        db.scalar(
            select(func.count())
            .select_from(Topic)
            .where(Topic.workspace_id.in_(account["workspaces"]))
        )
        == 0
    )
    assert sum("/assets/" in p for p in storage.deleted) == 1 and len(storage.deleted) == 3
    # The old token no longer reaches any of the deleted data.
    assert (
        client.get(f"/topics/workspace/{account['workspaces'][0]}", headers=headers).status_code
        == 404
    )
    assert db.get(Workspace, other_ws.id) is not None  # another student's data is untouched


def test_auth_outage_still_deletes_all_study_data(
    client: Any, db: Session, storage: FakeStorage
) -> None:
    from app.api.deps import get_auth_admin
    from app.main import app

    account = _account(db, storage)
    app.dependency_overrides[get_auth_admin] = lambda: StubAdmin(db, fail=True)
    response = client.post(
        "/profile/delete-account",
        headers=auth_headers(account["student"]),
        json={"confirm": "DELETE"},
    )
    assert response.status_code == 503 and response.json()["error"]["retryable"] is True
    db.expire_all()
    assert _counts(db, account["student"]) == [0, 0, 0, 0, 0]
