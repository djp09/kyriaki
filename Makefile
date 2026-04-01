.PHONY: up down dev build logs test db-shell db-migrate clean

up:
	docker compose up -d

down:
	docker compose down

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

build:
	docker compose build

logs:
	docker compose logs -f

test:
	cd backend && python -m pytest -v --tb=short

test-docker:
	docker compose exec backend python -m pytest -v --tb=short

db-shell:
	docker compose exec db psql -U kyriaki -d kyriaki

db-migrate:
	cd backend && alembic upgrade head

clean:
	docker compose down -v
