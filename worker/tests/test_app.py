from worker.app import celery_app


def test_worker_uses_json_only() -> None:
    assert celery_app.conf.accept_content == ["json"]


def test_worker_registers_every_pipeline_task() -> None:
    celery_app.loader.import_default_modules()
    for name in (
        "gapfinder.health.ping",
        "gapfinder.process_document",
        "gapfinder.propose_topic_map",
        "gapfinder.segment_past_paper",
        "gapfinder.map_past_papers",
        "gapfinder.generate_quiz",
        "gapfinder.evaluate_attempt",
        "gapfinder.explain",
        "gapfinder.render_audio",
        "gapfinder.render_visual",
    ):
        assert name in celery_app.tasks, name
