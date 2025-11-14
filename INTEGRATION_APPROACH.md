# Omni-Atlan Integration Approach

## Overview

This integration follows the collaborative approach outlined by the Atlan team:
- **Omni Team**: Writes extract logic and mapping to meta model using Apps SDK
- **Atlan Team**: Handles asset profiles, lineage graphs, meta model extensions, and publishing

## Omni Hierarchy

Based on the Omni data model, the integration extracts the following hierarchy (bottom to top):

1. **Data Warehouse Schema** - Raw data warehouse schemas, tables, and columns
2. **Schema Model** - Metadata from YAML files defining the schema
3. **Topics** - Virtual data marts or data domains (use case specific subsets)
4. **Shared Model** - Shared models with Branch/Main versions
5. **Workbook Model** - Models specific to workbooks
6. **Workbook Tab** - Tabs within workbooks
7. **Dashboard Tile** - Tiles within dashboards
8. **Dashboard** - Top-level dashboards

## Key Components

### 1. Meta Model Mapper (`meta_model_mapper.py`)

Maps Omni metadata to Atlan meta model format using Apps SDK structure:

- **Asset Type Definitions**: Defines all Omni asset types (OmniTopic, OmniDashboard, etc.)
- **Relationship Mappings**: Creates relationships between hierarchy levels
- **Lineage Mappings**: Provides lineage information for graph construction
- **Meta Model Extension Spec**: Generates specification for Atlan team

### 2. Metadata Extractor (`metadata_extractor.py`)

Extracts metadata following the full Omni hierarchy:

- Extracts all asset types from bottom to top
- Builds relationships between assets
- Creates lineage mappings
- Generates formatted output for Atlan team

### 3. Output Formatter (`output_formatter.py`)

Formats output into files for Atlan team:

- **meta_model_spec.json**: Asset types, relationships, and custom attributes
- **lineage_spec.json**: Lineage mappings for graph construction
- **asset_profile_spec.json**: Asset profile specifications
- **omni_metadata_full.json**: Complete extracted metadata

## Output Files for Atlan Team

### meta_model_spec.json

Contains:
- Asset type definitions with display names and descriptions
- Relationship type definitions
- Custom attribute specifications

### lineage_spec.json

Contains:
- Upstream/downstream mappings
- Transformation types
- Complete lineage graph structure

### asset_profile_spec.json

Contains:
- Required and optional attributes per asset type
- Sample attributes
- Relationship types per asset

### omni_metadata_full.json

Contains:
- All extracted assets with full attributes
- All relationships
- Complete hierarchy structure

## Usage

### Generate Output Files

```bash
python generate_atlan_output.py output/
```

This creates all output files in the specified directory for the Atlan team to use.

### What Happens Next

1. **Omni Team**: Runs the extract and generates output files
2. **Atlan Team**: Reviews output files and:
   - Designs asset profiles
   - Builds lineage graphs
   - Extends meta model with new asset types
   - Implements publishing logic
3. **Collaboration**: Both teams work together to test and refine

## Asset Types

The integration defines the following asset types:

- `OmniDataWarehouseSchema` - Data warehouse schemas
- `OmniSchemaModel` - Schema models from YAML
- `OmniTopic` - Virtual data marts/domains
- `OmniSharedModel` - Shared models
- `OmniSharedModelBranch` - Shared model branches
- `OmniSharedModelMain` - Shared model main branch
- `OmniWorkbookModel` - Workbook models
- `OmniWorkbookTab` - Workbook tabs
- `OmniDashboardTile` - Dashboard tiles
- `OmniDashboard` - Dashboards
- `OmniQuery` - Queries
- `OmniDocument` - Documents
- `OmniConnection` - Connections

## Relationship Types

The integration defines relationships between hierarchy levels:

- `OmniSchemaModelToDataWarehouse` - Schema model → Data warehouse
- `OmniTopicToSchemaModel` - Topic → Schema model
- `OmniSharedModelToTopic` - Shared model → Topic
- `OmniWorkbookModelToSharedModel` - Workbook model → Shared model
- `OmniWorkbookTabToWorkbookModel` - Workbook tab → Workbook model
- `OmniDashboardTileToWorkbookTab` - Dashboard tile → Workbook tab
- `OmniDashboardToDashboardTile` - Dashboard → Dashboard tiles

## Custom Attributes

Each asset type includes Omni-specific custom attributes:

- `omni_*_id` - Omni IDs for each asset type
- `omni_branch` - Branch information for shared models
- `omni_yaml_file_path` - YAML file paths for schema models
- `omni_metadata_source` - Source of metadata
- `omni_topic_type` - Type of topic
- `omni_use_case` - Use case information

## Next Steps

1. **Test Extraction**: Run `generate_atlan_output.py` to test extraction
2. **Review Output**: Check generated files for completeness
3. **Share with Atlan**: Provide output files to Atlan team
4. **Collaborate**: Work with Atlan team on meta model extensions
5. **Implement Publishing**: Once meta model is ready, implement publishing logic

