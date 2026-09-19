.PHONY: dev install css docker build stop logs shell test lint db-export db-export-file db-import setup help

HOST ?= 127.0.0.1
PORT ?= 8000

dev: css
	uv run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

install:
	uv sync
	npm install

# Compiles Tailwind CSS to static/css/app.css. Needed on the host even for
# Docker dev: docker-compose.dev.yml bind-mounts the whole repo over /app,
# which would otherwise shadow the image's own build-time compiled CSS with
# a host static/ that doesn't have it.
css:
	npm run build:css

docker: css
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

build: css
	docker compose -f docker-compose.yml -f docker-compose.dev.yml build

stop:
	docker compose down

logs:
	docker compose logs -f

shell:
	docker compose exec statuspage bash

test:
	uv run pytest tests/

lint:
	uv run ruff check .

db-export:
	@echo "Exporting database to db_export.json..."
	uv run python scripts/db_export.py

db-export-file:
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make db-export-file FILE=output.json"; \
		exit 1; \
	fi
	uv run python scripts/db_export.py $(FILE)

db-import:
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make db-import FILE=input.json"; \
		exit 1; \
	fi
	uv run python scripts/db_import.py $(FILE)

setup:
	@echo "Windows WSL2 setup:"
	@echo "  PowerShell: .\setup-wsl2.ps1"
	@echo "  Or double-click: setup-wsl2.bat"
	@echo ""
	@echo "For options: .\setup-wsl2.ps1 -Help"

help:
	@echo "Available commands:"
	@echo "  make dev            - Start dev server directly via uv (http://$(HOST):$(PORT))"
	@echo "  make install        - Install dependencies via uv sync + npm install"
	@echo "  make css            - Compile Tailwind CSS to static/css/app.css"
	@echo "  make docker         - Build and start via Docker Compose"
	@echo "  make build          - Rebuild Docker image without starting"
	@echo "  make stop           - Stop and remove Docker containers"
	@echo "  make logs           - Follow Docker container logs"
	@echo "  make shell          - Open shell in running container"
	@echo "  make test           - Run test suite via uv"
	@echo "  make lint           - Run ruff linter"
	@echo "  make db-export      - Export database to db_export.json"
	@echo "  make db-export-file FILE=output.json - Export to custom file"
	@echo "  make db-import FILE=input.json - Import from file"
	@echo "  make setup          - WSL2 setup info (Windows only)"
