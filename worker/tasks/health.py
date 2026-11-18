from worker.app import celery_app


@celery_app.task(name="gapfinder.health.ping")
def ping() -> str:
    return "ok"
