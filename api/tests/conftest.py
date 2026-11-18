"""Test harness.

Integration tests run against an isolated local Postgres, never Supabase:
TEST_DATABASE_URL (default: the Docker pgvector container's `gapfinder_test` database).
The schema is rebuilt from empty with `alembic upgrade head` once per session.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://gapfinder:gapfinder@localhost:5432/gapfinder_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # must precede any app import
os.environ.setdefault("SUPABASE_JWT_ISSUER", "https://test.supabase.local/auth/v1")
os.environ.setdefault(
    "SUPABASE_JWKS_URL", "https://test.supabase.local/auth/v1/.well-known/jwks.json"
)
# Routes gate on `groq_configured`; tests swap in fake providers, so placeholders suffice (CI has no .env).
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("GROQ_MODEL", "test-groq-model")
os.environ.setdefault("GROQ_MODEL_QUALITY", "test-groq-model-quality")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.helpers import FakeStorage, _FakeJwks

API_DIR = Path(__file__).resolve().parents[1]


def _db_available() -> bool:
    try:
        with create_engine(TEST_DATABASE_URL).connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _db_available():
        return
    skip = pytest.mark.skip(reason=f"test database unavailable: {TEST_DATABASE_URL}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Any]:
    from alembic.config import Config

    from alembic import command

    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("GRANT ALL ON SCHEMA public TO public"))
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture()
def db(migrated_engine: Any) -> Iterator[Session]:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture()
def queue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str], str]]:
    sent: list[tuple[str, list[str], str]] = []

    def fake_send(_redis: str, task: str, args: list[str], _correlation: str, job_key: str) -> None:
        sent.append((task, args, job_key))

    monkeypatch.setattr("app.services.jobs.send_task", fake_send)
    return sent


@pytest.fixture()
def fair_use() -> Any:
    from app.core.fair_use import FairUse, MemoryCounter

    return FairUse(MemoryCounter())


@pytest.fixture()
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def client(
    migrated_engine: Any,
    monkeypatch: pytest.MonkeyPatch,
    storage: FakeStorage,
    queue: list[Any],
    fair_use: Any,
) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from app.api.deps import get_fair_use, get_optional_groq, get_optional_storage, get_storage
    from app.core import auth
    from app.main import app

    monkeypatch.setattr(auth, "_jwks", lambda _url: _FakeJwks())
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_optional_groq] = lambda: None
    app.dependency_overrides[get_optional_storage] = lambda: storage
    app.dependency_overrides[get_fair_use] = lambda: fair_use
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
