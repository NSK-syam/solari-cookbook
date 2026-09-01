.PHONY: install dev start backend frontend test test-e2e lint build secret-scan audit smoke-deploy smoke-solari verify

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

test-e2e:
	cd frontend && npm run test:e2e

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

build:
	cd frontend && npm run build

secret-scan:
	python3 scripts/secret_scan.py

audit:
	cd backend && uv run --with pip-audit pip-audit
	cd frontend && npm audit --audit-level=high

smoke-deploy: build
	cd backend && uv run python ../scripts/deployment_smoke.py

smoke-solari:
	cd backend && uv run python ../scripts/solari_smoke.py

verify: lint test build secret-scan
