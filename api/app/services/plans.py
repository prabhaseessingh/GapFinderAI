"""Availability + immutable revision plan versions.

A new plan version is appended after every Gap Report (when availability is saved) and on
every availability change. Completed sessions reduce the unit's remaining demand only in
later plans built from the same report; mastery is never changed by completion.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.core.fair_use import zone
from app.db.models import (
    GapReport,
    RevisionPlan,
    RevisionSession,
    SessionCompletion,
    StudyPreferences,
)
from app.schemas.diagnosis import (
    PlanSessionOut,
    PlanStateOut,
    PlanVersionOut,
    RevisionPlanOut,
    StudyPreferencesIn,
    StudyPreferencesOut,
)
from app.services.plan_policy import PlanUnit, build_plan
from app.services.reports import _owned, latest_report, snapshots

FOCUS_ACCURACY_BELOW = 0.75
MAX_FOCUS = 3


def latest_preferences(
    session: Session, workspace_id: UUID, student_id: UUID
) -> StudyPreferences | None:
    return session.scalar(
        select(StudyPreferences)
        .where(
            StudyPreferences.workspace_id == workspace_id, StudyPreferences.student_id == student_id
        )
        .order_by(StudyPreferences.created_at.desc(), StudyPreferences.id.desc())
        .limit(1)
    )


def latest_plan(session: Session, workspace_id: UUID, student_id: UUID) -> RevisionPlan | None:
    return session.scalar(
        select(RevisionPlan)
        .where(RevisionPlan.workspace_id == workspace_id, RevisionPlan.student_id == student_id)
        .order_by(RevisionPlan.version.desc())
        .limit(1)
    )


def local_today(timezone: str, now: datetime | None = None) -> date:
    # zone() falls back instead of raising: an unreadable stored zone must never fail grading.
    return (now or datetime.now(UTC)).astimezone(zone(timezone)).date()


def _focus(facts: dict[str, object]) -> tuple[str, ...]:
    raw = facts.get("subtopics")
    subs = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
    weak = sorted(
        (s for s in subs if float(s.get("accuracy", 1)) < FOCUS_ACCURACY_BELOW),
        key=lambda s: float(s.get("accuracy", 1)),
    )
    return tuple(str(s["title"]) for s in weak[:MAX_FOCUS])


def completed_minutes(session: Session, report_id: UUID) -> dict[UUID, int]:
    rows = session.execute(
        select(RevisionSession.topic_id, func.sum(RevisionSession.minutes))
        .join(SessionCompletion, SessionCompletion.session_id == RevisionSession.id)
        .join(RevisionPlan, RevisionPlan.id == RevisionSession.plan_id)
        .where(
            RevisionPlan.report_id == report_id,
            RevisionSession.topic_id.is_not(None),
            RevisionSession.activity != "retest",
        )
        .group_by(RevisionSession.topic_id)
    ).all()
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}


def rebuild_plan(
    session: Session,
    workspace_id: UUID,
    student_id: UUID,
    *,
    report_id: UUID | None = None,
    now: datetime | None = None,
) -> RevisionPlan | None:
    """Append a plan version from the latest report + availability. None when either is missing
    or the exam date has passed (the UI then asks for new availability)."""
    report = (
        session.get(GapReport, report_id)
        if report_id
        else latest_report(session, workspace_id, student_id)
    )
    prefs = latest_preferences(session, workspace_id, student_id)
    if report is None or prefs is None:
        return None
    today = local_today(prefs.timezone, now)
    if prefs.exam_date < today:
        return None
    units = [
        PlanUnit(
            s.topic_id,
            s.topic_title,
            s.label,
            s.importance,
            s.priority,
            s.position,
            _focus(s.facts or {}),
        )
        for s in snapshots(session, report.id)
        if s.topic_id is not None
    ]
    plan = build_plan(
        units,
        today,
        prefs.exam_date,
        prefs.minutes_per_day,
        prefs.available_weekdays,
        completed_minutes(session, report.id),
    )
    session.execute(
        text("SELECT 1 FROM workspaces WHERE id = :id FOR UPDATE"), {"id": workspace_id}
    )
    version = (
        session.scalar(
            select(func.max(RevisionPlan.version)).where(RevisionPlan.workspace_id == workspace_id)
        )
        or 0
    ) + 1
    row = RevisionPlan(
        workspace_id=workspace_id,
        student_id=student_id,
        report_id=report.id,
        preferences_id=prefs.id,
        version=version,
        status=plan.status,
        demand_minutes=plan.demand_minutes,
        scheduled_minutes=plan.scheduled_minutes,
        available_minutes=plan.available_minutes,
        shortfall=plan.shortfall,
        policy_version=plan.policy_version,
    )
    session.add(row)
    session.flush()
    for planned in plan.sessions:
        session.add(
            RevisionSession(
                plan_id=row.id,
                workspace_id=workspace_id,
                day=planned.day,
                sequence=planned.sequence,
                topic_id=planned.topic_id,
                topic_title=planned.topic_title,
                focus=list(planned.focus),
                activity=planned.activity,
                minutes=planned.minutes,
            )
        )
    session.flush()
    return row


# ---- API helpers ---------------------------------------------------------------------------------


def _prefs_out(prefs: StudyPreferences) -> StudyPreferencesOut:
    return StudyPreferencesOut(
        id=prefs.id,
        created_at=prefs.created_at,
        exam_date=prefs.exam_date,
        minutes_per_day=prefs.minutes_per_day,
        available_weekdays=list(prefs.available_weekdays),  # type: ignore[arg-type]
        timezone=prefs.timezone,
    )


def plan_out(session: Session, plan: RevisionPlan) -> RevisionPlanOut:
    prefs = session.get(StudyPreferences, plan.preferences_id)
    report = session.get(GapReport, plan.report_id)
    assert prefs is not None and report is not None
    latest = latest_plan(session, plan.workspace_id, plan.student_id)
    rows = session.execute(
        select(RevisionSession, SessionCompletion.completed_at)
        .outerjoin(SessionCompletion, SessionCompletion.session_id == RevisionSession.id)
        .where(RevisionSession.plan_id == plan.id)
        .order_by(RevisionSession.day, RevisionSession.sequence)
    ).all()
    return RevisionPlanOut(
        id=plan.id,
        version=plan.version,
        report_id=plan.report_id,
        report_version=report.version,
        preferences=_prefs_out(prefs),
        status=plan.status,  # type: ignore[arg-type]
        demand_minutes=plan.demand_minutes,
        scheduled_minutes=plan.scheduled_minutes,
        available_minutes=plan.available_minutes,
        shortfall=plan.shortfall,
        policy_version=plan.policy_version,
        created_at=plan.created_at,
        is_latest=latest is not None and latest.id == plan.id,
        sessions=[
            PlanSessionOut(
                id=s.id,
                day=s.day,
                sequence=s.sequence,
                topic_id=s.topic_id,
                topic_title=s.topic_title,
                focus=list(s.focus or []),
                activity=s.activity,  # type: ignore[arg-type]
                minutes=s.minutes,
                completed_at=done,
            )
            for s, done in rows
        ],
    )


def plan_state(session: Session, student_id: UUID, workspace_id: UUID) -> PlanStateOut:
    _owned(session, student_id, workspace_id)
    prefs = latest_preferences(session, workspace_id, student_id)
    plan = latest_plan(session, workspace_id, student_id)
    has_report = latest_report(session, workspace_id, student_id) is not None
    next_action = (
        "take_diagnostic" if not has_report else "set_availability" if prefs is None else "none"
    )
    return PlanStateOut(
        preferences=_prefs_out(prefs) if prefs else None,
        plan=plan_out(session, plan) if plan else None,
        next_action=next_action,  # type: ignore[arg-type]
    )


def save_preferences(
    session: Session,
    student_id: UUID,
    workspace_id: UUID,
    body: StudyPreferencesIn,
    now: datetime | None = None,
) -> PlanStateOut:
    _owned(session, student_id, workspace_id)
    if body.exam_date < local_today(body.timezone, now):
        raise AppError(422, "VALIDATION_ERROR", "The exam date is in the past.")
    session.add(
        StudyPreferences(
            workspace_id=workspace_id,
            student_id=student_id,
            exam_date=body.exam_date,
            minutes_per_day=body.minutes_per_day,
            available_weekdays=list(body.available_weekdays),
            timezone=body.timezone,
        )
    )
    session.flush()
    rebuild_plan(session, workspace_id, student_id, now=now)
    session.commit()
    return plan_state(session, student_id, workspace_id)


def list_plans(session: Session, student_id: UUID, workspace_id: UUID) -> list[PlanVersionOut]:
    _owned(session, student_id, workspace_id)
    rows = session.execute(
        select(RevisionPlan, GapReport.version)
        .join(GapReport, GapReport.id == RevisionPlan.report_id)
        .where(RevisionPlan.workspace_id == workspace_id, RevisionPlan.student_id == student_id)
        .order_by(RevisionPlan.version.desc())
    ).all()
    return [
        PlanVersionOut(
            id=p.id, version=p.version, report_version=v, status=p.status, created_at=p.created_at
        )
        for p, v in rows
    ]


def get_plan(session: Session, student_id: UUID, plan_id: UUID) -> RevisionPlanOut:
    plan = session.scalar(
        select(RevisionPlan).where(
            RevisionPlan.id == plan_id, RevisionPlan.student_id == student_id
        )
    )
    if plan is None:
        raise not_found("Plan")
    return plan_out(session, plan)


def set_completion(
    session: Session, student_id: UUID, session_id: UUID, done: bool
) -> PlanSessionOut:
    row = session.execute(
        select(RevisionSession, RevisionPlan)
        .join(RevisionPlan, RevisionPlan.id == RevisionSession.plan_id)
        .where(RevisionSession.id == session_id, RevisionPlan.student_id == student_id)
    ).first()
    if row is None:
        raise not_found("Session")
    revision_session, plan = row
    latest = latest_plan(session, plan.workspace_id, student_id)
    if latest is None or latest.id != plan.id:
        raise AppError(409, "INVALID_STATE", "Older plan versions are read-only.")
    if done:
        session.execute(
            text("""INSERT INTO session_completions (session_id, workspace_id) VALUES (:s, :w)
                                ON CONFLICT (session_id) DO NOTHING"""),
            {"s": revision_session.id, "w": revision_session.workspace_id},
        )
    else:
        session.execute(
            text("DELETE FROM session_completions WHERE session_id = :s"),
            {"s": revision_session.id},
        )
    session.commit()
    completed = session.scalar(
        select(SessionCompletion.completed_at).where(SessionCompletion.session_id == session_id)
    )
    return PlanSessionOut(
        id=revision_session.id,
        day=revision_session.day,
        sequence=revision_session.sequence,
        topic_id=revision_session.topic_id,
        topic_title=revision_session.topic_title,
        focus=list(revision_session.focus or []),
        activity=revision_session.activity,  # type: ignore[arg-type]
        minutes=revision_session.minutes,
        completed_at=completed,
    )
