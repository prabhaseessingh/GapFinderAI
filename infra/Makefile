.PHONY: local-up local-down worker-health-check seed-demo reset-test-data
local-up:
	docker compose -f docker-compose.yml --profile worker up -d --build
local-down:
	docker compose -f docker-compose.yml --profile worker down
worker-health-check:
	docker compose -f docker-compose.yml exec worker celery -A worker.app.celery_app inspect ping
seed-demo:
	cd ../api && ../.venv/Scripts/python scripts/seed_demo.py --api http://localhost:8002
reset-test-data:
	docker compose -f docker-compose.yml exec postgres psql -U gapfinder -d postgres -c "DROP DATABASE IF EXISTS gapfinder_test" -c "CREATE DATABASE gapfinder_test"
