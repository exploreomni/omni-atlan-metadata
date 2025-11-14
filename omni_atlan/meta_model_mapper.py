"""Map Omni metadata to Atlan meta model using Apps SDK format

This module handles the mapping of Omni's hierarchical data model to Atlan's meta model.
The output format is designed for Atlan team to use for:
- Asset profile design
- Lineage graph construction
- Meta model extensions
- Publishing

Based on Omni hierarchy:
- Data Warehouse Schema (bottom layer)
- Schema Model (from YAML metadata)
- Topics (virtual data marts/domains)
- Shared Model (with Branch/Main versions)
- Workbook Model
- Workbook Tab
- Dashboard Tile
- Dashboard (top layer)
"""

from typing import List, Dict, Any, Optional
from enum import Enum


class OmniAssetType(str, Enum):
    """Omni asset types mapped to Atlan meta model"""
    # Bottom to top hierarchy
    DATA_WAREHOUSE_SCHEMA = "OmniDataWarehouseSchema"
    SCHEMA_MODEL = "OmniSchemaModel"
    TOPIC = "OmniTopic"  # Virtual data mart/domain
    SHARED_MODEL = "OmniSharedModel"
    SHARED_MODEL_BRANCH = "OmniSharedModelBranch"
    SHARED_MODEL_MAIN = "OmniSharedModelMain"
    WORKBOOK_MODEL = "OmniWorkbookModel"
    WORKBOOK_TAB = "OmniWorkbookTab"
    DASHBOARD_TILE = "OmniDashboardTile"
    DASHBOARD = "OmniDashboard"
    
    # Additional asset types
    QUERY = "OmniQuery"
    DOCUMENT = "OmniDocument"
    WORKBOOK = "OmniWorkbook"  # Saved workbook (from documents)
    CONNECTION = "OmniConnection"
    VIEW_FILE = "OmniViewFile"
    RELATIONSHIP_FILE = "OmniRelationshipFile"
    MODEL_FILE = "OmniModelFile"


class MetaModelMapper:
    """Maps Omni metadata to Atlan meta model format"""
    
    @staticmethod
    def create_asset_definition(
        asset_type: OmniAssetType,
        attributes: Dict[str, Any],
        relationships: Optional[List[Dict[str, Any]]] = None,
        lineage: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create an asset definition in Atlan meta model format
        
        Args:
            asset_type: The Omni asset type
            attributes: Asset attributes (name, qualified_name, description, etc.)
            relationships: List of relationships to other assets
            lineage: Lineage information (upstream/downstream)
        
        Returns:
            Asset definition in Atlan format
        """
        asset_def = {
            "type_name": asset_type.value,
            "attributes": {
                **attributes,
                # Ensure required fields
                "name": attributes.get("name", "Unknown"),
                "qualified_name": attributes.get("qualified_name", ""),
            }
        }
        
        if relationships:
            asset_def["relationships"] = relationships
        
        if lineage:
            asset_def["lineage"] = lineage
        
        return asset_def
    
    @staticmethod
    def map_data_warehouse_schema(schema_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Data Warehouse Schema to Atlan asset"""
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.DATA_WAREHOUSE_SCHEMA,
            attributes={
                "name": schema_data.get("name", "Unknown Schema"),
                "qualified_name": f"omni://datawarehouse/schema/{schema_data.get('id')}",
                "description": schema_data.get("description", ""),
                "omni_schema_id": schema_data.get("id"),
                "omni_schema_name": schema_data.get("name"),
                "omni_connection_id": schema_data.get("connection_id"),
            }
        )
    
    @staticmethod
    def map_schema_model(model_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Schema Model (from YAML) to Atlan asset"""
        relationships = []
        
        # Link to Data Warehouse Schema if available
        if model_data.get("data_warehouse_schema_id"):
            relationships.append({
                "type_name": "OmniSchemaModelToDataWarehouse",
                "attributes": {
                    "qualified_name": f"omni://schemamodel/{model_data.get('id')}->omni://datawarehouse/schema/{model_data.get('data_warehouse_schema_id')}"
                }
            })
        
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.SCHEMA_MODEL,
            attributes={
                "name": model_data.get("name", "Unknown Schema Model"),
                "qualified_name": f"omni://schemamodel/{model_data.get('id')}",
                "description": model_data.get("description", ""),
                "omni_schema_model_id": model_data.get("id"),
                "omni_yaml_file_path": model_data.get("yaml_file_path", ""),
                "omni_metadata_source": "yaml",
            },
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def map_topic(topic_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Topic (virtual data mart/domain) to Atlan asset"""
        relationships = []
        
        # Link to Schema Model if available
        if topic_data.get("schema_model_id"):
            relationships.append({
                "type_name": "OmniTopicToSchemaModel",
                "attributes": {
                    "qualified_name": f"omni://topic/{topic_data.get('id')}->omni://schemamodel/{topic_data.get('schema_model_id')}"
                }
            })
        
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.TOPIC,
            attributes={
                "name": topic_data.get("name", "Unknown Topic"),
                "qualified_name": f"omni://topic/{topic_data.get('id')}",
                "description": topic_data.get("description", ""),
                "omni_topic_id": topic_data.get("id"),
                "omni_topic_type": "virtual_data_mart",  # As per Omni definition
                "omni_use_case": topic_data.get("use_case", ""),
            },
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def map_shared_model(shared_model_data: Dict[str, Any], branch: Optional[str] = None) -> Dict[str, Any]:
        """Map Shared Model to Atlan asset"""
        asset_type = OmniAssetType.SHARED_MODEL
        if branch == "main":
            asset_type = OmniAssetType.SHARED_MODEL_MAIN
        elif branch:
            asset_type = OmniAssetType.SHARED_MODEL_BRANCH
        
        relationships = []
        
        # Link to Connection if available
        connection_id = shared_model_data.get("connectionId")
        if connection_id:
            relationships.append({
                "type_name": "OmniSharedModelToConnection",
                "attributes": {
                    "qualified_name": f"omni://sharedmodel/{shared_model_data.get('id')}->omni://connection/{connection_id}"
                }
            })
        
        # Link to Topic if available
        if shared_model_data.get("topic_id"):
            relationships.append({
                "type_name": "OmniSharedModelToTopic",
                "attributes": {
                    "qualified_name": f"omni://sharedmodel/{shared_model_data.get('id')}->omni://topic/{shared_model_data.get('topic_id')}"
                }
            })
        
        attributes = {
            "name": shared_model_data.get("name", "Unknown Shared Model"),
            "qualified_name": f"omni://sharedmodel/{shared_model_data.get('id')}",
            "description": shared_model_data.get("description", ""),
            "omni_shared_model_id": shared_model_data.get("id"),
            "omni_connection_id": connection_id,
            "omni_branch": branch or "main",
        }
        
        if branch:
            attributes["qualified_name"] = f"omni://sharedmodel/{shared_model_data.get('id')}/branch/{branch}"
        
        return MetaModelMapper.create_asset_definition(
            asset_type=asset_type,
            attributes=attributes,
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def map_workbook_model(workbook_model_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Workbook Model to Atlan asset"""
        relationships = []
        
        # Link to Connection if available
        connection_id = workbook_model_data.get("connectionId")
        if connection_id:
            relationships.append({
                "type_name": "OmniWorkbookModelToConnection",
                "attributes": {
                    "qualified_name": f"omni://workbookmodel/{workbook_model_data.get('id')}->omni://connection/{connection_id}"
                }
            })
        
        # Link to Shared Model if available
        if workbook_model_data.get("shared_model_id"):
            relationships.append({
                "type_name": "OmniWorkbookModelToSharedModel",
                "attributes": {
                    "qualified_name": f"omni://workbookmodel/{workbook_model_data.get('id')}->omni://sharedmodel/{workbook_model_data.get('shared_model_id')}"
                }
            })
        
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.WORKBOOK_MODEL,
            attributes={
                "name": workbook_model_data.get("name", "Unknown Workbook Model"),
                "qualified_name": f"omni://workbookmodel/{workbook_model_data.get('id')}",
                "description": workbook_model_data.get("description", ""),
                "omni_workbook_model_id": workbook_model_data.get("id"),
                "omni_connection_id": connection_id,
            },
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def map_workbook_tab(workbook_tab_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Workbook Tab to Atlan asset"""
        relationships = []
        
        # Link to Workbook Model if available
        if workbook_tab_data.get("workbook_model_id"):
            relationships.append({
                "type_name": "OmniWorkbookTabToWorkbookModel",
                "attributes": {
                    "qualified_name": f"omni://workbooktab/{workbook_tab_data.get('id')}->omni://workbookmodel/{workbook_tab_data.get('workbook_model_id')}"
                }
            })
        
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.WORKBOOK_TAB,
            attributes={
                "name": workbook_tab_data.get("name", "Unknown Workbook Tab"),
                "qualified_name": f"omni://workbooktab/{workbook_tab_data.get('id')}",
                "description": workbook_tab_data.get("description", ""),
                "omni_workbook_tab_id": workbook_tab_data.get("id"),
            },
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def map_dashboard_tile(dashboard_tile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Dashboard Tile to Atlan asset"""
        relationships = []
        
        # Link to Workbook Tab if available
        if dashboard_tile_data.get("workbook_tab_id"):
            relationships.append({
                "type_name": "OmniDashboardTileToWorkbookTab",
                "attributes": {
                    "qualified_name": f"omni://dashboardtile/{dashboard_tile_data.get('id')}->omni://workbooktab/{dashboard_tile_data.get('workbook_tab_id')}"
                }
            })
        
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.DASHBOARD_TILE,
            attributes={
                "name": dashboard_tile_data.get("name", "Unknown Dashboard Tile"),
                "qualified_name": f"omni://dashboardtile/{dashboard_tile_data.get('id')}",
                "description": dashboard_tile_data.get("description", ""),
                "omni_dashboard_tile_id": dashboard_tile_data.get("id"),
            },
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def map_dashboard(dashboard_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Dashboard to Atlan asset"""
        relationships = []
        identifier = dashboard_data.get("identifier") or dashboard_data.get("id")
        
        # Link to Dashboard Tiles if available
        tile_ids = dashboard_data.get("tile_ids", [])
        for tile_id in tile_ids:
            relationships.append({
                "type_name": "OmniDashboardToDashboardTile",
                "attributes": {
                    "qualified_name": f"omni://dashboard/{identifier}->omni://dashboardtile/{tile_id}"
                }
            })
        
        return MetaModelMapper.create_asset_definition(
            asset_type=OmniAssetType.DASHBOARD,
            attributes={
                "name": dashboard_data.get("name", "Unknown Dashboard"),
                "qualified_name": f"omni://dashboard/{identifier}",
                "description": dashboard_data.get("description", ""),
                "omni_dashboard_id": identifier,
                "omni_connection_id": dashboard_data.get("connectionId"),
                "omni_folder_id": dashboard_data.get("folder", {}).get("id") if dashboard_data.get("folder") else None,
                "omni_folder_name": dashboard_data.get("folder", {}).get("name") if dashboard_data.get("folder") else None,
                "omni_owner_id": dashboard_data.get("owner", {}).get("id") if dashboard_data.get("owner") else None,
                "omni_owner_name": dashboard_data.get("owner", {}).get("name") if dashboard_data.get("owner") else None,
                "omni_scope": dashboard_data.get("scope"),
                "omni_updated_at": dashboard_data.get("updatedAt"),
            },
            relationships=relationships if relationships else None
        )
    
    @staticmethod
    def create_lineage_mapping(
        upstream_assets: List[Dict[str, Any]],
        downstream_assets: List[Dict[str, Any]],
        transformation_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create lineage mapping for Atlan team to build lineage graphs
        
        Args:
            upstream_assets: List of upstream asset qualified names
            downstream_assets: List of downstream asset qualified names
            transformation_type: Type of transformation (e.g., "query", "view", "join")
        
        Returns:
            Lineage mapping structure
        """
        return {
            "upstream": [asset.get("attributes", {}).get("qualified_name") for asset in upstream_assets],
            "downstream": [asset.get("attributes", {}).get("qualified_name") for asset in downstream_assets],
            "transformation_type": transformation_type,
        }
    
    @staticmethod
    def create_meta_model_extension_spec() -> Dict[str, Any]:
        """
        Create meta model extension specification for Atlan team
        
        This defines the asset types and attributes needed in Atlan's meta model
        """
        return {
            "asset_types": [
                {
                    "type_name": "OmniDataWarehouseSchema",
                    "display_name": "Omni Data Warehouse Schema",
                    "description": "Data warehouse schema from Omni connection",
                    "parent_type": "Connection",  # Assuming Atlan has a Connection type
                },
                {
                    "type_name": "OmniSchemaModel",
                    "display_name": "Omni Schema Model",
                    "description": "Schema model defined in YAML files",
                    "parent_type": "Asset",
                },
                {
                    "type_name": "OmniTopic",
                    "display_name": "Omni Topic",
                    "description": "Virtual data mart or data domain - use case specific subset of tables and joins",
                    "parent_type": "DataDomain",  # If Atlan has DataDomain type
                },
                {
                    "type_name": "OmniSharedModel",
                    "display_name": "Omni Shared Model",
                    "description": "Shared model used across workbooks",
                    "parent_type": "Asset",
                },
                {
                    "type_name": "OmniWorkbookModel",
                    "display_name": "Omni Workbook Model",
                    "description": "Model specific to a workbook",
                    "parent_type": "Asset",
                },
                {
                    "type_name": "OmniWorkbookTab",
                    "display_name": "Omni Workbook Tab",
                    "description": "Tab within a workbook",
                    "parent_type": "Asset",
                },
                {
                    "type_name": "OmniDashboardTile",
                    "display_name": "Omni Dashboard Tile",
                    "description": "Tile within a dashboard",
                    "parent_type": "Asset",
                },
                {
                    "type_name": "OmniDashboard",
                    "display_name": "Omni Dashboard",
                    "description": "Dashboard in Omni",
                    "parent_type": "Asset",
                },
                {
                    "type_name": "OmniWorkbook",
                    "display_name": "Omni Workbook",
                    "description": "Saved workbook in Omni",
                    "parent_type": "Asset",
                },
            ],
            "relationship_types": [
                {
                    "type_name": "OmniSchemaModelToDataWarehouse",
                    "display_name": "Schema Model to Data Warehouse",
                    "description": "Links schema model to underlying data warehouse schema",
                },
                {
                    "type_name": "OmniTopicToSchemaModel",
                    "display_name": "Topic to Schema Model",
                    "description": "Links topic to its schema model",
                },
                {
                    "type_name": "OmniSharedModelToTopic",
                    "display_name": "Shared Model to Topic",
                    "description": "Links shared model to topic",
                },
                {
                    "type_name": "OmniWorkbookModelToSharedModel",
                    "display_name": "Workbook Model to Shared Model",
                    "description": "Links workbook model to shared model",
                },
                {
                    "type_name": "OmniWorkbookTabToWorkbookModel",
                    "display_name": "Workbook Tab to Workbook Model",
                    "description": "Links workbook tab to workbook model",
                },
                {
                    "type_name": "OmniDashboardTileToWorkbookTab",
                    "display_name": "Dashboard Tile to Workbook Tab",
                    "description": "Links dashboard tile to workbook tab",
                },
                {
                    "type_name": "OmniDashboardToDashboardTile",
                    "display_name": "Dashboard to Dashboard Tile",
                    "description": "Links dashboard to its tiles",
                },
                {
                    "type_name": "OmniDocumentToWorkbookModel",
                    "display_name": "Document to Workbook Model",
                    "description": "Links document (dashboard/workbook) to its workbook model",
                },
                {
                    "type_name": "OmniQueryToDocument",
                    "display_name": "Query to Document",
                    "description": "Links query to its document (dashboard/workbook)",
                },
                {
                    "type_name": "OmniDocumentToConnection",
                    "display_name": "Document to Connection",
                    "description": "Links document (dashboard/workbook) to its connection",
                },
                {
                    "type_name": "OmniSharedModelToConnection",
                    "display_name": "Shared Model to Connection",
                    "description": "Links shared model to its connection",
                },
                {
                    "type_name": "OmniWorkbookModelToConnection",
                    "display_name": "Workbook Model to Connection",
                    "description": "Links workbook model to its connection",
                },
            ],
            "custom_attributes": {
                "omni_schema_id": {"type": "string", "description": "Omni schema ID"},
                "omni_topic_id": {"type": "string", "description": "Omni topic ID"},
                "omni_shared_model_id": {"type": "string", "description": "Omni shared model ID"},
                "omni_workbook_model_id": {"type": "string", "description": "Omni workbook model ID"},
                "omni_workbook_tab_id": {"type": "string", "description": "Omni workbook tab ID"},
                "omni_dashboard_tile_id": {"type": "string", "description": "Omni dashboard tile ID"},
                "omni_dashboard_id": {"type": "string", "description": "Omni dashboard ID"},
                "omni_branch": {"type": "string", "description": "Branch name (main, branch, etc.)"},
                "omni_yaml_file_path": {"type": "string", "description": "Path to YAML file"},
                "omni_metadata_source": {"type": "string", "description": "Source of metadata"},
                "omni_topic_type": {"type": "string", "description": "Type of topic"},
                "omni_use_case": {"type": "string", "description": "Use case for the topic"},
            }
        }

