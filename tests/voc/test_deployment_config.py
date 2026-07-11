from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_has_one_canonical_deployment_path() -> None:
    production = (ROOT / "scripts" / "prod-up").read_text(encoding="utf-8")
    deployment = (ROOT / "scripts" / "deploy-server").read_text(encoding="utf-8")
    live = (ROOT / "scripts" / "live-up").read_text(encoding="utf-8")

    assert production.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "docker compose config --quiet" in production
    assert "docker compose up --build --detach --remove-orphans" in production
    assert 'runtime / "admin-token"' in production
    assert "secrets.token_urlsafe(32)" in production
    assert "OPENAI_API_KEY is required" in production
    assert 'exec "${ROOT_DIR}/scripts/prod-up"' in live
    assert "social-listening-crawler" not in production
    assert "social-listening-crawler" not in live
    assert "docker compose up --build --detach --remove-orphans" in deployment
    assert "chown 0:1000" in deployment
    assert "/api/v1/ready" in deployment


def test_main_ci_deploys_only_after_tests_pass() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "needs: test" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "environment: production" in workflow
    assert "DEPLOY_SSH_PRIVATE_KEY" in workflow
    assert "scripts/deploy-server" in workflow
    assert "--exclude='.env'" in workflow
    assert "--exclude='.runtime/'" in workflow


def test_production_social_collection_is_bounded_and_secret_safe() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "production-social-collection.yml"
    ).read_text(encoding="utf-8")
    configuration = (ROOT / "scripts" / "configure-production-social").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "secrets.SERP_API_KEY" in workflow
    assert "pages_per_query\\\":3" in workflow
    assert "fetch_limit\\\":500" in workflow
    assert "lookback_days\\\":30" in workflow
    assert "last-social-collection.json" in workflow
    assert "guardian_public_social,hasaki_public_social,watsons_public_social" in configuration
    assert "SERP_API_KEY" not in configuration


def test_production_classification_retry_is_protected_and_has_no_crawl() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "production-reclassify.yml"
    ).read_text(encoding="utf-8")

    assert "environment: production" in workflow
    assert "/api/v1/pipeline/run" in workflow
    assert "X-Admin-Token" in workflow
    assert "ServerAliveInterval=30" in workflow
    assert "live-collections" not in workflow
    assert "SERP_API_KEY" not in workflow


def test_compose_is_one_hardened_service_without_sibling_mounts() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "services:\n  app:" in compose
    assert compose.count("\n  app:") == 1
    assert '"127.0.0.1:${GUARDIAN_PORT:-8000}:8000"' in compose
    assert "VOC_DEMO_MODE: \"${VOC_DEMO_MODE:-false}\"" in compose
    assert (
        "guardian_public_social,hasaki_public_social,watsons_public_social"
        in compose
    )
    assert "VOC_ADMIN_TOKEN_FILE: /run/secrets/admin_token" in compose
    assert "AI_API_KEY_FILE: /run/secrets/openai_api_key" in compose
    assert "SERP_API_KEY_FILE: /run/secrets/serp_api_key" in compose
    assert "TINYFISH_API_KEY_FILE: /run/secrets/tinyfish_api_key" in compose
    assert "\n      AI_API_KEY:" not in compose
    assert "\n      SERP_API_KEY:" not in compose
    assert "\n      TINYFISH_API_KEY:" not in compose
    assert "\n      VOC_ADMIN_TOKEN:" not in compose
    assert "guardian_data:/app/data" in compose
    assert "../" not in compose
    assert "collector-output" not in compose
    assert "verified-feedback" not in compose
    assert "read_only: true" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "no-new-privileges:true" in compose
    assert "pids_limit: 256" in compose
    assert 'max-size: "10m"' in compose


def test_docker_build_produces_one_non_root_frontend_plus_api_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:22-alpine AS web-build" in dockerfile
    assert "FROM python:3.12-slim AS runtime" in dockerfile
    assert "COPY --from=web-build /build/web/dist ./web/dist" in dockerfile
    assert "USER guardian" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["python", "-m", "guardian_voc", "serve"' in dockerfile


def test_generated_runtime_data_is_excluded_from_git_and_docker_context() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for contents in (gitignore, dockerignore):
        assert ".runtime" in contents
        assert "data/live/" in contents
        assert "data/live_data_manifest.json" in contents
    assert "web/node_modules" in dockerignore
    assert "web/dist" in dockerignore
    assert "tests" in dockerignore
