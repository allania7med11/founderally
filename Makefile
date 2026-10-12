API_HEALTH = http://localhost:8000/api/health
TEMPORAL_UI = http://localhost:8080

.PHONY: up migrate makemigrations check-migrations down test test-stack

up:
	docker compose up -d --build
	@for url in $(API_HEALTH) $(TEMPORAL_UI); do \
	  for i in $$(seq 1 90); do curl -fs $$url >/dev/null 2>&1 && break; sleep 1; done; \
	  curl -fs $$url >/dev/null 2>&1 || { echo "not up after 90 s: $$url"; exit 1; }; \
	done
	@echo "up: API on :8000, Temporal UI on :8080"

migrate:
	docker compose run --rm --build api alembic upgrade head

# Diffs models.py against the migrated database and writes the file. On the host, so the file lands in the repo.
#   make makemigrations m="briefs, research_passes, competitors" rev=0002
makemigrations:
	cd backend && DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://founderally:founderally@localhost:5432/founderally} \
	  TEMPORAL_ADDRESS=$${TEMPORAL_ADDRESS:-localhost:7233} \
	  uv run alembic revision --autogenerate -m "$(m)" $(if $(rev),--rev-id $(rev))

down:
	docker compose down --volumes

test:
	cd backend && uv run pytest -m "not stack"

# Models and database agree, and the last migration goes down and up again.
check-migrations:
	docker compose run --rm --build api sh -c "alembic check && alembic downgrade -1 && alembic upgrade head && alembic check"

test-stack: check-migrations
	cd backend && uv run pytest -m stack
