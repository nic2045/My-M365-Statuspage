.PHONY: dev install docker build stop logs shell test lint help

HOST ?= 127.0.0.1
PORT ?= 8000

dev:
	uv run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

install:
	uv sync

docker:
	docker compose up --build

build:
	docker compose build

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

help:
	@echo "Available commands:"
	@echo "  make dev     - Start dev server directly via uv (http://$(HOST):$(PORT))"
	@echo "  make install - Install dependencies via uv sync"
	@echo "  make docker  - Build and start via Docker Compose"
	@echo "  make build   - Rebuild Docker image without starting"
	@echo "  make stop    - Stop and remove Docker containers"
	@echo "  make logs    - Follow Docker container logs"
	@echo "  make shell   - Open shell in running container"
	@echo "  make test    - Run test suite via uv"
	@echo "  make lint    - Run ruff linter"
