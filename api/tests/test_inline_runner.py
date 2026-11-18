"""TASK_RUNNER=inline: send_task runs the Celery task function on a thread, no broker involved."""

import threading
from typing import Any

import pytest

from app.core.config import get_settings
from app.services import inline_runner, jobs


def test_send_task_runs_task_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASK_RUNNER", "inline")
    get_settings.cache_clear()
    done = threading.Event()
    seen: dict[str, Any] = {}

    class FakeResult:
        result = None

        def failed(self) -> bool:
            return False

    class FakeTask:
        def apply(
            self, args: list[str], kwargs: dict[str, Any], headers: dict[str, Any]
        ) -> FakeResult:
            seen.update(args=args, kwargs=kwargs, headers=headers)
            done.set()
            return FakeResult()

    monkeypatch.setattr(inline_runner, "_task", lambda name: FakeTask())
    jobs.send_task("redis://unused", "gapfinder.x", ["a"], "corr-1", "key-1")
    assert done.wait(5)
    assert seen == {
        "args": ["a"],
        "kwargs": {"job_key": "key-1"},
        "headers": {"correlation_id": "corr-1"},
    }
    get_settings.cache_clear()


def test_celery_runner_is_default() -> None:
    get_settings.cache_clear()
    assert get_settings().task_runner == "celery"
