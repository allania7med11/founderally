API_HEALTH = http://localhost:8000/api/health
TEMPORAL_UI = http://localhost:8080

.PHONY: up down test

up:
	docker compose up -d --build
	@for url in $(API_HEALTH) $(TEMPORAL_UI); do \
	  for i in $$(seq 1 90); do curl -fs $$url >/dev/null 2>&1 && break; sleep 1; done; \
	  curl -fs $$url >/dev/null 2>&1 || { echo "not up after 90 s: $$url"; exit 1; }; \
	done
	@echo "up: API on :8000, Temporal UI on :8080"

down:
	docker compose down --volumes

test:
	cd backend && uv run pytest
