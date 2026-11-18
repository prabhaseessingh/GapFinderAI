"""Shared worker plumbing: correlation IDs, job_runs tracking, advisory locks."""

import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.request_context import bind_request_id
from app.services.jobs import mark_job
from sqlalchemy import text
from sqlalchemy.orm import Session

from worker.app import celery_app


def bind_correlation(task: Any) -> str:
    headers = getattr(task.request, "headers", None) or {}
    value = headers.get("correlation_id") if isinstance(headers, dict) else None
    return bind_request_id(value or getattr(task.request, "correlation_id", None))


@contextmanager
def advisory_lock(session: Session, key: str) -> Iterator[bool]:
    """Postgres advisory lock held on a *dedicated* connection.

    Session-level advisory locks belong to one connection. The job session commits many times
    and returns its connection to the pool, so the lock must live on its own connection and be
    released on that same connection (otherwise it leaks and blocks later jobs).
    """
    lock_id = zlib.crc32(key.encode()) & 0x7FFFFFFF
    with session.get_bind().connect() as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_id}
            ).scalar()
        )
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id}
                )
                connection.commit()


def job_running(session: Session, task_name: str, key: str) -> None:
    mark_job(session, task_name, key, "running", count_attempt=True)
    session.commit()


def job_done(
    session: Session,
    task_name: str,
    key: str,
    state: str,
    error_code: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    mark_job(session, task_name, key, state, error_code=error_code, result=result)
    session.commit()


__all__ = ["advisory_lock", "bind_correlation", "celery_app", "job_done", "job_running"]
