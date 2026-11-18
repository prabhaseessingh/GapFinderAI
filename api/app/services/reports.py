"""Gap Reports: append-only versions built from every evaluated attempt in a workspace.

A report diagnoses every approved top-level unit with `diagnosis_policy` (pure). Snapshots are
written once and never updated (invariant 5); the projection adds reason codes, the next action,
missed-question evidence and the previous version's label for comparison.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.db.models import (
    Attempt,
    GapReport,
    Quiz,
    QuizQuestion,
    Response,
    RevisionPlan,
    RevisionSession,
    SessionCompletion,
    Topic,
    TopicMasterySnapshot,
)
from app.schemas.diagnosis import (
    GapReportOut,
    MissedQuestionOut,
    ProgressOut,
    ProgressPoint,
    ReportVersionOut,
    UnitReportOut,
)
from app.services.diagnosis_policy import (
    DIAGNOSIS_POLICY_VERSION,
    EvaluatedItem,
    UnitInput,
    diagnose,
    overall_score,
)
from app.services.quizzes import resolve_citations
from app.services.workspaces import require_workspace_owner

HIGH_IMPORTANCE = 4


def _owned(session: Session, student_id: UUID, workspace_id: UUID) -> None:
    try:
        require_workspace_owner(session, student_id, workspace_id)
    except LookupError as error:
        raise not_found("Workspace") from error


def _root(topic_id: UUID, parents: dict[UUID, UUID | None]) -> UUID | None:
    seen: set[UUID] = set()
    current: UUID | None = topic_id
    while current is not None and current in parents and current not in seen:
        seen.add(current)
        parent = parents[current]
        if parent is None:
            return current
        current = parent
    return None


def build_unit_inputs(
    session: Session, workspace_id: UUID, student_id: UUID, include_attempt: UUID | None = None
) -> list[UnitInput]:
    topics = list(session.scalars(select(Topic).where(Topic.workspace_id == workspace_id)))
    parents = {t.id: t.parent_id for t in topics}
    units = [t for t in topics if t.parent_id is None and t.status == "approved"]
    state_ok = Attempt.state == "evaluated"
    if include_attempt is not None:
        state_ok = or_(state_ok, Attempt.id == include_attempt)
    rows = session.execute(
        select(Response, QuizQuestion, Attempt)
        .join(QuizQuestion, QuizQuestion.id == Response.question_id)
        .join(Attempt, Attempt.id == Response.attempt_id)
        .where(
            Attempt.workspace_id == workspace_id,
            Attempt.student_id == student_id,
            state_ok,
            Response.evaluated_at.is_not(None),
            Response.score.is_not(None),
        )
    ).all()
    by_unit: dict[UUID, list[tuple[Response, QuizQuestion, Attempt]]] = defaultdict(list)
    for response, question, attempt in rows:
        unit_id = _root(question.topic_id, parents) if question.topic_id else None
        if unit_id is not None:
            by_unit[unit_id].append((response, question, attempt))
    inputs: list[UnitInput] = []
    for unit in units:
        graded = by_unit.get(unit.id, [])
        order = sorted(
            {a.id: a for _, _, a in graded}.values(),
            key=lambda a: a.submitted_at or a.created_at,
            reverse=True,
        )
        rank = {a.id: i for i, a in enumerate(order)}
        items = tuple(
            EvaluatedItem(
                question_id=q.id,
                attempt_rank=rank[a.id],
                cognitive_level=q.cognitive_level,
                score=float(r.score or 0),
                max_score=float(r.max_score or q.max_score),
                confidence=float(r.confidence if r.confidence is not None else 0),
                subtopic=q.topic_title,
                question_type=q.question_type,
                attempt_id=a.id,
            )
            for r, q, a in graded
        )
        inputs.append(UnitInput(unit.id, unit.title, unit.position, unit.importance, items))
    return inputs


def create_report(session: Session, attempt: Attempt) -> GapReport:
    workspace_id, student_id = attempt.workspace_id, attempt.student_id
    # Serialise report versions per workspace.
    session.execute(
        text("SELECT 1 FROM workspaces WHERE id = :id FOR UPDATE"), {"id": workspace_id}
    )
    diagnoses = diagnose(
        build_unit_inputs(session, workspace_id, student_id, include_attempt=attempt.id)
    )
    previous = latest_report(session, workspace_id, student_id)
    version = (
        session.scalar(
            select(func.max(GapReport.version)).where(GapReport.workspace_id == workspace_id)
        )
        or 0
    ) + 1
    quiz = session.get(Quiz, attempt.quiz_id)
    pairs = [
        (float(r.score or 0), float(r.max_score or 0))
        for r in session.scalars(
            select(Response).where(Response.attempt_id == attempt.id, Response.score.is_not(None))
        )
    ]
    questions = (
        session.scalar(
            select(func.count())
            .select_from(QuizQuestion)
            .where(QuizQuestion.quiz_id == attempt.quiz_id)
        )
        or 0
    )
    answered = (
        session.scalar(
            select(func.count())
            .select_from(Response)
            .where(
                Response.attempt_id == attempt.id,
                Response.verdict.is_not(None),
                Response.verdict != "unanswered",
            )
        )
        or 0
    )
    labels: dict[str, int] = defaultdict(int)
    for diagnosis in diagnoses:
        labels[diagnosis.label] += 1
    report = GapReport(
        workspace_id=workspace_id,
        student_id=student_id,
        attempt_id=attempt.id,
        version=version,
        policy_version=DIAGNOSIS_POLICY_VERSION,
        summary={
            "quiz_id": str(attempt.quiz_id),
            "quiz_kind": quiz.kind if quiz else None,
            "overall_score": overall_score(pairs),
            "questions": questions,
            "answered": answered,
            "labels": dict(labels),
            "previous_report_id": str(previous.id) if previous else None,
        },
    )
    session.add(report)
    session.flush()
    for diagnosis in diagnoses:
        session.add(
            TopicMasterySnapshot(
                report_id=report.id,
                workspace_id=workspace_id,
                topic_id=diagnosis.topic_id,
                topic_title=diagnosis.title,
                position=diagnosis.position,
                label=diagnosis.label,
                mastery=diagnosis.mastery,
                confidence=diagnosis.confidence,
                priority=diagnosis.priority,
                importance=diagnosis.importance,
                evaluated_questions=diagnosis.evaluated_questions,
                facts=diagnosis.facts,
            )
        )
    session.flush()
    return report


def latest_report(session: Session, workspace_id: UUID, student_id: UUID) -> GapReport | None:
    return session.scalar(
        select(GapReport)
        .where(GapReport.workspace_id == workspace_id, GapReport.student_id == student_id)
        .order_by(GapReport.version.desc())
        .limit(1)
    )


def snapshots(session: Session, report_id: UUID) -> list[TopicMasterySnapshot]:
    return list(
        session.scalars(
            select(TopicMasterySnapshot)
            .where(TopicMasterySnapshot.report_id == report_id)
            .order_by(TopicMasterySnapshot.priority.desc(), TopicMasterySnapshot.position)
        )
    )


# ---- projection ----------------------------------------------------------------------------------


def reasons_for(snapshot: TopicMasterySnapshot, importance_source: str | None) -> list[str]:
    facts = snapshot.facts or {}
    if snapshot.label == "limited_evidence":
        codes = [f"limited_{facts.get('limited_reason') or 'few_questions'}"]
    else:
        codes = [f"score_{snapshot.label}"]
        if facts.get("weak_levels"):
            codes.append("weak_cognitive_levels")
    if snapshot.importance >= HIGH_IMPORTANCE:
        codes.append(
            "high_importance_past_papers"
            if importance_source == "past_papers"
            else "high_importance_student"
            if importance_source == "student"
            else "high_importance"
        )
    if (facts.get("attempts") or 0) > 1:
        codes.append("includes_history")
    return codes


def action_for(label: str) -> str:
    return {"weak": "study", "medium": "study", "strong": "review"}.get(label, "retest")


def _missed(
    session: Session, snapshot: TopicMasterySnapshot, student_id: UUID
) -> list[MissedQuestionOut]:
    out: list[MissedQuestionOut] = []
    for ref in (snapshot.facts or {}).get("missed", []):
        question = session.get(QuizQuestion, UUID(ref["question_id"]))
        if question is None or question.workspace_id != snapshot.workspace_id:
            continue
        response = (
            session.scalar(
                select(Response).where(
                    Response.question_id == question.id,
                    Response.attempt_id == UUID(ref["attempt_id"]),
                )
            )
            if ref.get("attempt_id")
            else None
        )
        out.append(
            MissedQuestionOut(
                question_id=question.id,
                attempt_id=UUID(ref["attempt_id"]) if ref.get("attempt_id") else question.quiz_id,
                prompt=question.prompt,
                question_type=question.question_type,
                cognitive_level=question.cognitive_level,
                topic_title=question.topic_title,
                score=response.score if response else None,
                max_score=question.max_score,
                verdict=response.verdict if response else None,
                feedback=((response.evaluation or {}).get("feedback") if response else None)
                or question.explanation,
                citations=resolve_citations(
                    session, question.workspace_id, student_id, question.citations
                ),
            )
        )
    return out


def report_out(session: Session, report: GapReport) -> GapReportOut:
    previous_id = (report.summary or {}).get("previous_report_id")
    previous = {s.topic_id: s for s in snapshots(session, UUID(previous_id))} if previous_id else {}
    sources = dict(
        session.execute(
            select(Topic.id, Topic.importance_source).where(
                Topic.workspace_id == report.workspace_id
            )
        ).all()
    )
    units = []
    for snap in snapshots(session, report.id):
        before = previous.get(snap.topic_id)
        units.append(
            UnitReportOut(
                topic_id=snap.topic_id,
                title=snap.topic_title,
                position=snap.position,
                label=snap.label,  # type: ignore[arg-type]
                mastery=snap.mastery,
                confidence=snap.confidence,
                priority=snap.priority,
                importance=snap.importance,
                importance_source=sources.get(snap.topic_id) if snap.topic_id else None,
                evaluated_questions=snap.evaluated_questions,
                facts=snap.facts,
                reasons=reasons_for(snap, sources.get(snap.topic_id) if snap.topic_id else None),
                action=action_for(snap.label),  # type: ignore[arg-type]
                missed=_missed(session, snap, report.student_id),
                previous_label=before.label if before else None,  # type: ignore[arg-type]
                previous_mastery=before.mastery if before else None,
            )
        )
    return GapReportOut(
        id=report.id,
        workspace_id=report.workspace_id,
        version=report.version,
        attempt_id=report.attempt_id,
        quiz_kind=(report.summary or {}).get("quiz_kind"),
        policy_version=report.policy_version,
        created_at=report.created_at,
        summary=report.summary,
        units=units,
        previous_report_id=UUID(previous_id) if previous_id else None,
    )


def get_latest_report(session: Session, student_id: UUID, workspace_id: UUID) -> GapReportOut:
    _owned(session, student_id, workspace_id)
    report = latest_report(session, workspace_id, student_id)
    if report is None:
        raise not_found("Gap Report")
    return report_out(session, report)


def get_report(session: Session, student_id: UUID, report_id: UUID) -> GapReportOut:
    report = session.scalar(
        select(GapReport).where(GapReport.id == report_id, GapReport.student_id == student_id)
    )
    if report is None:
        raise not_found("Gap Report")
    return report_out(session, report)


def list_reports(session: Session, student_id: UUID, workspace_id: UUID) -> list[ReportVersionOut]:
    _owned(session, student_id, workspace_id)
    reports = session.scalars(
        select(GapReport)
        .where(GapReport.workspace_id == workspace_id, GapReport.student_id == student_id)
        .order_by(GapReport.version.desc())
    )
    return [
        ReportVersionOut(
            id=r.id,
            version=r.version,
            created_at=r.created_at,
            attempt_id=r.attempt_id,
            quiz_kind=(r.summary or {}).get("quiz_kind"),
            overall_score=(r.summary or {}).get("overall_score"),
        )
        for r in reports
    ]


def progress(session: Session, student_id: UUID, workspace_id: UUID) -> ProgressOut:
    _owned(session, student_id, workspace_id)
    reports = list(
        session.scalars(
            select(GapReport)
            .where(GapReport.workspace_id == workspace_id, GapReport.student_id == student_id)
            .order_by(GapReport.version)
        )
    )
    titles: dict[str, int] = {}
    points: list[ProgressPoint] = []
    for report in reports:
        snaps = list(
            session.scalars(
                select(TopicMasterySnapshot)
                .where(TopicMasterySnapshot.report_id == report.id)
                .order_by(TopicMasterySnapshot.position)
            )
        )
        for snap in snaps:
            titles.setdefault(snap.topic_title, snap.position)
        points.append(
            ProgressPoint(
                report_id=report.id,
                version=report.version,
                created_at=report.created_at,
                quiz_kind=(report.summary or {}).get("quiz_kind"),
                overall_score=(report.summary or {}).get("overall_score"),
                units={
                    s.topic_title: (None if s.label == "limited_evidence" else s.mastery)
                    for s in snaps
                },
                labels={s.topic_title: s.label for s in snaps},
            )
        )
    plan = session.scalar(
        select(RevisionPlan)
        .where(RevisionPlan.workspace_id == workspace_id, RevisionPlan.student_id == student_id)
        .order_by(RevisionPlan.version.desc())
        .limit(1)
    )
    completion = {
        "sessions_planned": 0,
        "sessions_completed": 0,
        "minutes_planned": 0,
        "minutes_completed": 0,
    }
    if plan is not None:
        for sess, done in session.execute(
            select(RevisionSession, SessionCompletion.session_id)
            .outerjoin(SessionCompletion, SessionCompletion.session_id == RevisionSession.id)
            .where(RevisionSession.plan_id == plan.id)
        ).all():
            completion["sessions_planned"] += 1
            completion["minutes_planned"] += sess.minutes
            if done is not None:
                completion["sessions_completed"] += 1
                completion["minutes_completed"] += sess.minutes
    return ProgressOut(
        reports=points, unit_titles=sorted(titles, key=lambda t: titles[t]), completion=completion
    )
