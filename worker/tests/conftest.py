import os
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://gapfinder:gapfinder@localhost:5432/gapfinder_test",
)

import pytest
from sqlalchemy import create_engine, text

API_DIR = Path(__file__).resolve().parents[2] / "api"


def _db_available() -> bool:
    try:
        with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def migrated() -> None:
    if not _db_available():
        pytest.skip("test database unavailable")
    from alembic import command
    from alembic.config import Config

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(config, "head")
