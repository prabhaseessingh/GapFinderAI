"""Isolation gate: one student cannot reach another's workspace via API, SQL/RLS or retrieval."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.services.retrieval import retrieve_evidence
from tests.factories import make_document, make_topic, make_workspace, unit_vector
from tests.helpers import auth_headers, make_student

pytestmark = pytest.mark.integration


@pytest.fixture()
def two_students(db: Session) -> dict[str, Any]:
    alice, bob = make_student(db), make_student(db)
    ws_a = make_workspace(db, alice, "Alice physics")
    ws_b = make_workspace(db, bob, "Bob history")
    doc_a = make_document(
        db, ws_a, "syllabus", chunks=["Photosynthesis converts light energy"], seed=1
    )
    make_document(db, ws_b, "notes", chunks=["The Mughal empire was founded in 1526"], seed=2)
    chunk_a = db.execute(
        text("SELECT id FROM chunks WHERE document_id = :d"), {"d": doc_a.id}
    ).scalar()
    topic_a = make_topic(db, ws_a, "Photosynthesis", chunk_id=chunk_a)
    return {
        "alice": alice,
        "bob": bob,
        "ws_a": ws_a,
        "ws_b": ws_b,
        "doc_a": doc_a,
        "topic_a": topic_a,
    }


def test_api_denies_every_foreign_resource(client: Any, two_students: dict[str, Any]) -> None:
    bob = auth_headers(two_students["bob"])
    ws_a, doc_a, topic_a = (
        two_students["ws_a"].id,
        two_students["doc_a"].id,
        two_students["topic_a"].id,
    )
    attempts = [
        ("GET", f"/documents/workspace/{ws_a}", None),
        ("GET", f"/topics/workspace/{ws_a}", None),
        ("PATCH", f"/workspaces/{ws_a}", {"title": "pwned"}),
        ("DELETE", f"/workspaces/{ws_a}", None),
        ("GET", f"/documents/{doc_a}/source", None),
        ("GET", f"/documents/{doc_a}/preview-url", None),
        ("DELETE", f"/documents/{doc_a}", None),
        ("POST", f"/documents/{doc_a}/retry-processing", None),
        ("PATCH", f"/topics/{topic_a}", {"title": "pwned"}),
        ("POST", f"/topics/{topic_a}/approve", None),
        ("GET", f"/topics/{topic_a}/citations", None),
        ("DELETE", f"/topics/{topic_a}", None),
        ("POST", "/topics", {"workspace_id": str(ws_a), "title": "x"}),
        (
            "POST",
            "/documents/upload-intent",
            {
                "workspace_id": str(ws_a),
                "material_role": "notes",
                "filename": "a.txt",
                "mime_type": "text/plain",
                "byte_size": 5,
                "checksum_sha256": "a" * 64,
            },
        ),
    ]
    for method, path, body in attempts:
        response = client.request(method, path, json=body, headers=bob)
        assert response.status_code == 404, (method, path, response.status_code)
        assert response.json()["error"]["code"] == "NOT_FOUND"
    # Bob only ever sees his own workspace.
    titles = [w["title"] for w in client.get("/workspaces", headers=bob).json()]
    assert titles == ["Bob history"]


def test_requests_without_valid_token_are_rejected(
    client: Any, two_students: dict[str, Any]
) -> None:
    for headers in ({}, {"authorization": "Bearer not-a-jwt"}):
        response = client.get("/workspaces", headers=headers)
        assert response.status_code == 401
        body = response.json()["error"]
        assert body["code"] == "UNAUTHENTICATED" and body["nextAction"] == "sign_in"
        assert body["requestId"].startswith("req_")


def test_rls_limits_authenticated_role_to_own_rows(
    db: Session, two_students: dict[str, Any]
) -> None:
    connection = db.connection()
    connection.execute(text("SET LOCAL ROLE authenticated"))
    connection.execute(
        text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
        {"sub": str(two_students["bob"])},
    )
    for table in ("workspaces", "documents", "chunks", "topics", "topic_chunk_links"):
        rows = connection.execute(text(f"SELECT * FROM {table}")).mappings().all()
        assert all(
            str(two_students["ws_a"].id) not in {str(v) for v in row.values()} for row in rows
        ), table
    assert connection.execute(text("SELECT count(*) FROM topics")).scalar() == 0
    assert connection.execute(text("SELECT count(*) FROM workspaces")).scalar() == 1
    db.rollback()


def test_rls_blocks_writes_and_audit_tables(db: Session, two_students: dict[str, Any]) -> None:
    connection = db.connection()
    connection.execute(text("SET LOCAL ROLE authenticated"))
    connection.execute(
        text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
        {"sub": str(two_students["alice"])},
    )
    with pytest.raises(ProgrammingError):
        connection.execute(text("UPDATE workspaces SET title = 'x'"))
    db.rollback()
    connection = db.connection()
    connection.execute(text("SET LOCAL ROLE authenticated"))
    with pytest.raises(ProgrammingError):
        connection.execute(text("SELECT * FROM ai_runs"))
    db.rollback()


def test_anon_role_reads_nothing(db: Session, two_students: dict[str, Any]) -> None:
    connection = db.connection()
    connection.execute(text("SET LOCAL ROLE anon"))
    with pytest.raises(ProgrammingError):
        connection.execute(text("SELECT * FROM workspaces"))
    db.rollback()


def test_retrieval_never_crosses_workspaces(db: Session, two_students: dict[str, Any]) -> None:
    bundle = retrieve_evidence(
        db,
        two_students["bob"],
        two_students["ws_b"].id,
        "photosynthesis light energy",
        query_embedding=[float(x) for x in unit_vector(1)[1:-1].split(",")],
    )
    assert bundle.insufficient
    own = retrieve_evidence(db, two_students["bob"], two_students["ws_b"].id, "Mughal empire")
    assert [item.document_name for item in own.items] == ["notes-2.txt"]
    with pytest.raises(LookupError):
        retrieve_evidence(db, two_students["bob"], two_students["ws_a"].id, "photosynthesis")
