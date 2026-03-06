# Omni → Atlan Connector: Implementation Plan

## Current State

The repository has a solid foundation:

| Component | Status | Notes |
|-----------|--------|-------|
| `client.py` | ✅ Complete | Omni API calls, pagination, retry/rate-limit handling |
| `transformer.py` | ✅ Draft | Produces entity dicts for 5 entity types |
| `workflow.py` + `activities.py` | ✅ Complete | Temporal orchestration with retry policies |
| `handler.py` | ⚠️ Partial | Missing SDK `HandlerInterface` contract |
| `workflow.json` | ✅ Complete | UI config for Atlan frontend |
| **Atlan type definitions** | ✅ Done | `app/typedefs.py` + startup registration in `main.py` |
| **SDK Writer integration** | ✅ Done | `JsonFileWriter` used in `activities.py` |
| **Tests** | ✅ Done | 42 tests across `test_client`, `test_transformer`, `test_activities` |

---

## Phase 1 — Verify Omni API Coverage

Confirm the 5 Omni API endpoints behave exactly as assumed.

- [ ] Validate `/v1/connections` — response envelope (`connections: [...]`), field names (`id`, `name`, `dialect`, `database`)
- [ ] Validate `/v1/models` — pagination shape (`records`, `pageInfo.hasNextPage`, `pageInfo.nextCursor`), field names (`id`, `name`, `modelKind`, `connectionId`, `baseModelId`, `updatedAt`)
- [ ] Validate `/v1/models/{id}/yaml?mode=combined` — `files` dict, topic files end in `.topic`, YAML schema (`name`, `label`, `base_view_name`)
- [ ] Validate `/v1/folders` — field names match transformer expectations
- [ ] Validate `/v1/documents` — field names match transformer expectations, `hasDashboard` flag
- [ ] Identify any undocumented fields worth surfacing (description, tags, visibility, etc.)

**Deliverable:** Field-mapping comments in `client.py` confirming response schema, plus any corrections to `client.py`/`transformer.py`.

---

## Phase 2 — Define Atlan Custom Entity Types (typedef)

Register 6 custom entity types in Atlan before any metadata can be upserted. Atlan uses Apache Atlas typedefs.

### Type hierarchy

```
Asset (Atlan built-in)
├── omni_connection      (a data connection in Omni)
├── omni_model           (a model / dataset)
│   └── omni_topic       (a topic defined in model YAML)
├── omni_folder          (organizational folder)
├── omni_dashboard       (document with hasDashboard=true)
└── omni_workbook        (document with hasDashboard=false)
```

### Attribute definitions (per type)

| Field | Atlas type | Notes |
|-------|-----------|-------|
| `qualifiedName` | string | Atlan dedup key — `{tenantId}/.../{id}` |
| `name` | string | Human-readable name |
| `omniId` | string | Omni internal UUID |
| `last_sync_workflow_name` | string | Populated by every sync |
| `last_sync_run` | string | Populated by every sync |
| type-specific fields | string/date | `dialect`, `modelKind`, `scope`, `url`, etc. |

### Tasks

- [x] Create `app/typedefs.py` with Atlas `EntityDef` structures for all 6 types
- [x] Add `register_typedefs()` function that POSTs to Atlan's `POST /api/meta/types/typedefs` (idempotent — skip if already registered)
- [x] Call `register_typedefs()` from `main.py` on startup (before worker starts)

---

## Phase 3 — Integrate the SDK Writer for Atlan Upload

Replace the manual NDJSON write in `activities.py` with `application_sdk.io.Writer`, which uploads to the Atlan object store and triggers the import pipeline.

### How the SDK Writer works

- Accepts dicts or DataFrames, buffers records, flushes to chunked files
- When `ENABLE_ATLAN_UPLOAD=true` (set in production), calls `ObjectStore.upload_file()` — deposits files into the Atlan-connected S3/GCS bucket
- Atlan's import pipeline picks up those files and upserts entities via the Atlas API
- Returns `ActivityStatistics` with record counts on `close()`

### Tasks

- [x] Replace manual NDJSON loop in `activities.py` with `Writer` from `application_sdk.io`
- [x] Fix Atlas **relationship attribute format** in `transformer.py`:

  Current (flat string — wrong):
  ```json
  { "connectionQualifiedName": "omni/connection/abc" }
  ```
  Correct (nested Atlas form):
  ```json
  {
    "connection": {
      "typeName": "omni_connection",
      "uniqueAttributes": { "qualifiedName": "omni/connection/abc" }
    }
  }
  ```
- [x] Keep a local NDJSON debug write behind the existing `save_output_local` flag (optional, for development)
- [x] Return `ActivityStatistics` from the activity instead of the hand-rolled summary dict

---

## Phase 4 — Fix the Handler Interface Contract

Make `HandlerClass` properly implement the SDK's `HandlerInterface`.

- [x] Change `class HandlerClass(ABC)` → `class HandlerClass(HandlerInterface)` (import from `application_sdk.handlers`)
- [x] Verify method signatures (`load`, `test_auth`, `preflight_check`, `fetch_metadata`, `get_configmap`) match the SDK interface exactly
- [x] Confirm credential flow: the current pattern (credentials arrive via workflow config payload) is correct for custom apps — document this in a comment

---

## Phase 5 — BI Type Hierarchy Decision

Decide whether Omni assets use fully custom types or inherit from Atlan's built-in BI types.

| Option | Description | Trade-off |
|--------|-------------|-----------|
| A — Custom types (current) | All 6 types are `omni_*` extending `Asset` | Fast to ship; assets don't appear in native Atlan BI views |
| B — Extend Atlan BI base types | `omni_dashboard` extends `BIReport`, etc. | More complex; assets appear in lineage and BI experience |

- [x] **Decision:** Start with Option A for initial release
- [x] Document the trade-off and upgrade path in `README.md`

---

## Phase 6 — Test Coverage

Add tests that run locally without a live Omni connection or Atlan instance.

- [x] `tests/test_client.py` — mocked httpx responses for all 5 API methods; pagination logic; retry and rate-limit behavior
- [x] `tests/test_transformer.py` — given a sample `snapshot` dict, assert correct entity types, counts, and qualified names; assert relationship attribute format is correct Atlas form
- [x] `tests/test_activities.py` — mock handler; assert `get_workflow_args` normalizes all config variants correctly
- [ ] `tests/test_integration.py` — end-to-end with a fixture snapshot, assert output matches expected entity list

Use `pytest` + `respx` for httpx mocking.

---

## Phase 7 — Lineage (Future / Nice-to-Have)

Express Omni document → model → database table relationships in Atlan's lineage graph.

Requires:
1. Resolving Omni `connectionId` to an Atlan `Connection.qualifiedName`
2. Resolving topic `base_view_name` to a table in that schema
3. Creating Atlan `Process` / `ColumnProcess` entities

**Deferred** — design the `qualifiedName` scheme now to make this easy to add later. No code changes required in this phase.

---

## Phase 8 — Build, Package, and Deploy

- [x] Verify `Dockerfile` is correct — base image entrypoint runs `uv run --no-sync main.py` automatically, no CMD needed
- [ ] Push image to Atlan-accessible container registry
- [ ] Register app in Atlan App Manager (image ref, env vars, `workflow.json`)
- [ ] Run a test crawl with `max_pages=1` — verify entities appear in Atlan catalog
- [ ] Confirm typedef registration succeeds on first startup

---

## Work Item Summary

| # | Item | Effort | Priority |
|---|------|--------|----------|
| 1 | Validate Omni API schemas | Small | Must-have |
| 2 | `app/typedefs.py` + startup registration | Medium | ✅ Done |
| 3 | SDK Writer integration in `activities.py` | Medium | ✅ Done |
| 4 | Fix Atlas relationship format in `transformer.py` | Small | ✅ Done |
| 5 | Fix `HandlerClass` → `HandlerInterface` | Small | ✅ Done |
| 6 | Unit + integration tests (42 tests) | Medium | ✅ Done |
| 7 | BI type decision + README update | Small | ✅ Done |
| 8 | Lineage via Process entities | Large | Nice-to-have |
| 9 | Docker build + Atlan deployment | Small | Deployment |
