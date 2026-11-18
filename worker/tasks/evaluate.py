"""evaluate_attempt: grade a locked attempt, append Gap Report + plan.
Terminal: evaluated | evaluation_failed (visible, retryable)."""

import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.db.models import Attempt
from app.db.session import SessionLocal
from app.providers.groq import GroqNotConfigured, GroqProvider
from app.services.evaluation import evaluate_attempt as run_evaluation
from app.services.jobs import EVALUATE_ATTEMPT
from sqlalchemy import func, update
from tasks.common import advisory_lock, bind_correlation, job_done, job_running

from worker.app import celery_app

logger = logging.getLogger("gapfinder.evaluate")


@celery_app.task(name=EVALUATE_ATTEMPT, bind=True, acks_late=True)
def evaluate_attempt(self: Any, attempt_id: str, job_key: str | None = None) -> str:
    bind_correlation(self)
    key = job_key or attempt_id
    try:
        provider: GroqProvider | None = GroqProvider(get_settings())
    except GroqNotConfigured:
        provider = (
            None  # objective-only attempts still grade; short answers fail visibly
        )
    with (
        SessionLocal() as session,
        advisory_lock(session, f"evaluate:{attempt_id}") as acquired,
    ):
        if not acquired:
            return "busy"
        job_running(session, EVALUATE_ATTEMPT, key)
        try:
            state = run_evaluation(session, provider, UUID(attempt_id))
        except Exception:
            session.rollback()
            logger.exception("Evaluation crashed for %s", attempt_id)
            session.execute(
                update(Attempt)
                .where(Attempt.id == UUID(attempt_id))
                .values(
                    state="evaluation_failed",
                    failure_code="EVALUATION_ERROR",
                    updated_at=func.now(),
                )
            )
            session.commit()
            state = "evaluation_failed"
        job_done(
            session,
            EVALUATE_ATTEMPT,
            key,
            "succeeded" if state == "evaluated" else "failed",
            None if state == "evaluated" else state[:80],
            result={"state": state},
        )
        return state
