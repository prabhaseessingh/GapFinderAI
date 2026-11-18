"""Routes: Gap Reports (versioned), availability, revision plans, progress."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.core.auth import Actor, require_actor
from app.schemas.diagnosis import (
    GapReportOut,
    PlanSessionOut,
    PlanStateOut,
    PlanVersionOut,
    ProgressOut,
    ReportVersionOut,
    RevisionPlanOut,
    StudyPreferencesIn,
)
from app.services import plans, reports
from app.services.jobs import audit

router = APIRouter(tags=["diagnosis"])


class CompletionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool


@router.get("/workspaces/{workspace_id}/reports", response_model=list[ReportVersionOut])
def report_versions(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[ReportVersionOut]:
    return reports.list_reports(session, actor.user_id, workspace_id)


@router.get("/workspaces/{workspace_id}/reports/latest", response_model=GapReportOut)
def latest_report(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> GapReportOut:
    return reports.get_latest_report(session, actor.user_id, workspace_id)


@router.get("/reports/{report_id}", response_model=GapReportOut)
def report(
    report_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> GapReportOut:
    return reports.get_report(session, actor.user_id, report_id)


@router.get("/workspaces/{workspace_id}/plan", response_model=PlanStateOut)
def plan_state(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> PlanStateOut:
    return plans.plan_state(session, actor.user_id, workspace_id)


@router.put("/workspaces/{workspace_id}/study-preferences", response_model=PlanStateOut)
def set_preferences(
    workspace_id: UUID,
    body: StudyPreferencesIn,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> PlanStateOut:
    state = plans.save_preferences(session, actor.user_id, workspace_id, body)
    audit(
        session,
        action="study_preferences.save",
        resource_type="workspace",
        student_id=actor.user_id,
        workspace_id=workspace_id,
        resource_id=workspace_id,
        metadata={"minutes_per_day": body.minutes_per_day, "days": len(body.available_weekdays)},
    )
    session.commit()
    return state


@router.get("/workspaces/{workspace_id}/plans", response_model=list[PlanVersionOut])
def plan_versions(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[PlanVersionOut]:
    return plans.list_plans(session, actor.user_id, workspace_id)


@router.get("/plans/{plan_id}", response_model=RevisionPlanOut)
def plan(
    plan_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> RevisionPlanOut:
    return plans.get_plan(session, actor.user_id, plan_id)


@router.put("/plan-sessions/{session_id}/completion", response_model=PlanSessionOut)
def completion(
    session_id: UUID,
    body: CompletionIn,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> PlanSessionOut:
    return plans.set_completion(session, actor.user_id, session_id, body.done)


@router.get("/workspaces/{workspace_id}/progress", response_model=ProgressOut)
def progress(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> ProgressOut:
    return reports.progress(session, actor.user_id, workspace_id)
