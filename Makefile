.PHONY: install lock test build verify dev-api dev-web deploy backup logs

install:
	uv sync --extra dev
	cd web && npm ci

lock:
	uv lock
	uv export --frozen --no-dev --no-emit-project --output-file requirements.lock

test:
	uv run pytest
	cd web && npm test -- --run

build:
	cd web && npm run build
	docker compose build

verify: test build
	docker compose config --quiet

dev-api:
	uv run python -m guardian_voc serve --reload --host 127.0.0.1 --port 8000

dev-web:
	cd web && npm run dev

deploy:
	./scripts/prod-up

backup:
	./scripts/backup

logs:
	docker compose logs --follow app
