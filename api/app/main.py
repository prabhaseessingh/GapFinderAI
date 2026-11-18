import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.diagnosis import router as diagnosis_router
from app.api.documents import router as documents_router
from app.api.explain import router as explain_router
from app.api.health import router as health_router
from app.api.profile import router as profile_router
from app.api.quizzes import router as quizzes_router
from app.api.topics import router as topics_router
from app.api.workspaces import router as workspaces_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.request_context import request_id_middleware
from app.db import models as _models  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if get_settings().task_runner == "inline":
        from app.services.inline_runner import recover_after_restart

        recover_after_restart()
    yield


app = FastAPI(title="GapFinder AI API", version="0.2.0", lifespan=lifespan)
app.middleware("http")(request_id_middleware)
install_error_handlers(app)
app.include_router(health_router)
app.include_router(profile_router)
app.include_router(workspaces_router)
app.include_router(documents_router)
app.include_router(topics_router)
app.include_router(quizzes_router)
app.include_router(diagnosis_router)
app.include_router(explain_router)
