# Changelog

All notable changes to the Omni connector are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.5] - 2026-06-05

**Form-field cleanup.** v0.2.4's workflow registration fix unblocked
end-to-end dispatch, but the first real run on
`marketplace-partner.atlan.com` failed in `get_workflow_args` because
the activity required `connection_epoch_ms` as a form field — and the
Atlan UI doesn't collect it (the epoch is already embedded in the
Connection's qualifiedName at `base_args["connection"]`).

### Changed

- `app/activities.py::get_workflow_args` derives `connection_epoch_ms`
  from `base_args["connection"].attributes.qualifiedName` (third segment
  of `default/omni/<epoch>/...`) before falling back to a form field.
  The form-field path remains so the local playground keeps working.
  The 13-digit validation is unchanged so malformed connections still
  fail loud.
- `app/frontend/workflow.json` — `connection_epoch_ms` is now
  `required: false` with help text noting it's auto-derived in
  production and only relevant for local runs.

### Added

- Tests covering Connection-QN derivation, Connection-QN precedence
  over a stale form field, malformed-QN fallback to the form field,
  and asset-style QNs with extra segments.

## [0.2.4] - 2026-06-04

**Workflow registration fix.** v0.2.3 resolved Test Authentication on
`marketplace-partner.atlan.com` but the first end-to-end workflow run
sat idle: Atlan's launcher dispatches workflows by the wire-level type
name `OmniMetadataExtractionWorkflow` (mirroring the SDK's
`BaseSQLMetadataExtractionWorkflow` convention), and our class was
registered under its Python symbol `WorkflowClass`. The Temporal worker
reported class-not-found and never picked up the run. Latent in every
prior image — the synchronous `/auth` route doesn't go through the
workflow registry, so Test Authentication never exercised it.

### Fixed

- `app/workflow.py:15` — override the registered name on `@workflow.defn`
  to `OmniMetadataExtractionWorkflow`. The Python class symbol
  `WorkflowClass` is unchanged so `main.py` imports and other internal
  references stay intact.

## [0.2.3] - 2026-06-02

**Auth fix, round 2.** v0.2.2 unwrapped the SDK's wrapped auth body but
`client.load_credentials` still only recognized the semantic key names
`omni_base_url` / `omni_api_token`. The Atlan UI sends wire-shape keys
`host` / `password` / `authType` through Heracles to
`POST /workflows/v1/auth`, so v0.2.2 raised `ValueError` again — surfaced
as Heracles' generic "App service returned an internal error" 400 in the
Test Authentication form on `marketplace-partner.atlan.com`. Same
PART-1112 ticket.

### Fixed

- `app/client.py::ClientClass.load_credentials` now accepts both
  credential shapes: wire (`host`, `password`, `authType`) and semantic
  (`omni_base_url`, `omni_api_token`). Wire keys are read as aliases for
  the semantic keys; `authType` is ignored (only API-key auth is
  supported). The protocol check applies to whichever base URL is
  provided.

### Added

- Tests covering the wire-shape path and the protocol check against the
  wire-shape base URL.

## [0.2.2] - 2026-05-31

**Auth fix.** v0.2.1's `/workflows/v1/auth` route raised `ValueError: Both
omni_base_url and omni_api_token are required.` on every credential load.
The Atlan SDK wraps the auth body as `{"credentials": {...}, "metadata":
{...}}` before calling `handler.load(body.model_dump())`, but `load()`
passed the outer wrapper straight to `client.load_credentials`, which
looks for `omni_base_url` at the top level — so it never found it.
Reproduced on `marketplace-partner.atlan.com` (PART-1112) across four
identical-fingerprint failures from pod `omni-7874b49895-v65xk`.

### Fixed

- `app/handler.py::HandlerClass.load` now unwraps the `credentials` key
  out of the wrapped body before forwarding to the client, mirroring the
  same logic already used in `preflight_check`. Falls back to the raw
  `args[0]` so the activities path (which passes a flat dict) keeps
  working.

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
