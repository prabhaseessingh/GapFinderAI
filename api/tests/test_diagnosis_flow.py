"""Diagnosis integration: submit -> evaluate -> Gap Report -> availability -> plan -> completion ->
re-test -> new report/plan versions with history intact -> progress. Real evaluator gate; the
Groq call is replaced by a fake that must pass the same validator."""

import re
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Attempt, Quiz, QuizQuestion, Response
from app.schemas.diagnosis import CriterionJudgement, ShortAnswerEvaluation
from app.schemas.topics import CitationReference
from app.services.evaluation import evaluate_attempt
from app.services.jobs import EVALUATE_ATTEMPT
from app.services.quiz_generation import run_generation
from tests.helpers import auth_headers, make_student
from tests.test_quiz import _generate, quiz_world  # noqa: F401 - fixture re-export

pytestmark = pytest.mark.integration


class FakeGrader:
    """Awards `fraction` of every criterion and cites the first source, like a well-behaved model."""

    def __init__(self, fraction: float = 1.0, fail: Exception | None = None) -> None:
        self.fraction, self.fail, self.calls = fraction, fail, 0

    def structured(
        self,
        _context: Any,
        *,
        output: type[ShortAnswerEvaluation],
        system: str,
        user: str,
        tier: str,
        validate: Any,
        **_: Any,
    ) -> ShortAnswerEvaluation:
        self.calls += 1
        assert tier == "quality" and "<student_answer>" in user and "untrusted" in system
        if self.fail:
            raise self.fail
        points = [float(p) for p in re.findall(r"^\[\d\] \(([0-9.]+) points\)", user, re.MULTILINE)]
        max_score = float(re.search(r"max_score ([0-9.]+)", user).group(1))  # type: ignore[union-attr]
        chunk_id, body = re.search(
            r'<source chunk_id="([^"]+)">\n(.+?)\n</source>', user, re.DOTALL
        ).groups()  # type: ignore[union-attr]
        awarded = [round(p * self.fraction, 2) for p in points]
        score = round(sum(awarded), 2)
        verdict = "correct" if score >= max_score else "incorrect" if score == 0 else "partial"
        result = output(
            verdict=verdict,
            score=score,
            max_score=max_score,
            feedback="Feedback grounded in your notes.",
            criteria=[
                CriterionJudgement(criterion_index=i, awarded_points=a, met=a >= points[i])
                for i, a in enumerate(awarded)
            ],
            citations=[
                CitationReference(chunk_id=UUID(chunk_id), quote=" ".join(body.split()[1:7]))
            ],
            evaluator_confidence=0.9,
        )
        validate(result)
        return result


def _answer_all(
    client: Any, db: Session, quiz: Quiz, headers: dict[str, str], *, correct: bool
) -> str:
    attempt = client.post(f"/quizzes/{quiz.id}/attempts", headers=headers).json()
    keys = {
        q.id: q for q in db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
    }
    for shown in attempt["questions"]:
        question = keys[UUID(shown["id"])]
        key = question.correct_answer or {}
        if question.question_type == "mcq":
            answer: Any = (
                key["option_id"]
                if correct
                else next(o["id"] for o in question.options or [] if o["id"] != key["option_id"])
            )
        elif question.question_type == "true_false":
            answer = key["boolean"] if correct else not key["boolean"]
        else:
            answer = "Current is proportional to voltage." if correct else ""
        assert (
            client.put(
                f"/attempts/{attempt['id']}/responses/{shown['id']}",
                json={"answer": answer},
                headers=headers,
            ).status_code
            == 204
        )
    submitted = client.post(f"/attempts/{attempt['id']}/submit", headers=headers).json()
    assert submitted["state"] == "submitted"
    return str(attempt["id"])


def test_full_diagnosis_plan_retest_cycle(
    client: Any,
    db: Session,
    quiz_world: dict[str, Any],  # noqa: F811
    queue: list[Any],
) -> None:
    headers = auth_headers(quiz_world["student"])
    ws = quiz_world["ws"]
    assert (
        client.get(f"/workspaces/{ws.id}/plan", headers=headers).json()["next_action"]
        == "take_diagnostic"
    )
    retest_body = {"workspace_id": str(ws.id), "kind": "retest", "question_count": 5}
    assert (
        client.post("/quizzes", json=retest_body, headers=headers).json()["error"]["code"]
        == "INVALID_STATE"
    )

    # Diagnostic: everything wrong / blank.
    quiz = _generate(db, quiz_world, 10)
    attempt_id = _answer_all(client, db, quiz, headers, correct=False)
    assert (EVALUATE_ATTEMPT, [attempt_id], attempt_id) in queue
    grader = FakeGrader()
    assert evaluate_attempt(db, grader, UUID(attempt_id)) == "evaluated"  # type: ignore[arg-type]
    assert grader.calls == 0  # blank short answers never reach the LLM
    view = client.get(f"/attempts/{attempt_id}", headers=headers).json()
    assert view["state"] == "evaluated" and view["score"] == 0 and view["report_id"]
    assert {q["verdict"] for q in view["questions"]} <= {"incorrect", "unanswered"}

    report = client.get(f"/workspaces/{ws.id}/reports/latest", headers=headers).json()
    assert report["version"] == 1 and report["quiz_kind"] == "diagnostic"
    assert {u["title"] for u in report["units"]} == {"Light", "Electricity", "Photosynthesis"}
    tested = [u for u in report["units"] if u["evaluated_questions"] >= 2]
    assert tested and all(u["label"] == "weak" and u["action"] == "study" for u in tested)
    assert all(u["missed"] and u["missed"][0]["citations"] for u in tested)
    assert report["summary"]["overall_score"] == 0

    # Availability -> plan v1.
    assert (
        client.get(f"/workspaces/{ws.id}/plan", headers=headers).json()["next_action"]
        == "set_availability"
    )
    prefs = {
        "exam_date": str(date.today() + timedelta(days=14)),
        "minutes_per_day": 60,
        "available_weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "timezone": "UTC",
    }
    past = prefs | {"exam_date": str(date.today() - timedelta(days=2))}
    assert (
        client.put(f"/workspaces/{ws.id}/study-preferences", json=past, headers=headers).status_code
        == 422
    )
    state = client.put(f"/workspaces/{ws.id}/study-preferences", json=prefs, headers=headers).json()
    plan1 = state["plan"]
    assert plan1["version"] == 1 and plan1["report_version"] == 1 and plan1["sessions"]
    assert (
        plan1["scheduled_minutes"] + sum(s["minutes"] for s in plan1["shortfall"])
        == plan1["demand_minutes"]
    )
    first = next(s for s in plan1["sessions"] if s["activity"] == "study")
    done = client.put(
        f"/plan-sessions/{first['id']}/completion", json={"done": True}, headers=headers
    ).json()
    assert done["completed_at"]
    progress = client.get(f"/workspaces/{ws.id}/progress", headers=headers).json()
    assert progress["completion"]["sessions_completed"] == 1
    assert len(progress["reports"]) == 1  # completion never changes mastery

    # Changing availability appends plan v2 from the same report, minus completed minutes.
    state = client.put(
        f"/workspaces/{ws.id}/study-preferences",
        json=prefs | {"minutes_per_day": 90},
        headers=headers,
    ).json()
    assert (
        state["plan"]["version"] == 2
        and state["plan"]["demand_minutes"] == plan1["demand_minutes"] - first["minutes"]
    )
    assert (
        client.put(
            f"/plan-sessions/{first['id']}/completion", json={"done": False}, headers=headers
        ).status_code
        == 409
    )  # old version is read-only

    # Re-test targeted at gaps, all correct.
    gap_ids = [u["topic_id"] for u in report["units"] if u["label"] != "strong"]
    created = client.post("/quizzes", json=retest_body | {"topic_ids": gap_ids}, headers=headers)
    assert created.status_code == 202 and created.json()["kind"] == "retest"
    retest = db.get(Quiz, UUID(created.json()["id"]))
    assert retest is not None
    run_generation(db, object(), retest, [UUID(t) for t in gap_ids], lambda _q: [0.0] * 384)  # type: ignore[arg-type]
    db.refresh(retest)
    retest_attempt = _answer_all(client, db, retest, headers, correct=True)
    grader = FakeGrader()
    assert evaluate_attempt(db, grader, UUID(retest_attempt)) == "evaluated"  # type: ignore[arg-type]

    report2 = client.get(f"/workspaces/{ws.id}/reports/latest", headers=headers).json()
    assert report2["version"] == 2 and report2["quiz_kind"] == "retest"
    assert report2["previous_report_id"] == report["id"]
    improved = [
        u
        for u in report2["units"]
        if u["previous_label"] == "weak" and u["evaluated_questions"] >= 2
    ]
    assert improved and all(u["mastery"] > u["previous_mastery"] for u in improved)
    assert any("includes_history" in u["reasons"] for u in improved)
    # History is immutable: v1 reads exactly as before.
    again = client.get(f"/reports/{report['id']}", headers=headers).json()
    assert again["units"] == report["units"] and again["version"] == 1
    assert [
        r["version"] for r in client.get(f"/workspaces/{ws.id}/reports", headers=headers).json()
    ] == [2, 1]
    plans = client.get(f"/workspaces/{ws.id}/plans", headers=headers).json()
    assert (
        plans[0]["version"] == 3 and plans[0]["report_version"] == 2
    )  # auto-rebuilt after the report
    old = client.get(f"/plans/{plan1['id']}", headers=headers).json()
    assert old["is_latest"] is False and old["sessions"] == [
        s | {"completed_at": old["sessions"][0]["completed_at"]} if s["id"] == first["id"] else s
        for s in plan1["sessions"]
    ]

    progress = client.get(f"/workspaces/{ws.id}/progress", headers=headers).json()
    assert [p["version"] for p in progress["reports"]] == [1, 2]
    assert progress["reports"][1]["overall_score"] == 100.0

    # Isolation: nothing is visible to another student.
    stranger = auth_headers(make_student(db))
    for path in (
        f"/workspaces/{ws.id}/reports",
        f"/workspaces/{ws.id}/reports/latest",
        f"/reports/{report['id']}",
        f"/workspaces/{ws.id}/plan",
        f"/workspaces/{ws.id}/plans",
        f"/plans/{plan1['id']}",
        f"/workspaces/{ws.id}/progress",
    ):
        assert client.get(path, headers=stranger).status_code == 404, path
    assert (
        client.put(
            f"/workspaces/{ws.id}/study-preferences", json=prefs, headers=stranger
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/plan-sessions/{first['id']}/completion", json={"done": True}, headers=stranger
        ).status_code
        == 404
    )


def test_evaluator_failure_is_visible_and_retry_keeps_graded_work(
    client: Any,
    db: Session,
    quiz_world: dict[str, Any],  # noqa: F811
    queue: list[Any],
) -> None:
    headers = auth_headers(quiz_world["student"])
    quiz = _generate(db, quiz_world, 10)
    attempt_id = _answer_all(client, db, quiz, headers, correct=True)
    assert (
        evaluate_attempt(db, FakeGrader(fail=TimeoutError()), UUID(attempt_id))
        == "evaluation_failed"
    )  # type: ignore[arg-type]
    view = client.get(f"/attempts/{attempt_id}", headers=headers).json()
    assert view["state"] == "evaluation_failed" and view["failure_code"] == "PROVIDER_UNAVAILABLE"
    assert view["score"] is None and view["report_id"] is None  # no fabricated score
    graded = db.scalars(
        select(Response).where(
            Response.attempt_id == UUID(attempt_id), Response.evaluated_at.is_not(None)
        )
    ).all()
    assert graded and all(
        r.evaluator == "deterministic" for r in graded
    )  # objective work preserved
    assert (
        client.get(f"/workspaces/{quiz.workspace_id}/reports/latest", headers=headers).status_code
        == 404
    )

    retried = client.post(f"/attempts/{attempt_id}/evaluate", headers=headers).json()
    assert retried["state"] == "submitted" and queue[-1][0] == EVALUATE_ATTEMPT
    assert client.post(f"/attempts/{attempt_id}/evaluate", headers=headers).status_code == 409
    grader = FakeGrader(fraction=0.5)
    assert evaluate_attempt(db, grader, UUID(attempt_id)) == "evaluated"  # type: ignore[arg-type]
    shorts = db.scalar(
        select(QuizQuestion).where(
            QuizQuestion.quiz_id == quiz.id, QuizQuestion.question_type == "short_answer"
        )
    )
    assert shorts is not None
    assert (
        grader.calls
        == db.query(QuizQuestion)
        .filter(QuizQuestion.quiz_id == quiz.id, QuizQuestion.question_type == "short_answer")
        .count()
    )
    view = client.get(f"/attempts/{attempt_id}", headers=headers).json()
    partial = [q for q in view["questions"] if q["question_type"] == "short_answer"]
    assert partial and all(
        q["verdict"] == "partial" and q["feedback"] and q["evaluation_citations"] for q in partial
    )
    assert evaluate_attempt(db, grader, UUID(attempt_id)) == "evaluated"  # idempotent redelivery
    assert db.scalar(select(Attempt.state).where(Attempt.id == UUID(attempt_id))) == "evaluated"
