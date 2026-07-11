# Guardian Signal

Guardian Signal turns fragmented marketplace, Guardian-owned, customer-service,
and public social feedback into an evidence-backed operating dashboard. This
directory is the canonical application: a FastAPI service and DuckDB data layer
plus the Kanji React 19/Vite interface in `web/`.

In production it is one deployable service. The image builds the React bundle,
FastAPI serves that bundle and `/api/v1` from the same origin, and DuckDB remains
the canonical store. The sibling `../social-listening-crawler` is an upstream
data producer only. Its output directory may be mounted read-only for ingestion;
the monolith does not write to or require a second crawler HTTP service.

The repository also includes a deterministic, visibly synthetic demo with no
paid API dependency. Synthetic records appear only in explicit demo mode. The
live path uses the same ingestion, classification, metric, and publication
pipeline.

## Source snapshot and provenance

The three supplied project directories are local source snapshots and do not
contain `.git` metadata. Their remotes, branches, commit hashes, and authorship
cannot be verified from this workspace. “Kanji frontend” identifies the UI
snapshot supplied for this integration; it is not a claim of Git provenance.
Record the upstream repository URL and immutable commit for each snapshot before
a release that requires reproducible provenance.

## Run the judge demo

Requirements: Docker with Compose.

```bash
./scripts/demo-up
```

Open <http://127.0.0.1:8000>. The script creates a fresh local admin token in
`.runtime/admin-token` with mode `0600`; it never prints the token. To demonstrate
a proactive update, run:

```bash
./scripts/demo-increment
```

That command submits one authenticated import, receives one pipeline run ID,
and polls it until the refreshed dashboard is published.

`demo-up` resets its Compose data volume by default so every presentation starts
from the same Watch state. Set `VOC_DEMO_RESET=false` only when you intentionally
want to preserve the current local demo data.

## Local development

Requirements: Python 3.12, [`uv`](https://docs.astral.sh/uv/), and Node.js 22.
Run the backend from the repository root on port 8000:

```bash
uv sync --extra dev
uv run python fixtures/generate_demo.py
uv run python -m guardian_voc seed-demo --reset
uv run python -m guardian_voc serve --reload --host 127.0.0.1 --port 8000
```

In another terminal, run the React development server:

```bash
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. The Vite server proxies relative `/api` requests to
<http://127.0.0.1:8000>, so the browser uses the same API paths as production.
Do not set `VITE_API_BASE_URL` for this normal workflow. FastAPI itself exposes
OpenAPI at <http://127.0.0.1:8000/api/docs>.

Copy `.env.example` to `.env` only when you need overrides. Secrets are blank by
default, write APIs are disabled by default, and `.env` is ignored and excluded
from the container build. DuckDB is a single-writer store: use one backend
process and one Uvicorn worker.

## Containerized monolith

```bash
./scripts/demo-up       # isolated cached demo, including local secret files
# or: ./scripts/live-up # live collector-to-insight deployment
curl --fail http://127.0.0.1:8000/api/v1/ready
```

Open <http://127.0.0.1:8000>. The multi-stage Docker build compiles `web/` and
copies its static output into the Python image. FastAPI serves both the UI and
API, so no production CORS configuration, separate frontend container, or
second web server is required. Compose runs one `guardian-voc` application
service with one persistent DuckDB volume. It can additionally mount
`../social-listening-crawler/data` at `/app/collector-output:ro`; that mount is
an ingestion boundary, not another application tier.

The Compose file always declares four file secrets. If you invoke
`docker compose up` directly instead of using the mode-specific scripts, first
provide the files selected by `VOC_ADMIN_TOKEN_SECRET_FILE`,
`VOC_OPENAI_API_KEY_SECRET_FILE`, `VOC_SERP_API_KEY_SECRET_FILE`, and
`VOC_TINYFISH_API_KEY_SECRET_FILE`. Provider-key files may be empty only for the
cached demo path. The wrapper scripts create or validate the appropriate files
without placing secret values in the image or container environment.

Use `/api/v1/live` for process liveness and `/api/v1/ready` for DuckDB and
scheduler readiness. Keep one application replica while DuckDB is the store;
move to a concurrent database before adding workers or replicas.

## Truthful dashboard states

The Kanji Command Center reads `GET /api/v1/dashboard` and renders the state the
backend actually returns:

- `ready`: render the returned aggregates and records.
- `partial`: required current, baseline, product, or analysis coverage is
  missing; render only the available data with the limitation visible. An
  isolated excluded record that does not block the requested metrics remains a
  visible backend note on an otherwise `ready` response. Missing coverage is
  never extrapolated.
- `empty`: show an empty state and zeros or unavailable values as supplied; do
  not populate charts or KPIs with design fixtures.

An HTTP or network failure is an error, not an empty dataset. The production UI
does not silently fall back to mock dashboard data. Seeded synthetic data is
allowed only when `VOC_DEMO_MODE=true` and remains visibly identified as demo
data.

## Run the live collector-to-insight pipeline

The live deployment reads only the allowlisted `SERP_API_KEY`,
`TINY_FISH_API_KEY` (or `TINYFISH_API_KEY`), and `OPENAI_API_KEY` (or
`AI_API_KEY`) values from the sibling crawler `.env` or exported environment.
It copies them into ignored mode-`0600` runtime secret files; credentials are
not placed in the image or container environment.

```bash
./scripts/live-up
```

Before the live service starts, `live-up` performs a fail-closed, deploy-time
handoff from the clean host `data/guardian_voc.duckdb` into the live named
volume. The service is stopped for the comparison. A missing or empty live
database is seeded; an equal feedback-ID set is preserved byte-for-byte; and
the live database is atomically replaced only when the host contains every
live feedback ID plus additional feedback. A live database that already
contains additional scheduled rows is preserved so deploys cannot roll back
near-real-time collection. A host `.wal` file, an invalid
database, divergent ID sets, or incompatible schema histories refuses the
deploy and leaves the live database unchanged. On refusal, the previously
stopped live container is restarted before `live-up` returns a nonzero status.
Handoff output contains only the action and record counts—never feedback IDs,
customer text, URLs, or secrets.

This handoff seeds the verified, strict `prefetch-data` output at deploy time.
It does not turn search snippets into feedback and is separate from the
30-minute collector/inbox ingestion loop.

Compose mounts the sibling crawler `data/` directory read-only. The in-process
scheduler watches `guardian_voc_vi_12m.customer-candidates.vi.jsonl`, takes a
stable bounded snapshot, preserves its brand/query provenance, and imports a
changed content fingerprint exactly once. Canonical URL deduplication provides
a second idempotency layer. The same single `GuardianService` then classifies,
rebuilds metrics, and publishes the latest three decision cards. It also drains
the configured inbox every 30 minutes by default.

Search-result titles and snippets remain discovery evidence. Generic page
enrichment is disabled by default because a fetched login shell or official
campaign is not customer voice. The production `prefetch-data` path runs the
strict page-feedback extractor first, excludes seller copy and blocked pages,
then publishes only grounded customer-authored units. Runtime and source health
still expose discovery and verification gaps without URLs, provider error text,
keys, or customer content.

The live deployment enables `VOC_SCHEDULER_FULL_FLOW_ENABLED=true`. Every 30
minutes, one non-overlapping single-writer cycle runs SerpAPI discovery for
Guardian public social sources, TinyFish Fetch for up to 25 new pages, strict
OpenAI page-feedback extraction for up to 25 pages, current-model
classification, deduplication, metric rebuilding, and publication. The default
two-day overlapping date window avoids a midnight gap; stable discovery,
fetch, extraction, and feedback identities prevent duplicates. Set
`VOC_LIVE_COLLECTION_SOURCE_IDS` or the per-cycle limits explicitly when quota
requirements change. The older generic keyword crawl remains off. Failed
cycles use exponential backoff capped by
`VOC_SCHEDULER_MAX_BACKOFF_SECONDS`; the last run and next retry are exposed at
`/api/v1/health`, with probes at `/api/v1/live` and `/api/v1/ready`.

The live classifier defaults to the official `https://api.openai.com/v1` base
URL and `gpt-5.4-mini`. The deterministic demo remains offline because
`AI_PROVIDER=cached` and TinyFish are disabled by default.

## Import official and marketplace review CSVs

CSV writes are fail-closed and disabled by default. Generate a strong token in
an ignored, owner-readable file and enable the write API explicitly:

```bash
umask 077
openssl rand -hex 32 > .runtime/admin-token
```

For local development, set these values in the ignored `.env` file:

```dotenv
VOC_WRITE_API_ENABLED=true
VOC_ADMIN_TOKEN_FILE=.runtime/admin-token
```

For Docker, set `VOC_WRITE_API_ENABLED=true` and leave
`VOC_ADMIN_TOKEN_FILE=/run/secrets/admin_token`; Compose reads the host file
selected by `VOC_ADMIN_TOKEN_SECRET_FILE` (default `.runtime/admin-token`) as a
mounted secret. Do not put the token in source control, a frontend environment
variable, a URL, or application logs.

Open the expandable **Import reviews** operator panel on the main Command
Center. Select Guardian official page, TikTok Shop, Shopee, Lazada, or GrabMart;
choose the authorized CSV export; paste the admin token; preview; then import.
`GET /api/v1/imports/config` is safe to call without a token. Preview and commit
are privileged import operations and require the token in `X-Admin-Token`;
preview validates without writing to DuckDB. The browser keeps the token in
component memory only, never browser storage, and clears it only after the
backend reports `completed`. It retains the token and preview after a `partial`
or `failed` result so the operator can inspect or retry.

Commit returns `202 Accepted` after persisting a queued pipeline-run status row
in DuckDB. FastAPI retains the upload bytes in the current process and runs the
pipeline in an in-process background task, serialized by the application's
single-writer lock. The browser polls `GET /api/v1/runs/{run_id}` until
`completed`, `partial`, or `failed`, then refetches the dashboard after
completed or partial publication. If only polling is interrupted, the same run
ID can be queried again without re-uploading.

This is not a durable job queue: a backend restart after acceptance can leave a
queued status row without recoverable upload bytes, in which case the operator
must submit the file again.

Exports should include a review ID, review text, and review date. Rating,
product, category, branch/store, and product/review URL are optional. Common
English and Vietnamese marketplace headers are resolved automatically. The
server enforces configured byte and row limits; the preview masks personal data
and reports malformed rows. Commit filters to Vietnamese, redacts PII,
persists malformed rows to quarantine,
deduplicates stable review IDs/content, classifies only new feedback, rebuilds
the dashboard, and reports inserted, skipped, and failed counts. Reimporting the
same export is safe. Keep write APIs disabled when operators do not need them.

## Build the live Vietnamese data layer

The auditable live flow is SerpAPI discovery → TinyFish Fetch → strict page
feedback extraction → local Vietnamese/brand gates → OpenAI structured
classification → DuckDB. Search titles and snippets stay in the discovery
audit and can never become customer feedback.

With `SERP_API_KEY`, `TINY_FISH_API_KEY`, and `OPENAI_API_KEY` exported:

```bash
AI_PROVIDER=openai_compatible \
AI_MODEL=gpt-5.4-mini \
VOC_DEMO_MODE=false \
python -m guardian_voc prefetch-data \
  --period-start 2025-07-12 \
  --period-end 2026-07-11

python -m guardian_voc data-manifest
```

The versioned registry covers Guardian web, both verified Shopee shops,
Lazada, TikTok Shop, GrabMart, Facebook, Instagram, Threads, TikTok, YouTube,
and other allowlisted public-social results. SerpAPI is the only search
provider. TinyFish reads only registry-permitted public pages and revalidates
host, redirect, blocked-path, and permission policy immediately before every
request. Only stable one-post social URL shapes can enter extraction; hidden
comments, profile/feed pages, login walls, and pages without durable customer
unit identity remain enrichment or audit evidence.

Complete marketplace review acquisition uses seller-scoped APIs or authorized
exports, never search snippets or automated marketplace UI scraping. For
Guardian-owned seller credentials:

```bash
python -m guardian_voc ingest-shopee-reviews \
  --owned-shop-authorized \
  --all-items

python -m guardian_voc ingest-lazada-reviews \
  --owned-shop-authorized \
  --all-items
```

`--all-items` first enumerates the complete seller catalog through the
authorized product API; alternatively, repeat `--item-id` for a controlled
subset. The commands paginate to exhaustion,
filter to Vietnamese and the 365-day window, deduplicate review IDs, classify
through the normal pipeline, and emit secret-free total/cursor reconciliation.
Shopee/Lazada credentials are read only from the documented environment
variables. TikTok Shop, GrabMart, and Guardian-owned web reviews use their
authorized exports through the matching import profiles until an approved
seller API is configured. Hasaki and Watsons public export profiles are
available for matched benchmarking; they are never accessed with Guardian
seller credentials.

`data/live_data_manifest.json` is the source of truth for readiness. A source
is not labelled complete until authorized pagination is exhausted and reported
totals reconcile to unique review IDs. TinyFish success alone is not evidence
of complete marketplace review coverage. The cumulative, PII-redacted
item/classification join is materialized at `data/live/analysis_ready.jsonl`;
DuckDB remains the canonical store.

## Verification

```bash
uv run pytest
cd web && npm test -- --run && npm run build
docker compose build
```

Compatibility coverage for the preserved `social_crawler` package remains in
the test suite. The production ingestion boundary is still the sibling
`social-listening-crawler` output mounted read-only; its source tree is never
modified by this application.

See [the demo script](docs/DEMO_SCRIPT.md), [architecture](docs/ARCHITECTURE.md),
[data dictionary](docs/DATA_DICTIONARY.md), [taxonomy](docs/TAXONOMY.md),
[evaluation](docs/EVALUATION.md), and [limitations](docs/LIMITATIONS.md).
