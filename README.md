# Omni Connector App

Atlan custom app for extracting metadata from Omni APIs and transforming it into Atlan-ready entity payloads.

## What this app does

- Connects to Omni REST APIs using API token authentication.
- Extracts connections, models, topics (from model YAML), folders, and documents.
- Transforms extracted metadata into Atlan-ready entity dictionaries.
- Writes NDJSON output for validation during connector development.

## App structure

This follows Atlan app conventions:

- `main.py`
- `app/activities.py`
- `app/workflow.py`
- `app/client.py`
- `app/handler.py`
- `app/transformer.py`
- `app/frontend/workflow.json`

## Local setup

```bash
uv sync --all-extras --all-groups
uv run poe download-components
```

Start dependencies:

```bash
uv run poe start-deps
```

Run app:

```bash
uv run main.py
```

Optional richer local UI:

```bash
npx @atlanhq/app-playground install-to frontend/static
```

## Runtime URLs

- App UI: `http://localhost:8000`
- Temporal UI: `http://localhost:8233`

## Config fields

- `omni_base_url`: Omni base API URL (for example `https://your-org.omniapp.co/api`)
- `omni_api_token`: PAT or organization API key
- `tenant_id`: prefix used in generated qualified names
- `page_size`, `max_pages`: extraction controls
- `verify_ssl`, `timeout_seconds`: HTTP behavior
- `save_output_local`, `output_file`: output settings
