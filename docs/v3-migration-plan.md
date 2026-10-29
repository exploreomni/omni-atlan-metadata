# SDK v3 migration plan (parked)

Snapshotted 2026-10-29 after reading
`atlanhq/application-sdk/docs/upgrade-guide-v3.md` (saved alongside this file
as `upstream-sdk-v3-upgrade-guide.md`).

**Status: parked.** v2.3.1 → 2.8.7 landed in 0.4.4. CCI needs a correct v2
build first (lineage source type + model order). v3 resumes after that.

## Why v3 is not a bump

The upgrade guide is explicit: v3 is a **clean break**. Every v2 module path
raises `ImportError`. This is a rewrite with the same behavior, not a
migration.

Three structural shifts for us:

1. **`@workflow.defn` + `@activity.defn` → `App` + `@task`.** `app/workflow.py`
   (`WorkflowClass`) and `app/activities.py` (`ActivitiesClass`) collapse
   into one `OmniApp(App)` class.
2. **`HandlerInterface` → `Handler`.** `load()` is removed; context injected
   via `self.context`. `test_auth` / `preflight_check` / `fetch_metadata`
   take typed `Input`/`Output` Pydantic models.
3. **`Dict[str, Any]` is banned at task boundaries.** Our free-form payloads
   become declared Pydantic contracts. Unbounded `list[T]` raises
   `PayloadSafetyError` at import — needs `MaxItems(N)` or `FileReference`.

## What we specifically gain

- **Checkpoint/resume via heartbeat details** (guide Step 11). Exact feature
  Atlan asked for in October. We'd finally be able to raise
  `maximum_attempts` above 1.
- **24h start_to_close backstop + progress watchdog** (Step 11b). Replaces
  our hand-tuned timeouts.
- **Dependency profiles.** `duckdb`+`pandas`+`pyarrow` (~300 MiB) drop out of
  core — we're API-based, don't need `[sql]` extra, lighter image.
- **Run metrics via `TaskStatistics` / `TaskResult`.** Replaces ad-hoc
  `_failures` / `_stats` dicts.

## What breaks

Every one of these raises `ImportError` under v3 — all required rewrites:

| Today | v3 target |
|---|---|
| `app/workflow.py::WorkflowClass(WorkflowInterface)` | `app/app.py::OmniApp(App)` |
| `app/activities.py::ActivitiesClass(ActivitiesInterface)` | methods on `OmniApp` with `@task` |
| `app/handler.py::HandlerClass(HandlerInterface)` | `Handler` subclass with typed I/O |
| `main.py::BaseApplication(...).start()` | `ENV ATLAN_APP_MODULE=app.app:OmniApp` + `run_dev_combined` for dev |
| `@workflow.defn(name="OmniMetadataExtractionWorkflow")` | `@entrypoint` on method |
| `@auto_heartbeater` | removed — built into `@task` |
| `SecretStore.get_credentials(credential_guid)` | `self.context.get_secret(...)` or `self.context.resolve_credential(ref)` |
| `ActivityStatistics` / `ActivityResult` | `TaskStatistics` / `TaskResult` |
| Dict-based payloads flowing through activities | Pydantic `Input`/`Output` + `MaxItems` or `FileReference` |
| `app/frontend/workflow.json` form | `app/generated/manifest.json` from Pkl contract |
| `FROM app-runtime-base:2.8.7-14` | `FROM app-runtime-base:3` |

## The snapshot problem (biggest unknown)

Today `extract` returns a big dict and `transform` consumes it in the same
activity. Under v3 that payload crosses an `@task` boundary — Temporal's
~2MB cap applies.

On a CCI-size tenant that's unquestionably over 2MB. Fix is almost certainly
**`FileReference` to NDJSON on disk** between extract and transform
(auto-upload / auto-download by the framework, per Step 7 of the guide).
Asset-mapper pattern (Step 3b) describes it directly.

## Scoping

| Phase | What | Days of focused work |
|---|---|---|
| 1 | Scaffold `app/app.py` with `OmniApp(App)` + `@entrypoint`; move `@task`s over | 1-2 |
| 2 | Rewrite `handler.py` as a v3 `Handler` with typed I/O | 0.5 |
| 3 | Pydantic `Input`/`Output` contracts; snapshot as `FileReference` | 1-2 |
| 4 | Rework 178 tests — new import paths, new seams | 1-2 |
| 5 | Pkl contract + `app/generated/manifest.json` to replace `workflow.json` | 0.5-1 |
| 6 | Local run via `run_dev_combined`; smoke-test against Peter's org | 0.5 |
| 7 | Checkpoint/resume via heartbeat details on extract task | 1-2 |
| 8 | Deploy; monitor first production run; fix tenant surprises | buffer, 1-2 |

**~2 weeks focused eng. 1 week elapsed if dedicated person, 3-4 weeks otherwise.**

## Sequencing

Do v3 as a dedicated branch, not an in-place migration on `main`:

1. We must keep patching v2 for CCI if urgent. `main` is 0.4.4 in production.
2. The Atlan import rewriter (`tools/migrate_v3/rewrite_imports.py` per the
   guide) handles mechanical imports but not the transformer / handler /
   workflow restructure — hand work regardless.
3. Register v3 as a **separate app_id** on marketplace-partner during
   overlap so a half-finished v3 doesn't replace a working v2 install.

## Before any coding

1. Fetch `standards/v3-readiness.md` — the sign-off checklist.
2. Fetch ADR-0014 (two-store rule) and ADR-0018 (progress-aware heartbeat).
3. Decide snapshot strategy — `FileReference` to NDJSON is the likely answer.
4. Decide if asset-mapper pattern (Step 3b) goes in the first cut or a follow-up.

## Open questions for Atlan when we restart

- Timing driver — ask-by-date vs. get-ahead-of-it
- Is a separate `app_id` for the v3 app the recommended overlap pattern?
- v3-readiness checklist link if it's not public

## Not in this file

Code. Deliberate — Atlan hasn't asked us to commit yet, and the readiness
checklist might change scope. Resume here when CCI's v2 is landed and
Atlan confirms the ask.
