.PHONY: task-test worker-health-check
task-test:
	python -m pytest tests
worker-health-check:
	celery -A worker.app.celery_app inspect ping
