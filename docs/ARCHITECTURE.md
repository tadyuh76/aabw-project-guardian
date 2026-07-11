# Architecture

## Deployment boundary

Guardian Signal is a single-repository monolith with a clear internal split:

- `web/` owns the React/Vite presentation layer;
- `guardian_voc/api/` owns HTTP and static-file delivery;
- `guardian_voc/connectors/` owns seller exports and authorized sources;
- `guardian_voc/pipeline/` owns validation, redaction, normalization, and dedupe;
- `guardian_voc/analytics/` and `guardian_voc/insights/` own derived decisions;
- DuckDB is the canonical application store.

The frontend is not a separate production service. Node compiles it in the
first Docker stage; the final non-root Python image serves the resulting static
assets and `/api/v1` from the same origin.

```text
CSV/XLSX upload ─┐
seller API ──────┼─> validate → redact → deduplicate → classify ─> DuckDB
public sources ──┘                                              │
                                                                v
                                                       FastAPI + React
                                                          one origin
```

Local development uses separate FastAPI and Vite processes for hot reload.
Production uses one container, one Uvicorn worker, and one persistent volume.

## Why one process

DuckDB is an embedded single-writer database. GuardianService serializes
imports, scheduled collection, classification, metric rebuilding, and
publication with one writer lock. Running multiple application replicas or
Uvicorn workers would violate this design. Move to PostgreSQL and a durable job
queue before horizontally scaling.

## Import trust boundary

The import UI submits one operator action, but the backend keeps detection and
commit as separate trust boundaries:

1. the server reads only the spreadsheet header and first five rows;
2. the configured OpenAI model returns a strict column-mapping object;
3. every returned value must exactly match an uploaded header;
4. deterministic code parses and validates the full file;
5. reviewer identity is hashed and preview/error content is masked;
6. SHA-256 file history blocks identical successful imports; and
7. stable review IDs and content hashes deduplicate overlapping newer exports.

Import endpoints require `X-Admin-Token`. Production reads this value from a
mounted Docker secret. The browser holds it only in React component memory and
clears it after completion.

The pipeline run status is durable, but uploaded bytes are retained only by the
current process. A crash between `202 Accepted` and completion requires the
operator to submit the file again. A durable queue is the appropriate future
upgrade if imports become large or business-critical enough to require restart
recovery.

## Data truth

The backend owns all business calculations and returns one explicit state:

- `ready`: requested data and denominators are available;
- `partial`: available results are usable but required coverage is incomplete;
- `empty`: the query succeeded but has no usable records; or
- HTTP failure: the UI renders an error and never substitutes demo fixtures.

Synthetic feedback is permitted only when `VOC_DEMO_MODE=true` and remains
visibly identified.

## Collection

Authorized seller exports are the primary source for complete marketplace
reviews. Optional SerpAPI/TinyFish public discovery is an internal library and
scheduled task, not a separate service or repository. Search snippets remain
discovery evidence and never become feedback without grounded page extraction.

## Runtime security

Production Compose:

- binds the app to loopback for a TLS reverse proxy;
- runs as a non-root user;
- mounts credentials as files rather than environment values;
- uses a read-only container filesystem and a dedicated data volume;
- drops Linux capabilities and enables `no-new-privileges`;
- bounds PIDs, temporary storage, and Docker logs;
- exposes liveness and readiness probes; and
- allows a three-minute graceful shutdown for the single writer.

`/api/v1/health`, `/api/v1/live`, and `/api/v1/ready` must never expose tokens,
customer text, private URLs, or provider response bodies.
