.PHONY: help up down build logs migrate revision shell-db shell-backend lint test fmt

help:
	@echo "Gitinho — comandos"
	@echo "  make up             — sobe stack local (docker compose)"
	@echo "  make down           — derruba stack"
	@echo "  make build          — rebuild de imagens"
	@echo "  make logs           — segue logs do backend"
	@echo "  make migrate        — alembic upgrade head"
	@echo "  make revision M=…   — nova migração (autogenerate)"
	@echo "  make shell-db       — psql"
	@echo "  make shell-backend  — bash no container backend"
	@echo "  make lint           — ruff + tsc"
	@echo "  make test           — pytest"

up:
	cd deploy && docker compose up -d --build

down:
	cd deploy && docker compose down

build:
	cd deploy && docker compose build

logs:
	cd deploy && docker compose logs -f backend

migrate:
	cd deploy && docker compose exec backend alembic upgrade head

revision:
	cd deploy && docker compose exec backend alembic revision --autogenerate -m "$(M)"

shell-db:
	cd deploy && docker compose exec db psql -U gitinho

shell-backend:
	cd deploy && docker compose exec backend bash

lint:
	cd backend && ruff check app && ruff format --check app
	cd frontend && npx tsc --noEmit

test:
	cd deploy && docker compose exec backend pytest -q

fmt:
	cd backend && ruff format app
