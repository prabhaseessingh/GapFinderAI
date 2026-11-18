import os

from celery import Celery

celery_app = Celery(
    "gapfinder", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    imports=(
        "tasks.health",
        "tasks.ingest",
        "tasks.map",
        "tasks.quiz",
        "tasks.evaluate",
        "tasks.explain",
    ),
)
