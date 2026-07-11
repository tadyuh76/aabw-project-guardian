from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_demo_and_live_use_separate_compose_projects_and_duckdb_volumes() -> None:
    demo = (ROOT / "scripts" / "demo-up").read_text(encoding="utf-8")
    live = (ROOT / "scripts" / "live-up").read_text(encoding="utf-8")

    assert "COMPOSE_PROJECT_NAME=guardian-voc-demo" in demo
    assert "COMPOSE_PROJECT_NAME=guardian-voc-live" in live
    assert '"${COMPOSE[@]}" -p guardian-voc-demo down --remove-orphans' in live
    assert "-p guardian-voc-demo down --volumes" not in live
    assert "VOC_WRITE_API_ENABLED=true" in live
    assert 'VOC_SCHEDULER_FULL_FLOW_ENABLED="${VOC_SCHEDULER_FULL_FLOW_ENABLED:-true}"' in live
    assert 'VOC_SCHEDULER_INTERVAL_SECONDS="${VOC_SCHEDULER_INTERVAL_SECONDS:-1800}"' in live
    assert 'VOC_LIVE_COLLECTION_SOURCE_IDS="${VOC_LIVE_COLLECTION_SOURCE_IDS:-guardian_public_social}"' in live
    assert "unset VOC_ADMIN_TOKEN" in live
    assert "export VOC_ADMIN_TOKEN=" not in demo
    assert "export AI_PROVIDER=cached" in demo
    assert "export TINYFISH_ENABLED=false" in demo
    assert "export VOC_COLLECTOR_ENRICHMENT_ENABLED=false" in demo
    assert 'DEMO_SECRETS_DIR="${RUNTIME_DIR}/demo-secrets"' in demo
    assert (
        'DEMO_VERIFIED_DIR="${RUNTIME_DIR}/demo-verified-feedback-empty"' in demo
    )
    assert 'chmod 700 "${RUNTIME_DIR}" "${DEMO_SECRETS_DIR}" "${DEMO_VERIFIED_DIR}"' in demo
    assert 'export VOC_VERIFIED_FEEDBACK_FILES=""' in demo
    assert 'export VOC_VERIFIED_FEEDBACK_HOST_DIR="${DEMO_VERIFIED_DIR}"' in demo
    assert "Demo verified-feedback directory must remain empty" in demo
    assert 'VOC_OPENAI_API_KEY_SECRET_FILE="${DEMO_OPENAI_KEY_FILE}"' in demo
    assert 'VOC_SERP_API_KEY_SECRET_FILE="${DEMO_SERP_KEY_FILE}"' in demo
    assert 'VOC_TINYFISH_API_KEY_SECRET_FILE="${DEMO_TINYFISH_KEY_FILE}"' in demo
    assert 'VOC_COLLECTOR_ENRICHMENT_ENABLED="${VOC_COLLECTOR_ENRICHMENT_ENABLED:-false}"' in live
    assert 'VOC_COLLECTOR_ENRICHMENT_MAX_ROWS="${VOC_COLLECTOR_ENRICHMENT_MAX_ROWS:-25}"' in live
    assert (
        'VOC_COLLECTOR_ENRICHMENT_CONCURRENCY="'
        '${VOC_COLLECTOR_ENRICHMENT_CONCURRENCY:-3}"' in live
    )


def test_compose_mounts_credentials_as_secrets_and_hardens_the_container() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:${VOC_PORT:-8000}:8000"' in compose
    assert "VOC_ADMIN_TOKEN_FILE: /run/secrets/admin_token" in compose
    assert "AI_API_KEY_FILE: /run/secrets/openai_api_key" in compose
    assert "SERP_API_KEY_FILE: /run/secrets/serp_api_key" in compose
    assert "TINYFISH_API_KEY_FILE: /run/secrets/tinyfish_api_key" in compose
    assert (
        'VOC_COLLECTOR_ENRICHMENT_ENABLED: "'
        '${VOC_COLLECTOR_ENRICHMENT_ENABLED:-false}"' in compose
    )
    assert (
        'VOC_VERIFIED_FEEDBACK_FILES: "'
        '${VOC_VERIFIED_FEEDBACK_FILES-/app/verified-feedback/analysis_ready.jsonl}"'
        in compose
    )
    assert 'VOC_SCHEDULER_FULL_FLOW_ENABLED: "${VOC_SCHEDULER_FULL_FLOW_ENABLED:-false}"' in compose
    assert 'VOC_SCHEDULER_INTERVAL_SECONDS: "${VOC_SCHEDULER_INTERVAL_SECONDS:-1800}"' in compose
    assert 'VOC_LIVE_COLLECTION_FETCH_LIMIT: "${VOC_LIVE_COLLECTION_FETCH_LIMIT:-25}"' in compose
    assert "\n      AI_API_KEY:" not in compose
    assert "\n      SERP_API_KEY:" not in compose
    assert "\n      TINYFISH_API_KEY:" not in compose
    assert "\n      VOC_ADMIN_TOKEN:" not in compose
    assert '${VOC_ADMIN_TOKEN_SECRET_FILE:-./.runtime/admin-token}' in compose
    assert '${VOC_OPENAI_API_KEY_SECRET_FILE:-./.runtime/openai-api-key}' in compose
    assert '${VOC_SERP_API_KEY_SECRET_FILE:-./.runtime/serp-api-key}' in compose
    assert '${VOC_TINYFISH_API_KEY_SECRET_FILE:-./.runtime/tinyfish-api-key}' in compose
    assert "read_only: true" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "no-new-privileges:true" in compose
    assert "../social-listening-crawler/data:/app/collector-output:ro" in compose
    assert (
        '"${VOC_VERIFIED_FEEDBACK_HOST_DIR:-./data/live}:'
        '/app/verified-feedback:ro"' in compose
    )


def test_generated_live_exports_are_excluded_from_git_and_docker_context() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for contents in (gitignore, dockerignore):
        assert "data/live/" in contents
        assert "data/live_data_manifest.json" in contents
