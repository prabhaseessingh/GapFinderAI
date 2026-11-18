"""generate_quiz: blueprint -> cited questions. Terminal: ready | generation_failed (visible)."""

import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.db.models import Quiz
from app.db.session import SessionLocal
from app.providers.groq import GroqDailyLimit, GroqProvider
from app.services.jobs import GENERATE_QUIZ, mark_job
from app.services.quiz_generation import QuizGenerationFailed, run_generation
from sqlalchemy import func
from tasks.common import advisory_lock, bind_correlation, job_done, job_running
from tasks.ingest import embed_query

from worker.app import celery_app

logger = logging.getLogger("gapfinder.quiz")


@celery_app.task(name=GENERATE_QUIZ, bind=True, acks_late=True)
def generate_quiz(self: Any, quiz_id: str, job_key: str | None = None) -> str:
    bind_correlation(self)
    key = job_key or quiz_id
    with SessionLocal() as session:
        quiz = session.get(Quiz, UUID(quiz_id))
        if not quiz:
            return "missing"
        if quiz.state in {"ready", "generation_failed"}:
            return quiz.state  # idempotent redelivery
        with advisory_lock(session, f"quiz:{quiz_id}") as acquired:
            if not acquired:
                return "busy"
            job_running(session, GENERATE_QUIZ, key)
            requested = [
                UUID(t) for t in (quiz.blueprint or {}).get("requested_topic_ids", [])
            ]
            try:

                def progress(done: int, total: int) -> None:
                    # Short separate transaction from the lane thread; the UI polls this count.
                    with SessionLocal() as tick:
                        mark_job(
                            tick,
                            GENERATE_QUIZ,
                            key,
                            "running",
                            result={"done": done, "total": total},
                        )
                        tick.commit()

                count = run_generation(
                    session,
                    GroqProvider(get_settings()),
                    quiz,
                    requested or None,
                    embed_query,
                    progress,
                )
                job_done(
                    session,
                    GENERATE_QUIZ,
                    key,
                    "succeeded",
                    result={"questions": count},
                )
                return "ready"
            except Exception as error:
                session.rollback()
                code = (
                    error.code
                    if isinstance(error, QuizGenerationFailed | GroqDailyLimit)
                    else "GENERATION_ERROR"
                )
                if not isinstance(error, QuizGenerationFailed | GroqDailyLimit):
                    logger.exception("Quiz generation crashed for %s", quiz_id)
                quiz = session.get(Quiz, UUID(quiz_id))
                if quiz:
                    quiz.state, quiz.failure_code, quiz.updated_at = (
                        "generation_failed",
                        code[:80],
                        func.now(),
                    )
                    session.commit()
                job_done(session, GENERATE_QUIZ, key, "failed", code[:80])
                return "failed"
