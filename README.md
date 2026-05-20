# Omni Connector App

Atlan custom connector that crawls metadata from [Omni Analytics](https://omni.co) and syncs it into the Atlan catalog.

## What this connector does

- Authenticates to Omni REST APIs using an API token.
- Extracts **connections**, **models**, **folders**, and **documents** (dashboards and workbooks).
- Enumerates **topics** from each model's YAML and enriches them via `GET /v1/models/{modelId}/topic/{topicName}` to capture base-view identity, joined views, dimensions, and measures used for downstream lineage.
- Resolves each dashboard's per-tile topics via `queryPresentations[].topicName` from the document detail API.
- Registers Omni custom typedefs (1 abstract supertype + 4 concrete types + 3 enums + 3 relationships) in Atlan on first startup. On the canary tenant (`marketplace-partner.atlan.com`) Atlan has pre-seeded these; registration is idempotent.
- Emits Atlan `Process` entities for **Topic → Document** lineage and (when configured) **Source Table → Topic** lineage so the relationships render in Atlan's lineage graph.
- Transforms extracted metadata into Atlan entities and uploads them via the Atlan Application SDK's object-store pipeline.

## Asset type hierarchy

Aligned with Atlan's partner typedef reference v0 (2026-05-15). All four concrete Omni types extend an abstract `OmniV01` supertype, which in turn extends Atlan's built-in BI supertype:

```
Asset → Catalog → BI → OmniV01 (abstract)
                       ├── OmniV01Model     — a model / dataset; references upstream Connection,
                       │                       may inherit from a base Model
                       │   └── OmniV01Topic — presentation projection backed by warehouse tables
                       ├── OmniV01Folder    — organizational hierarchy node
                       └── OmniV01Document  — dashboard OR workbook
                                              (omniV01DocumentType discriminator: DASHBOARD | WORKBOOK)
```

The Omni instance itself is represented by the built-in Atlan `Connection` type with `connectorName: "omni"` — no custom connection type. The previously-shipped `omni_connection`, `omni_dashboard`, and `omni_workbook` custom types are retired.

Cross-references between Omni assets (`OmniV01Model.connection`, `OmniV01Topic.model`, `OmniV01Model.baseModel`, `OmniV01Document.folder`) are emitted as **typed Atlas relationship edges**, not string-QN attributes — so Atlan's lineage graph and SDK traversal work out of the box.

### Qualified name convention

All entities use the standard partner-connector pattern:

```
default/omni/{connection_epoch_ms}/{rest}
```

where `{connection_epoch_ms}` is the 13-digit creation timestamp of the Atlan-side Omni Connection (operator-supplied in the workflow form). Example: `default/omni/1747156800000/model/3f24abc1.../topic/trades_enriched`.

### Model filtering

Not all Omni models are synced to Atlan:

- **SCHEMA** models are excluded — these mirror raw database schema and are not authored artifacts.
- **WORKBOOK** models are only included if they back a saved document. Omni creates an ephemeral WORKBOOK model each time a user opens a workbook session; these are excluded unless the workbook has been saved. The connector determines this by calling `GET /v1/documents/{identifier}` for each document and matching the returned `modelId`.
- **SHARED** models are always included.

## Lineage

The connector emits Atlan `Process` entities so lineage edges render in Atlan's graph view. Two kinds:

- **Topic → Document** — one Process per unique (topic, document) pair. Inputs are pulled from the document detail's `queryPresentations[].topicName`, deduped per document. `inputs: [OmniV01Topic]`, `outputs: [OmniV01Document]`. Always emitted; no extra config required.
- **Source Table → Topic** — one Process per topic, with one input per backing view (base + joined). Each view's source table qualifiedName is built from the user-supplied `atlan_source_connection_map` plus the view's `catalog`/`schema`/`table_name` returned by the topic API. When a view has no `catalog` (single-database connectors like Postgres), the Omni connection's `database` is used as the catalog. Database-agnostic — works with Snowflake, Redshift, BigQuery, Postgres, etc. `inputs: [Table]`, `outputs: [OmniV01Topic]`. **Disabled by default**; enable by setting `atlan_source_connection_map`.

`Process` is Atlan's built-in supertype, so no custom typedef is registered for it. If a customer's source database hasn't been crawled in Atlan, source-table Process entities are still emitted but the lineage edge will not render until the table assets exist.

## App structure

```
main.py                        # Application entry point
app/
  activities.py                # Temporal workflow activities
  client.py                    # Omni REST API client (concurrent N+1 mitigation)
  handler.py                   # HandlerInterface implementation
  transformer.py               # Raw Omni data → Atlan entity dicts (OmniV01* shape)
  typedefs.py                  # Enum + entity + relationship typedefs; idempotent registration
  workflow.py                  # Temporal workflow definition
  frontend/
    workflow.json              # Atlan UI configuration form
scripts/
  inspect_dryrun.py            # Validate local NDJSON output against the typedef contract
tests/
  test_client.py               # Omni API client unit tests
  test_transformer.py          # Transformer unit tests
  test_activities.py           # Activity config-normalization tests
```

## Local development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- [Dapr CLI](https://docs.dapr.io/getting-started/install-dapr-cli/)
- [Temporal CLI](https://docs.temporal.io/cli)

### Install dependencies

```bash
uv sync --all-extras --all-groups
uv run poe download-components
```

### Start local dependencies (Dapr + Temporal)

```bash
uv run poe start-deps
```

### Run the app

```bash
uv run main.py
```

### Runtime URLs

| Service | URL |
|---------|-----|
| App UI | http://localhost:8000 |
| Temporal UI | http://localhost:8233 |

### Run tests

```bash
uv run pytest tests/ -v
```

### Inspect a dry-run output

```bash
python scripts/inspect_dryrun.py omni_entities.ndjson
```

Validates that all entities match the OmniV01 typedef contract — type names, qualified-name prefix, required discriminators (`omniV01DocumentType`, `omniV01ModelKind`), Process I/O typing, and no regressions to retired snake_case type names. Exits non-zero on red flags so it can gate CI.

## Configuration

| Field | Required | Description |
|-------|----------|-------------|
| `omni_base_url` | Yes | Omni API base URL, e.g. `https://your-org.omniapp.co/api` |
| `omni_api_token` | Yes | Organization API key or personal access token |
| `connection_epoch_ms` | Yes | 13-digit creation timestamp (ms) of the Atlan-side Omni Connection. Anchors every qualifiedName under `default/omni/{this_value}/...` |
| `page_size` | Yes | Records per API page (default: `50`) |
| `max_pages` | No | Cap on pages fetched per resource; omit to fetch all |
| `verify_ssl` | No | Verify TLS certificates (default: `true`) |
| `timeout_seconds` | No | HTTP request timeout in seconds (default: `30`) |
| `max_concurrency` | No | Max in-flight per-model-YAML + per-document-detail fetches (default: `10`) |
| `atlan_source_connection_map` | No | JSON object mapping Omni connection IDs to Atlan source-database connection qualifiedNames, e.g. `{"omni-conn-id": "default/snowflake/1700000000"}`. When set, the connector emits Source-Table → Topic lineage processes. Database-agnostic. |
| `save_output_local` | No | Debug: also write NDJSON locally (default: `false`; hidden from the production form) |
| `output_file` | No | Debug: path for the local NDJSON file (default: `omni_entities.ndjson`; hidden from the production form) |

## Deployment to Atlan

### 1. Build the Docker image

```bash
docker build -t omni-connector:latest .
```

> The base image (`registry.atlan.com/public/app-runtime-base:2.8.7-6`) is pulled from Atlan's registry. Ensure your Docker daemon is authenticated:
> ```bash
> docker login registry.atlan.com
> ```

### 2. Push to your registry

```bash
docker tag omni-connector:latest <your-registry>/omni-connector:latest
docker push <your-registry>/omni-connector:latest
```

### 3. Register the app in Atlan

In the Atlan UI, navigate to **App Manager → Register App** and provide:

- **Image**: the full image reference from step 2
- **Environment variables** (set as Atlan secrets or env config):
  - `ATLAN_BASE_URL` — your Atlan instance URL
  - `ATLAN_API_KEY` — an Atlan API key with permission to create typedefs and upsert assets
  - Object store config as required by your Atlan deployment (S3/GCS bucket, credentials)

### 4. Run a test crawl

Trigger the connector from the Atlan UI with `max_pages=1` to verify:

1. Typedef registration succeeds on first startup (check app logs).
2. Entities appear in the Atlan catalog under the OmniV01 types.
3. `qualifiedName` values match `default/omni/{your_connection_epoch_ms}/...`.

### 5. Schedule recurring syncs

Once validated, configure a cron schedule in the Atlan workflow settings to keep the catalog in sync with Omni.
