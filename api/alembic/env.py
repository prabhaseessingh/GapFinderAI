from typing import Any

from sqlalchemy import engine_from_config, pool
from sqlalchemy.dialects.postgresql.base import ischema_names

from alembic import context
from app.core.config import get_settings
from app.db import models as _models
from app.db.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata
ischema_names["vector"] = _models.Vector  # let reflection recognise pgvector columns

# Indexes that SQLAlchemy cannot express (expression GIN / partial HNSW) are owned by migrations.
MIGRATION_OWNED_INDEXES = {"chunks_text_search_idx", "chunks_embedding_cosine_idx"}


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, _compare: Any) -> bool:
    if type_ == "table" and name == "alembic_version":
        return False
    # profiles.id -> auth.users(id) is owned by Supabase Auth, not by the ORM.
    referred = getattr(obj, "referred_table", None) if type_ == "foreign_key_constraint" else None
    if referred is not None and referred.schema == "auth":
        return False
    if type_ == "index" and name in MIGRATION_OWNED_INDEXES:
        return False
    schema = getattr(obj, "schema", None)
    return schema in (None, "public")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
