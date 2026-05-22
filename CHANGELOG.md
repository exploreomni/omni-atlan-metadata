# Changelog

All notable changes to the Omni connector are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-05-22

**Security fix.** v0.2.0 inadvertently shipped sensitive local files inside
the Docker image because the `COPY . .` step in the Dockerfile did not honor
`.gitignore`. Atlan partner review flagged:

- `app/.env` containing a live Omni API token bound to `peter.omniapp.co`
- `omni_entities.ndjson` — a 4.4 MB metadata snapshot of the same tenant
- `.git/` history

### Added

- `.dockerignore` — authoritative exclusion list for the Docker build context:
  `.env`/`.env.*` (except `.env.example`), `.git/`, `.venv/`, `local/`,
  `components/`, `temporal.db*`, `omni_entities.ndjson`, `*.ndjson`, Python
  caches, frontend playground assets, IDE files, `.github/`.

### Fixed

- v0.2.0 image leaked the Omni API token, a tenant metadata snapshot, and
  `.git/`. v0.2.1 builds without any of these in the layer. The leaked token
  was revoked on the Omni side; the v0.2.0 / `c95349` tags must not be
  deployed.

## [0.2.0] - 2026-05-20

Aligns the connector image with Atlan's v0 partner typedef reference, clears
the quality flags raised in the va3aeae codebase analysis, and adds the
operational hardening needed to run against real-world Omni tenants
(rate-limit honoring, progress visibility, recoverable timeouts).

Validated end-to-end against `peter.omniapp.co` on 2026-05-20: 36 models /
8915 topics / 28 documents / 32 lineage processes, no red flags from the
`scripts/inspect_dryrun.py` contract checks.

### Added

- Abstract `OmniV01` supertype (extends `BI`) plus four concrete entity
  typedefs: `OmniV01Model`, `OmniV01Topic`, `OmniV01Folder`, `OmniV01Document`.
- Three enum typedefs: `OmniV01ModelKind`, `OmniV01DocumentType`,
  `OmniV01Scope`.
- Three internal typed relationships: model→topics, model→baseModel/derived
  models, folder→documents.
- `connection_epoch_ms` workflow form field; qualified names now follow
  `default/omni/{connection_epoch_ms}/{rest}`.
- Thread-safe API rate limiter on the Omni client (default 60 rpm, exposed as
  a `rate_limit_rpm` form field). Spaces requests evenly regardless of
  `max_concurrency`.
- Honor `Retry-After` header on 429 responses; fall back to jittered
  exponential backoff if Omni doesn't send one.
- Progress logging during `fetch_snapshot` — model/document completion
  counters via `as_completed`, plus summary line on snapshot done.
- `OMNI_LOCAL_UI=1` env flag for local development. When set, the SDK's UI
  routes are mounted at `http://localhost:8000`, and `save_output_local` is
  forced on so dry-runs leave `omni_entities.ndjson` on disk for the
  `scripts/inspect_dryrun.py` validator.
- Omni Deep Pink monogram logo, inlined as a base64 data URI in
  `workflow.json` and checked in as `app/frontend/omni-logo.svg`.

### Changed

- All entity payloads map to standard `Asset.*` fields where applicable
  (`ownerUsers`, `sourceURL`, `sourceUpdatedAt`).
- Cross-references promoted from string-QN attributes to typed Atlas
  relationship edges.
- `Process` lineage entities now reference `OmniV01Topic` and `OmniV01Document`
  as inputs/outputs (Snowflake → Topic → Document chain).
- Base image upgraded to `app-runtime-base:2.8.7-6` (was the legacy
  `application-sdk:main-2.3.1`); picks up CVE remediation.
- `extract_and_transform_metadata` activity timeout raised from 20 min to 8 h
  (large-tenant runs at the 60 rpm cap can exceed 4 h).
- Typedef-registration failure now surfaces as `ERROR` (was `WARN`) so the
  silent-bad-startup mode is no longer possible.
- `get_workflow_args` now sources every form field from
  `payload`/`metadata`/`credentials`/`base_args` so it handles both the
  marketplace-packages nesting and the playground's flat layout.

### Removed

- Custom `omni_connection`, `omni_dashboard`, `omni_workbook` typedefs. Use the
  built-in `Connection` with `connectorName: "omni"` for the warehouse anchor;
  the unified `OmniV01Document` carries an `omniV01DocumentType` discriminator.
- `Asset.*`-overlapping attributes from the custom typedefs (`url`, `updatedAt`,
  `ownerId/ownerName`, custom `last_sync_*` triple).

### Fixed

- `application.start()` now passes `ui_enabled=False` in production (and `True`
  when `OMNI_LOCAL_UI=1`) so the SDK does not try to mount the empty
  `frontend/static/` stub in production while still serving the form locally.
- `snapshot["document_model_ids"]` is now a JSON-serializable `list` (was a
  `set`), unblocking any future activity-to-activity hand-off of the snapshot.
- `connection_epoch_ms` validation failure now raises
  `ApplicationError(non_retryable=True)` instead of `ValueError`, so misconfig
  fails fast without burning Temporal retries.

## [0.1.0] - 2026-03-10

Initial Harbor push (`a3aeae`). Six custom typedefs, file-output +
publish-app delivery, full Dapr + Temporal integration, source-table-to-topic
and topic-to-dashboard Process lineage.
