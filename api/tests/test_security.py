"""Security regression suite.

* IDOR sweep: every route that takes a resource id (from the live OpenAPI schema, so new routes are
  covered automatically) is called by another student with the owner's REAL ids -> 404, and the
  owner's data is unchanged. The same routes without a token -> 401.
* Prompt-injection guard: every Groq call site tells the model that retrieved text is untrusted.
"""

import ast
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Attempt,
    Explanation,
    GeneratedAsset,
    Quiz,
    QuizQuestion,
    RevisionSession,
    Topic,
    Workspace,
)
from app.services.evaluation import evaluate_attempt
from tests.helpers import auth_headers, make_student
from tests.test_diagnosis_flow import FakeGrader, _answer_all
from tests.test_quiz import _generate, quiz_world  # noqa: F401 - fixture re-export

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Routes whose body names a workspace (no id in the path) are swept too.
BODY_ROUTES = [
    ("POST", "/quizzes", lambda ids: {"workspace_id": ids["workspace_id"], "question_count": 5}),
    (
        "POST",
        "/explanations",
        lambda ids: {
            "workspace_id": ids["workspace_id"],
            "question": "Explain Ohm's law",
            "locale": "en",
        },
    ),
    (
        "POST",
        "/voice/transcribe",
        lambda ids: {
            "workspace_id": ids["workspace_id"],
            "locale": "en",
            "mime_type": "audio/webm",
            "audio_base64": "QUJDREVGR0hJSktMTU5PUA==",
        },
    ),
    (
        "POST",
        "/documents/upload-intent",
        lambda ids: {
            "workspace_id": ids["workspace_id"],
            "material_role": "notes",
            "filename": "x.txt",
            "mime_type": "text/plain",
            "byte_size": 10,
            "checksum_sha256": "a" * 64,
        },
    ),
    (
        "POST",
        "/topics",
        lambda ids: {"workspace_id": ids["workspace_id"], "title": "Injected topic"},
    ),
]
PATH_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/workspaces/{workspace_id}"): {"title": "Hijacked"},
    ("POST", "/documents/{document_id}/confirm"): {"checksum_sha256": "a" * 64},
    ("PATCH", "/topics/{topic_id}"): {"title": "Hijacked"},
    ("PUT", "/attempts/{attempt_id}/responses/{question_id}"): {"answer": "A"},
    ("PUT", "/workspaces/{workspace_id}/study-preferences"): {
        "exam_date": "2099-01-01",
        "minutes_per_day": 60,
        "available_weekdays": ["mon"],
        "timezone": "UTC",
    },
    ("PUT", "/plan-sessions/{session_id}/completion"): {"done": True},
}
JOB_PARAM = {"job": "propose"}


@pytest.fixture()
def owned(client: Any, db: Session, quiz_world: dict[str, Any], queue: list[Any]) -> dict[str, str]:  # noqa: F811
    headers = auth_headers(quiz_world["student"])
    ws = quiz_world["ws"]
    quiz = _generate(db, quiz_world, 5)
    attempt_id = _answer_all(client, db, quiz, headers, correct=True)
    evaluate_attempt(db, FakeGrader(), UUID(attempt_id))  # type: ignore[arg-type]
    prefs = {
        "exam_date": "2099-01-01",
        "minutes_per_day": 60,
        "available_weekdays": ["mon", "wed"],
        "timezone": "UTC",
    }
    plan = client.put(f"/workspaces/{ws.id}/study-preferences", json=prefs, headers=headers).json()[
        "plan"
    ]
    report = client.get(f"/workspaces/{ws.id}/reports/latest", headers=headers).json()
    explanation = Explanation(
        workspace_id=ws.id,
        student_id=quiz_world["student"],
        question="Explain refraction",
        locale="en",
        state="answered",
        answer="Light bends.",
    )
    db.add(explanation)
    db.flush()
    asset = GeneratedAsset(
        explanation_id=explanation.id,
        workspace_id=ws.id,
        student_id=quiz_world["student"],
        kind="audio",
        state="ready",
        config_hash="b" * 64,
        storage_path="workspaces/x/assets/y.mp3",
    )
    db.add(asset)
    db.commit()
    question = db.scalar(select(QuizQuestion.id).where(QuizQuestion.quiz_id == quiz.id))
    document = db.execute(select(Topic.id).where(Topic.workspace_id == ws.id)).first()
    from app.db.models import Document

    return {
        "owner": str(quiz_world["student"]),
        "workspace_id": str(ws.id),
        "document_id": str(db.scalar(select(Document.id).where(Document.workspace_id == ws.id))),
        "topic_id": str(document[0]) if document else "",
        "quiz_id": str(quiz.id),
        "attempt_id": attempt_id,
        "question_id": str(question),
        "report_id": report["id"],
        "plan_id": plan["id"],
        "session_id": plan["sessions"][0]["id"]
        if plan["sessions"]
        else str(db.scalar(select(RevisionSession.id))),
        "explanation_id": str(explanation.id),
        "asset_id": str(asset.id),
    }


def _id_routes() -> list[tuple[str, str, bool]]:
    from app.main import app

    routes = []
    for path, operations in app.openapi()["paths"].items():
        if "{" not in path:
            continue
        for method, operation in operations.items():
            routes.append((method.upper(), path, "requestBody" in operation))
    return routes


@pytest.mark.integration
def test_every_id_route_denies_other_students_and_anonymous(
    client: Any, db: Session, owned: dict[str, str]
) -> None:
    stranger = auth_headers(make_student(db))
    values = owned | JOB_PARAM
    checked, problems = 0, []
    for method, path, has_body in _id_routes():
        params = re.findall(r"{(\w+)}", path)
        missing = [p for p in params if p not in values]
        assert not missing, f"add an owned id for {missing} ({method} {path}) to the IDOR sweep"
        url = path.format(**values)
        body = PATH_BODIES.get((method, path))
        assert not has_body or body is not None, (
            f"add a valid body for {method} {path} to PATH_BODIES"
        )
        response = client.request(method, url, headers=stranger, json=body)
        if response.status_code not in (403, 404):
            problems.append(f"{method} {path} -> {response.status_code} for another student")
        anonymous = client.request(method, url, json=body)
        if anonymous.status_code != 401:
            problems.append(f"{method} {path} -> {anonymous.status_code} without a token")
        checked += 1
    for method, path, make_body in BODY_ROUTES:
        response = client.request(method, path, headers=stranger, json=make_body(values))
        if response.status_code not in (403, 404):
            problems.append(
                f"{method} {path} (body workspace) -> {response.status_code} for another student"
            )
        checked += 1
    assert not problems, "\n".join(problems)
    assert checked >= 45
    # The owner's data is untouched by the sweep.
    db.expire_all()
    workspace = db.get(Workspace, UUID(owned["workspace_id"]))
    assert workspace is not None and workspace.title != "Hijacked"
    assert (
        db.scalar(select(Attempt.state).where(Attempt.id == UUID(owned["attempt_id"])))
        == "evaluated"
    )
    assert db.scalar(select(Quiz.id).where(Quiz.id == UUID(owned["quiz_id"]))) is not None
    assert db.scalar(select(Topic.title).where(Topic.title == "Injected topic")) is None


def test_every_groq_call_marks_sources_as_untrusted() -> None:
    """Static guard: each `.structured(...)` call passes a system prompt containing UNTRUSTED_SOURCE_RULE."""
    offenders, calls = [], 0
    for path in APP_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "structured"
            ):
                calls += 1
                system = next((kw.value for kw in node.keywords if kw.arg == "system"), None)
                segment = ast.get_source_segment(source, system) if system is not None else ""
                if "UNTRUSTED_SOURCE_RULE" not in (segment or ""):
                    offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno}")
    assert calls >= 7, (
        calls
    )  # topic proposal, segmentation, mapping, translation, quiz, grading, explain, visual
    assert not offenders, offenders
