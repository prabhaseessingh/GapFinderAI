"""Durable job state (job_runs) and audit events. Redis is never the source of truth."""

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.request_context import current_request_id
from app.db.models import AuditEvent, JobRun

logger = logging.getLogger("gapfinder.jobs")

# Celery task names (shared contract between API and worker).
PROCESS_DOCUMENT = "gapfinder.process_document"
PROPOSE_TOPIC_MAP = "gapfinder.propose_topic_map"
SEGMENT_PAST_PAPER = "gapfinder.segment_past_paper"
MAP_PAST_PAPERS = "gapfinder.map_past_papers"
GENERATE_QUIZ = "gapfinder.generate_quiz"
EVALUATE_ATTEMPT = "gapfinder.evaluate_attempt"
EXPLAIN = "gapfinder.explain"
RENDER_AUDIO = "gapfinder.render_audio"
RENDER_VISUAL = "gapfinder.render_visual"


class QueueUnavailable(RuntimeError):
    pass


def upsert_job(
    session: Session,
    *,
    task_name: str,
    idempotency_key: str,
    student_id: UUID | None,
    workspace_id: UUID | None,
    state: str = "queued",
    correlation_id: str | None = None,
) -> JobRun:
    """Create or reset a job row; the (task, key) pair is the idempotency guard."""
    session.execute(
        text(
            """
            INSERT INTO job_runs (student_id, workspace_id, task_name, idempotency_key, state,
                                  correlation_id)
            VALUES (:student_id, :workspace_id, :task_name, :key, :state, :correlation_id)
            ON CONFLICT (task_name, idempotency_key) DO UPDATE
              SET state = excluded.state, error_code = NULL, correlation_id = excluded.correlation_id,
                  updated_at = now()
            """
        ),
        {
            "student_id": student_id,
            "workspace_id": workspace_id,
            "task_name": task_name,
            "key": idempotency_key,
            "state": state,
            "correlation_id": correlation_id or current_request_id(),
        },
    )
    job = session.scalar(
        select(JobRun).where(
            JobRun.task_name == task_name, JobRun.idempotency_key == idempotency_key
        )
    )
    assert job is not None
    return job


def mark_job(
    session: Session,
    task_name: str,
    idempotency_key: str,
    state: str,
    *,
    error_code: str | None = None,
    result: dict[str, Any] | None = None,
    count_attempt: bool = False,
) -> None:
    session.execute(
        text(
            """
            UPDATE job_runs SET state = :state, error_code = :error_code,
                   result = COALESCE(CAST(:result AS jsonb), result),
                   attempts = attempts + :inc, updated_at = now()
            WHERE task_name = :task_name AND idempotency_key = :key
            """
        ),
        {
            "state": state,
            "error_code": error_code,
            "result": None if result is None else json.dumps(result),
            "inc": 1 if count_attempt else 0,
            "task_name": task_name,
            "key": idempotency_key,
        },
    )


def latest_job(session: Session, workspace_id: UUID, task_name: str) -> JobRun | None:
    return session.scalar(
        select(JobRun)
        .where(JobRun.workspace_id == workspace_id, JobRun.task_name == task_name)
        .order_by(JobRun.updated_at.desc())
        .limit(1)
    )


def send_task(
    redis_url: str, task_name: str, args: list[str], correlation_id: str, job_key: str
) -> None:
    from app.core.config import get_settings

    if get_settings().task_runner == "inline":
        from app.services.inline_runner import submit

        submit(task_name, args, correlation_id, job_key)
        return

    from celery import Celery
    from kombu.exceptions import OperationalError

    try:
        Celery("gapfinder", broker=redis_url).send_task(
            task_name,
            args=args,
            kwargs={"job_key": job_key},
            headers={"correlation_id": correlation_id},
            retry=True,
            retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5},
        )
    except OperationalError as error:
        raise QueueUnavailable(task_name) from error


def enqueue(
    session: Session,
    redis_url: str,
    *,
    task_name: str,
    idempotency_key: str,
    args: list[str],
    student_id: UUID | None,
    workspace_id: UUID | None,
) -> JobRun:
    """Persist the job first, then publish. A broker outage leaves a visible failed job."""
    correlation_id = current_request_id()
    job = upsert_job(
        session,
        task_name=task_name,
        idempotency_key=idempotency_key,
        student_id=student_id,
        workspace_id=workspace_id,
        correlation_id=correlation_id,
    )
    session.commit()
    try:
        send_task(redis_url, task_name, args, correlation_id, idempotency_key)
    except QueueUnavailable:
        mark_job(session, task_name, idempotency_key, "failed", error_code="QUEUE_UNAVAILABLE")
        session.commit()
        raise
    return job


def audit(
    session: Session,
    *,
    action: str,
    resource_type: str,
    student_id: UUID | None,
    workspace_id: UUID | None = None,
    resource_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append-only audit trail. Metadata must never contain secrets or raw material."""
    session.add(
        AuditEvent(
            student_id=student_id,
            workspace_id=workspace_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=current_request_id(),
            metadata_=metadata or {},
        )
    )
