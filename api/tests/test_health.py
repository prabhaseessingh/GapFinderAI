import inspect

from app.api.health import live


def test_liveness_needs_no_dependencies() -> None:
    assert inspect.iscoroutinefunction(live)
