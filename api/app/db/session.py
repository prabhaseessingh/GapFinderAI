from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
# Supabase's free session pooler allows 15 clients in total across every process, so each
# process keeps a small pool (DB_POOL_SIZE / DB_MAX_OVERFLOW) and recycles idle connections.
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=300,
)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
