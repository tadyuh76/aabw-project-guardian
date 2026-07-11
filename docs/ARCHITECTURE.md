# Architecture

## Canonical application boundary

`guardian-voc-mvp` is the canonical monolith. It contains:

- the Kanji React 19/Vite frontend in `web/`;
- the FastAPI HTTP API and static-file host in `guardian_voc/`;
- the ingestion, redaction, classification, and deterministic metric pipeline;
- one DuckDB database as the canonical application store.

The frontend is not a second deployable application. A multi-stage Docker build
compiles it, copies `web/dist` into the Python image, and FastAPI serves the
single-page application and `/api/v1` on the same origin. Browser requests use
relative `/api/...` URLs.

The sibling `../social-listening-crawler` has a different boundary: it is an
upstream file producer. Production Compose may mount its `data/` directory at
`/app/collector-output:ro`. Guardian Signal takes stable, bounded snapshots of
allowlisted outputs and imports them idempotently. It must not mutate the
sibling directory, depend on a crawler web server, or treat search-result
snippets as customer feedback.

```text
authorized CSV ───────────────┐
                              │
sibling crawler output (ro) ──┼─> normalize/redact/deduplicate/classify
                              │                    │
authorized seller APIs ───────┘                    v
                                                DuckDB
                                                   │
                                     FastAPI /api/v1/dashboard
                                                   │
                                React Command Center (same origin)
```

## Runtime topology

Local development intentionally uses two processes for hot reload:

1. FastAPI listens on `127.0.0.1:8000`.
2. Vite listens on `127.0.0.1:5173` and proxies `/api` to port 8000.

The proxy preserves the production request shape and avoids maintaining a
development-only API adapter. `VITE_API_BASE_URL` is unnecessary in this normal
setup.

Production uses one container and one origin:

1. Node builds the React assets during the image build.
2. The runtime image contains Python, the backend, and the compiled assets.
3. One Uvicorn process serves both the assets and API on port 8000.
4. One persistent volume contains DuckDB and application runtime data.

DuckDB has one writer guarded by application and filesystem locks. Run one
Uvicorn worker, one application instance, and one replica. PostgreSQL or another
concurrent store is a prerequisite for horizontal API scaling.

## Dashboard contract and truth states

The Command Center reads `GET /api/v1/dashboard`. The backend owns aggregation
and returns a truth state, server message, coverage metadata, and the available
dashboard payload. The frontend formats and visualizes that response; it does
not recompute business truth from design fixtures.

State handling is explicit:

- `ready` means the payload is available for the requested scope.
- `partial` means coverage required to compute the requested scope is missing,
  such as an absent current or baseline window. Available values remain usable,
  but the response message and coverage limitations must stay visible. Isolated
  exclusions that do not prevent the requested metrics keep the response
  `ready` and remain disclosed as backend data notes. Neither tier extrapolates
  the missing portion.
- `empty` is a successful query with no usable records for the scope. It renders
  an honest empty state instead of sample charts or invented KPIs.
- transport failures and non-success HTTP responses render an error state. They
  are not converted to `empty` and do not trigger a fixture fallback.

Synthetic records are permitted only in explicit `VOC_DEMO_MODE=true` runs and
must remain visibly labelled. A production response never borrows demo records
to make a sparse dashboard appear complete.

## CSV import trust boundary

`GET /api/v1/imports/config` exposes only safe capability metadata. Preview and
commit endpoints are disabled unless `VOC_WRITE_API_ENABLED=true`, and startup
fails closed if writes are enabled without a non-empty `VOC_ADMIN_TOKEN` or
`VOC_ADMIN_TOKEN_FILE`.

Operators enter the token in the React **Import reviews** panel. It is sent as
`X-Admin-Token` for preview and commit, held in component memory, never written
to local/session storage, and cleared only after a run reaches `completed`. It
is retained with the preview for `partial` and `failed` results. Production
mounts the token as a file secret; it is not baked into the image, exposed as a
Vite variable, placed in a query string, or logged.

The server, rather than the browser, enforces upload size and row limits,
profile selection, Vietnamese filtering, PII redaction, quarantine rules, and
stable identity/content deduplication. Preview performs no database write.
Commit returns `202 Accepted` after persisting a queued pipeline-run status row
in DuckDB. FastAPI retains the upload bytes in the current process and starts an
in-process background task; the service's single-writer locks serialize
ingestion, classification, aggregation, and publication. The frontend polls
`GET /api/v1/runs/{run_id}` until a terminal state and refetches the dashboard
after completed or partial publication.

The status row is persistent, but the upload payload and task are not backed by
a durable job queue. Process termination can therefore leave a queued row that
cannot be resumed; the file must be submitted again. Durable restart recovery
would require persisting the upload/job or using an external queue. A polling
interruption alone remains resumable with the existing run ID while the backend
process continues.

## Pipeline and evidence model

All trusted connectors emit one `RawFeedback` contract. The pipeline normalizes
timestamps and URLs, redacts PII, hashes identifiers, deduplicates across runs,
groups exact public reposts, classifies unseen content, and builds deterministic
fact packets. A grounded writer may shorten those facts; deterministic templates
remain the fail-closed fallback.

Search titles and snippets are discovery evidence only. A candidate can become
feedback only after an allowed reader obtains a durable customer-authored unit
and the normal validation pipeline accepts it. Generic page shells, seller copy,
login walls, hidden comments, and pages without stable unit identity remain
audit or enrichment evidence.

All-channel Guardian trends and public-only competitor benchmarks are separate
measurements. Guardian trends freeze baseline source-stratum weights. Competitor
benchmarks keep only common public strata and apply the same pooled weights to
Guardian, Hasaki, and Watsons.

## Operational health

`/api/v1/live` checks the process without depending on providers.
`/api/v1/ready` checks DuckDB and scheduler readiness. `/api/v1/health` exposes
sanitized source and scheduler state. Health responses must not include tokens,
customer text, source URLs, or provider error bodies.

The scheduler and request-driven imports share the same application service and
single-writer discipline. Scheduled inputs are fingerprinted and checkpointed;
canonical URL and stable feedback identities provide a second idempotency layer.

## Snapshot provenance

The supplied application, crawler, and Kanji UI directories are filesystem
snapshots without `.git` metadata. This workspace therefore cannot establish
their upstream remotes, branches, commits, or authorship. Preserve those facts
in release metadata before treating a build as provenance-reproducible.
