.PHONY: format-check type-check unit-test integration-test migration-check
# Integration tests use TEST_DATABASE_URL (default: local Docker gapfinder_test DB).
format-check:
	python -m ruff format --check app tests alembic
	python -m ruff check app tests alembic
type-check:
	python -m mypy app
unit-test:
	python -m pytest -m "not integration"
integration-test:
	python -m pytest -m integration
migration-check:
	python -m alembic upgrade head && python -m alembic check
