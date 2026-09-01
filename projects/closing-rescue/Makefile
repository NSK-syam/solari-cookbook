.PHONY: install dev start backend frontend test lint build smoke-solari

install:
	cd backend && uv sync --all-groups
	cd frontend && npm install

dev:
	@echo "Run 'make backend' and 'make frontend' in separate terminals."

start:
	./scripts/dev.sh

backend:
	cd backend && uv run uvicorn septic_sentinel.api:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest
	cd frontend && npm test -- --run

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

build:
	cd frontend && npm run build

smoke-solari:
	cd backend && uv run python ../scripts/solari_smoke.py
