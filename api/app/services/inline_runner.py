"""Run background jobs on threads inside the API process (TASK_RUNNER=inline).

For hosts with no free worker/queue (Render free tier). The Celery task functions are reused
unchanged and executed eagerly. job_runs in Postgres stays the source of truth: a restart loses
in-flight work, so `recover_after_restart` re-dispatches documents and fails the other stale jobs
visibly instead of leaving them "running" forever.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.jobs import PROCESS_DOCUMENT, mark_job

logger = logging.getLogger("gapfinder.inline")
_executor: ThreadPoolExecutor | None = None
_lock = Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=max(1, get_settings().inline_workers), thread_name_prefix="inline-job"
            )
        return _executor


def _task(task_name: str) -> Any:
    from worker.app import celery_app  # lazy: pulls in pymupdf etc. only when a job runs

    celery_app.loader.import_default_modules()
    return celery_app.tasks[task_name]


def _run(task_name: str, args: list[str], correlation_id: str | None, job_key: str) -> None:
    try:
        result = _task(task_name).apply(
            args=args, kwargs={"job_key": job_key}, headers={"correlation_id": correlation_id}
        )
        if result.failed():
            raise RuntimeError(str(result.result))
    except Exception:
        logger.exception("Inline job %s (%s) crashed", task_name, job_key)
        try:
            with SessionLocal() as session:
                mark_job(session, task_name, job_key, "failed", error_code="WORKER_ERROR")
                session.commit()
        except Exception:
            logger.exception("Could not record failure for %s", job_key)


def submit(task_name: str, args: list[str], correlation_id: str | None, job_key: str) -> None:
    _pool().submit(_run, task_name, list(args), correlation_id, job_key)


def recover_after_restart() -> None:
    """Called once at startup. Safe to call when there is nothing to recover."""
    try:
        with SessionLocal() as session:
            docs = (
                session.execute(
                    text(
                        "SELECT id::text FROM documents "
                        "WHERE state IN ('scanning','extracting','chunking','embedding','mapping') "
                        "AND updated_at < now() - interval '2 minutes'"
                    )
                )
                .scalars()
                .all()
            )
            stale = session.execute(
                text(
                    "SELECT task_name, idempotency_key FROM job_runs "
                    "WHERE state IN ('queued','running') AND task_name <> :doc "
                    "AND updated_at < now() - interval '5 minutes'"
                ),
                {"doc": PROCESS_DOCUMENT},
            ).all()
            for task_name, key in stale:
                mark_job(session, task_name, key, "failed", error_code="WORKER_RESTARTED")
            session.commit()
        for document_id in docs:
            submit(PROCESS_DOCUMENT, [document_id], None, f"recovered:{document_id}")
        if docs or stale:
            logger.warning("Recovered %d documents, failed %d stale jobs", len(docs), len(stale))
    except Exception:
        logger.exception("Inline recovery skipped")
