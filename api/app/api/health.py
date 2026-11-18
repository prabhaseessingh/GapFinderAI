from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response, session: Session = Depends(get_session)) -> dict[str, str]:
    """Readiness without secrets or configuration values."""
    try:
        session.execute(text("SELECT 1"))
        vector = session.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"))
        return {"status": "ok", "database": "ok", "pgvector": "ok" if vector else "missing"}
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unavailable"}
