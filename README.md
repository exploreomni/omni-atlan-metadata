# Omni Connector App

Atlan custom connector that crawls metadata from [Omni Analytics](https://omni.co) and syncs it into the Atlan catalog.

## What this connector does

- Authenticates to Omni REST APIs using an API token.
- Extracts **connections**, **models**, **folders**, and **documents** (dashboards and workbooks).
- Enumerates **topics** from each model's YAML and enriches them via `GET /v1/models/{modelId}/topic/{topicName}` to capture base-view source-table identity, joined views, dimensions, and measures.
- Resolves each dashboard's per-tile topics via `queryPresentations[].topicName` from the document detail API.
- Registers six custom entity types in Atlan (`omni_connection`, `omni_model`, `omni_topic`, `omni_folder`, `omni_dashboard`, `omni_workbook`) on first startup.
- Emits Atlan `Process` entities for **Topic → Dashboard** lineage and (when configured) **Source Table → Topic** lineage so the relationships render in Atlan's lineage graph.
- Transforms extracted metadata into Atlan entities and uploads them via the Atlan Application SDK's object-store pipeline.

## Asset type hierarchy

All six Omni types extend Atlan's built-in `Asset` supertype:

```
Asset
├── omni_connection   — a data connection defined in Omni
├── omni_model        — a model / dataset (may reference a connection and a base model)
│   └── omni_topic    — a topic defined in model YAML (references its parent model)
├── omni_folder       — an organizational folder
├── omni_dashboard    — a document with at least one dashboard view
└── omni_workbook     — a document without a dashboard view
```

### Model filtering

Not all Omni models are synced to Atlan:

- **SCHEMA** models are excluded — these mirror the raw database schema and are not authored artifacts.
- **WORKBOOK** models are only included if they back a saved document (dashboard or workbook). Omni creates an ephemeral WORKBOOK model each time a user opens a workbook session; these are excluded unless the workbook has been saved as a document. The connector determines this by calling `GET /v1/documents/{identifier}` for each document and matching the returned `modelId` against the models list.
- **SHARED** models are always included — these are the authored, shared data models.

Cross-references between types (e.g. `connectionQualifiedName`, `modelQualifiedName`) are stored as string attributes rather than Atlas relationship edges. This keeps the typedef schema simple and is sufficient for search, impact analysis, and asset browsing in Atlan.

## Lineage

The connector emits Atlan `Process` entities so lineage edges render in Atlan's graph view. Two kinds:

- **Topic → Dashboard / Workbook** — one Process per unique (topic, document) pair. Inputs are pulled from the document detail's `queryPresentations[].topicName`, deduped per document. Always emitted; no extra config required.
- **Source Table → Topic** — one Process per topic, with one input per backing view (base + joined). Each view's source table qualifiedName is built from the user-supplied `atlan_source_connection_map` plus the view's `catalog`/`schema`/`table_name` returned by the topic API. When a view has no `catalog` (single-database connectors like Postgres), the Omni connection's `database` is used as the catalog. Database-agnostic — works with Snowflake, Redshift, BigQuery, Postgres, etc. **Disabled by default**; enable by setting `atlan_source_connection_map` (see Configuration).

`Process` is Atlan's built-in supertype, so no custom typedef is registered for it. If a customer's source database hasn't been crawled in Atlan, source-table Process entities are still emitted but the lineage edge will not render until the table assets exist.

## App structure

```
main.py                        # Application entry point
app/
  activities.py                # Temporal workflow activities
  client.py                    # Omni REST API client
  handler.py                   # HandlerInterface implementation
  transformer.py               # Raw Omni data → Atlan entity dicts
  typedefs.py                  # Custom entity type definitions + registration
  workflow.py                  # Temporal workflow definition
  frontend/
    workflow.json              # Atlan UI configuration form
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

### Optional: richer local UI

```bash
npx @atlanhq/app-playground install-to frontend/static
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

## Configuration

| Field | Required | Description |
|-------|----------|-------------|
| `omni_base_url` | Yes | Omni API base URL, e.g. `https://your-org.omniapp.co/api` |
| `omni_api_token` | Yes | Organization API key or personal access token |
| `tenant_id` | Yes | Prefix for generated `qualifiedName` values (default: `omni`) |
| `page_size` | Yes | Records per API page (default: `50`) |
| `max_pages` | No | Cap on pages fetched per resource; omit to fetch all |
| `verify_ssl` | No | Verify TLS certificates (default: `true`) |
| `timeout_seconds` | No | HTTP request timeout in seconds (default: `30`) |
| `save_output_local` | No | Also write a local NDJSON file for debugging (default: `true`) |
| `output_file` | No | Path for the local debug file (default: `omni_entities.ndjson`) |
| `atlan_source_connection_map` | No | JSON object mapping Omni connection IDs to Atlan source-database connection qualifiedNames, e.g. `{"omni-conn-id": "default/snowflake/1700000000"}`. When set, the connector emits Source-Table → Topic lineage processes that link to the database tables Atlan has already crawled. Database-agnostic — works with Snowflake, Redshift, BigQuery, Postgres, etc. |

## Deployment to Atlan

### 1. Build the Docker image

```bash
docker build -t omni-connector:latest .
```

> The base image (`registry.atlan.com/public/application-sdk:main-2.3.1`) is pulled from
> Atlan's registry. Ensure your Docker daemon is authenticated:
> ```bash
> docker login registry.atlan.com
> ```

### 2. Push to your registry

Push to whichever container registry your Atlan instance can pull from:

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
- **Frontend config**: the `app/frontend/workflow.json` file (uploaded or referenced)

### 4. Run a test crawl

Trigger the connector from the Atlan UI with `max_pages=1` to verify:

1. Typedef registration succeeds on first startup (check app logs).
2. Entities appear in the Atlan catalog under the custom types.
3. `qualifiedName` values are stable and match the `tenant_id` prefix you configured.

### 5. Schedule recurring syncs

Once validated, configure a cron schedule in the Atlan workflow settings to keep the catalog in sync with Omni.
