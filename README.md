# Guardian Signal

Guardian Signal consolidates Guardian product reviews from Shopee, Lazada,
TikTok Shop, GrabMart, Guardian-owned channels, and authorized seller exports.
Managers upload CSV/XLSX exports in one simple UI; GPT identifies the relevant
columns from the header and first five rows, while deterministic backend code
validates, redacts, deduplicates, stores, and analyzes the complete file.

This is one repository and one production service. There is no required sibling
repository or separate frontend deployment.

The app also supports a serverless Vercel deployment backed by PostgreSQL. Set
`DATABASE_URL` (the Neon integration injects it automatically); local runs keep
using `VOC_DB_PATH` and DuckDB. To copy an existing local database, run
`scripts/migrate_duckdb_to_postgres.py --replace` with
`DATABASE_URL_UNPOOLED` set. The command verifies every copied table with row
counts and content checksums before it succeeds.

## Repository layout

```text
guardian-signal/
├── guardian_voc/       FastAPI API, ingestion, analytics, and DuckDB access
├── social_crawler/     Internal public-source acquisition library
├── web/                React/Vite frontend
├── tests/              Backend and integration tests
├── fixtures/           Synthetic demo data and import samples
├── scripts/            Deployment, demo, backup, and maintenance commands
├── Dockerfile          Multi-stage frontend + backend production image
├── requirements.lock   Frozen production Python dependencies
└── docker-compose.yml  Single-service VPS deployment
```

The Docker build compiles `web/` and copies the static bundle into the FastAPI
image. FastAPI serves both the UI and `/api/v1` from the same origin. DuckDB is
stored in one persistent Docker volume, so run exactly one application replica.

## Production deployment on a VPS

Requirements:

- Docker Engine with the Compose plugin
- A domain pointed at the VPS
- Caddy, Nginx, or another TLS reverse proxy

Clone the repository and configure it:

```bash
git clone https://github.com/tadyuh76/aabw-project-guardian.git guardian-signal
cd guardian-signal
cp .env.example .env
chmod 600 .env
```

At minimum, set `OPENAI_API_KEY` in `.env`. Then start the complete application:

```bash
./scripts/prod-up
```

The script:

1. creates a strong admin access key in `.runtime/admin-token`;
2. converts provider keys into Docker secret files protected by a mode-`0700`
   parent directory and readable by the non-root container group;
3. validates the Compose configuration;
4. builds and starts the single hardened container; and
5. waits for `/api/v1/ready` before reporting success.

The application listens only on `127.0.0.1:8000` by default. Put HTTPS in front
of it. A minimal Caddy configuration is:

```caddyfile
reviews.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Do not expose port 8000 directly to the internet. Keep `.env` and `.runtime/`
out of backups shared with other people; both are ignored by Git and Docker.

### Updating

```bash
git pull --ff-only
./scripts/prod-up
```

### GitHub CI/CD

Every pull request runs release checks: production dependency export, frontend
build, Compose validation, and production-image build. Production is deployed
to Vercel from this repository's `vercel.json`; the former automatic VPS deploy
job is intentionally disabled. Review imports remain enabled against PostgreSQL,
while admin writes and social collection stay disabled in the Vercel entrypoint.
The social collection GitHub Actions workflow is also disabled.

### Backups

Create a consistent, offline DuckDB backup:

```bash
./scripts/backup
```

The command briefly stops the single database writer, archives the persistent
volume into `backups/`, restarts the service, and writes the backup with mode
`0600`. Copy these archives to encrypted off-site storage.

### Operations

```bash
docker compose ps
docker compose logs -f app
docker compose restart app
curl --fail http://127.0.0.1:8000/api/v1/live
curl --fail http://127.0.0.1:8000/api/v1/ready
```

The container runs as a non-root user with a read-only filesystem, dropped Linux
capabilities, `no-new-privileges`, bounded temporary storage, a PID limit, log
rotation, a health check, and graceful shutdown time for the DuckDB writer.

## Review import workflow

1. Open **Import reviews**.
2. Choose the marketplace.
3. Select the authorized CSV or XLSX export.
4. Enter the admin access key from `.runtime/admin-token`.
5. Click **Import reviews**.

Guardian performs schema detection and commit behind that single action. Only
the headers and first five rows are sent to the configured OpenAI model. Model
output is constrained to exact uploaded header names and revalidated before
use. Full rows are processed by application code, reviewer identifiers are
hashed, preview/error samples are masked, and SHA-256 file history prevents an
identical successful export from being imported again.

Synthetic test exports are in `fixtures/import_samples/`.

## Optional scheduled collection

Uploaded seller exports are the recommended complete-review source. Optional
public-source discovery can run inside the same application process—there is no
second crawler service.

To enable the scheduled live pipeline, also configure `SERP_API_KEY` and
`TINYFISH_API_KEY`, then set:

```dotenv
VOC_SCHEDULER_ENABLED=true
VOC_SCHEDULER_FULL_FLOW_ENABLED=true
TINYFISH_ENABLED=true
VOC_LIVE_COLLECTION_SOURCE_IDS=guardian_public_social,hasaki_public_social,watsons_public_social
```

These registry sources cover the verified public-social discovery scopes for
Guardian, Hasaki, and Watsons. Search results remain discovery evidence only;
only fetched public pages that pass strict extraction and provenance checks are
published as feedback.

Scheduled work and imports share the same serialized writer lock. Keep one app
container while DuckDB is the database.

## Local development

Requirements: Python 3.12, `uv`, and Node.js 22.

Backend:

```bash
uv sync --extra dev
uv run python -m guardian_voc serve --reload --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```bash
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. Vite proxies `/api` to the backend.

For the deterministic offline demo:

```bash
./scripts/demo-up
```

## Verification

```bash
uv run pytest
cd web && npm test -- --run && npm run build
docker compose config --quiet
docker compose build
```

See [architecture](docs/ARCHITECTURE.md),
[data dictionary](docs/DATA_DICTIONARY.md),
[taxonomy](docs/TAXONOMY.md), and [limitations](docs/LIMITATIONS.md).
