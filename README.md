# Omni-Atlan Integration

This project extracts metadata from Omni and generates output files for the Atlan team to use for:
- Asset profile design
- Lineage graph construction
- Meta model extensions
- Publishing to Atlan

## Goal

Generate Omni metadata in a format that the Atlan team can use to design asset profiles, build lineage graphs, extend the meta model, and publish assets to Atlan.

## Documentation Links

### Omni API Documentation
- [Omni API Overview](https://docs.omni.co/docs/API)
- [Documents API](https://docs.omni.co/docs/API/documents)
- [Retrieve Document Queries](https://docs.omni.co/docs/API/documents#retrieve-document-queries)
- [Connections API](https://docs.omni.co/docs/API/connections#list-connections)
- [Models API](https://docs.omni.co/docs/API/models)
- [Topics API](https://docs.omni.co/docs/API/topics)

### Atlan Documentation
- [Atlan Apps Framework](https://docs.atlan.com/product/capabilities/build-apps/concepts/apps-framework)

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Omni credentials:
```bash
cp .env.example .env
```

Edit `.env` and add:
```
OMNI_BASE_URL=https://your-instance.omniapp.co
OMNI_API_KEY=your_api_key_here
```

## Usage

Run the metadata extraction script to generate output files for the Atlan team:

```bash
python generate_atlan_output.py
```

This will generate the following files in the `output/` directory:
- `omni_metadata_full.json` - Complete metadata with all assets
- `meta_model_spec.json` - Meta model extension specifications
- `lineage_spec.json` - Lineage mappings for graph construction
- `asset_profile_spec.json` - Asset profile specifications

## Extracted Metadata

The integration extracts the following Omni assets:

- **Connections** - Database connections with dialect, database, and schema information
- **Shared Models** - Base models that can be used across workbooks
- **Documents** - Dashboards and saved workbooks
- **Queries** - Queries from documents with fields, tables, sorts, and filters
- **Topics** - Virtual data marts/domains (when available)

## Lineage

The integration builds lineage relationships tracing:
- **Connection** → **Shared Model** → **Workbook Model** → **Document** → **Query**

This enables end-to-end data lineage visualization from source connections through models and documents to queries.

## Output Files

### `omni_metadata_full.json`
Complete metadata for all extracted assets, organized by asset type.

### `meta_model_spec.json`
Specifications for Atlan meta model extensions, including:
- Asset types
- Relationship types
- Custom attributes

### `lineage_spec.json`
Lineage mappings showing upstream and downstream relationships between assets.

### `asset_profile_spec.json`
Asset profile specifications with required and optional attributes for each asset type.

## Project Structure

```
omni_atlan/
├── config.py              # Configuration management
├── omni_client.py         # Omni API client
├── metadata_extractor.py   # Metadata extraction logic
├── meta_model_mapper.py   # Mapping to Atlan meta model
└── output_formatter.py    # Output file formatting

generate_atlan_output.py   # Main script to generate output files
main.py                     # CLI entry point (for Temporal workflows)
```

## Rate Limiting

The Omni API has a rate limit of 60 requests per minute. The integration includes automatic rate limiting with exponential backoff to handle rate limit errors gracefully.

## License

[Add your license here]
