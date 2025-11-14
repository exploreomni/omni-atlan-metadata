"""Extract and transform metadata from Omni for Atlan ingestion

This module extracts metadata following Omni's hierarchical structure:
- Data Warehouse Schema (bottom)
- Schema Model (from YAML)
- Topics (virtual data marts)
- Shared Model (with Branch/Main)
- Workbook Model
- Workbook Tab
- Dashboard Tile
- Dashboard (top)

The output is formatted for Atlan team to use for:
- Asset profile design
- Lineage graph construction
- Meta model extensions
- Publishing
"""

from typing import List, Dict, Any, Optional
from omni_atlan.omni_client import OmniClient
from omni_atlan.meta_model_mapper import MetaModelMapper, OmniAssetType


class MetadataExtractor:
    """Extract metadata from Omni and transform it for Atlan using meta model mapper"""
    
    def __init__(self, omni_client: OmniClient):
        self.omni_client = omni_client
        self.mapper = MetaModelMapper()
    
    def extract_full_hierarchy(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract the focused Omni hierarchy:
        - Connections (map to models)
        - Shared Models (base models)
        - Topics (from model IDs)
        - Documents (Dashboards/Workbooks)
        - Workbook Models (only those associated with documents)
        - Queries (from documents)
        
        Returns:
            Dictionary with all asset types organized by hierarchy level
        """
        print("\nExtracting focused metadata hierarchy:")
        print("=" * 60)
        
        print("\n1. Connections...")
        connections = self.extract_connections_as_assets()
        print(f"   ✓ {len(connections)} connection(s)")
        
        print("\n2. Shared Models (base models)...")
        shared_models = self.extract_shared_models()
        print(f"   ✓ {len(shared_models)} shared model(s)")
        
        print("\n3. Topics (from model IDs)...")
        topics = self.extract_topics_from_models()
        print(f"   ✓ {len(topics)} topic(s)")
        
        print("\n4. Documents (Dashboards & Saved Workbooks)...")
        documents = self.extract_documents_as_assets()
        dashboards = self.extract_dashboards()
        workbooks = self.extract_workbooks()
        print(f"   ✓ {len(documents)} document(s), {len(dashboards)} dashboard(s), {len(workbooks)} workbook(s)")
        
        print("\n5. Workbook Models (only from documents)...")
        workbook_models = self.extract_workbook_models_from_documents(documents)
        print(f"   ✓ {len(workbook_models)} workbook model(s) from documents")
        
        print("\n6. Queries (from documents)...")
        queries = self.extract_queries_as_assets()
        print(f"   ✓ {len(queries)} query/queries")
        
        print("\n" + "=" * 60)
        
        return {
            "data_warehouse_schemas": [],  # Not focusing on this
            "schema_models": [],  # Not focusing on this
            "topics": topics,
            "shared_models": shared_models,
            "workbook_models": workbook_models,  # Only from documents
            "workbook_tabs": [],
            "dashboard_tiles": [],
            "dashboards": dashboards,
            "workbooks": workbooks,
            "queries": queries,
            "documents": documents,
            "connections": connections,
        }
    
    def extract_data_warehouse_schemas(self) -> List[Dict[str, Any]]:
        """Extract Data Warehouse Schemas (bottom layer)"""
        # Note: This may need to come from connections or a separate endpoint
        connections = self.omni_client.get_connections()
        schemas = []
        
        for connection in connections:
            # Assuming connection contains schema information
            # Adjust based on actual API response
            schema_data = {
                "id": f"{connection.get('id')}_schema",
                "name": connection.get("name", "Unknown Schema"),
                "description": connection.get("description", ""),
                "connection_id": connection.get("id"),
            }
            schemas.append(self.mapper.map_data_warehouse_schema(schema_data))
        
        return schemas
    
    def extract_schema_models(self) -> List[Dict[str, Any]]:
        """Extract Schema Models (from YAML metadata)"""
        print("    Fetching schema models...")
        schema_models = self.omni_client.get_schema_models()
        print(f"    Found {len(schema_models)} schema model(s)")
        assets = []
        
        for model in schema_models:
            assets.append(self.mapper.map_schema_model(model))
        
        return assets
    
    def extract_topics_from_models(self) -> List[Dict[str, Any]]:
        """Extract Topics (virtual data marts/domains) - topics are associated with models"""
        print("    Fetching topics from models...")
        # Get all models (shared and workbook models)
        all_models = []
        
        # Get shared models
        shared_models = self.omni_client.get_shared_models()
        all_models.extend(shared_models)
        
        # Get workbook models from documents
        documents = self.omni_client.get_documents()
        workbook_model_ids = set()
        for document in documents:
            model_id = document.get("modelId") or document.get("workbookModelId") or document.get("baseModelId")
            if model_id:
                workbook_model_ids.add(model_id)
        
        # Get workbook models
        workbook_models = self.omni_client.get_workbook_models()
        for wb_model in workbook_models:
            if wb_model.get("id") in workbook_model_ids:
                all_models.append(wb_model)
        
        print(f"    Found {len(all_models)} model(s), fetching topics for each...")
        all_topics = []
        seen_topic_ids = set()
        
        # Get topics for each model
        for idx, model in enumerate(all_models, 1):
            model_id = model.get("id")
            model_name = model.get("name", model_id)
            if model_id:
                print(f"      [{idx}/{len(all_models)}] Fetching topics for model: {model_name}")
                topics = self.omni_client.get_topics(model_id=model_id)
                print(f"        Found {len(topics)} topic(s)")
                for topic in topics:
                    topic_id = topic.get("id")
                    if topic_id and topic_id not in seen_topic_ids:
                        # Add model_id to topic for relationship mapping
                        topic["model_id"] = model_id
                        topic["model_kind"] = model.get("modelKind")
                        all_topics.append(topic)
                        seen_topic_ids.add(topic_id)
        
        print(f"    Total unique topics: {len(all_topics)}")
        assets = []
        for topic in all_topics:
            assets.append(self.mapper.map_topic(topic))
        
        return assets
    
    def extract_shared_models(self) -> List[Dict[str, Any]]:
        """Extract Shared Models (with Branch/Main versions)"""
        print("    Fetching shared models...")
        shared_models = self.omni_client.get_shared_models(include_branches=True)
        print(f"    Found {len(shared_models)} shared model(s)")
        assets = []
        
        for model in shared_models:
            # Check if model has branches
            branches = model.get("branches", [])
            if branches:
                # Map each branch
                for branch in branches:
                    branch_name = branch.get("name", "main")
                    assets.append(self.mapper.map_shared_model(model, branch=branch_name))
            else:
                # Map main model
                assets.append(self.mapper.map_shared_model(model, branch="main"))
        
        return assets
    
    def extract_workbook_models_from_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract Workbook Models only from documents (not standalone throwaway models)
        
        Args:
            documents: List of document assets (dashboards/workbooks) that may reference workbook models
        
        Returns:
            List of workbook model assets that are associated with documents
        """
        print("    Extracting workbook models from documents...")
        
        # Get raw documents from API to check for model references
        raw_documents = self.omni_client.get_documents()
        
        # Collect unique workbook model IDs from documents
        workbook_model_ids = set()
        for document in raw_documents:
            # Documents may have modelId, workbookModelId, or baseModelId
            model_id = document.get("modelId") or document.get("workbookModelId") or document.get("baseModelId")
            if model_id:
                workbook_model_ids.add(model_id)
        
        if not workbook_model_ids:
            print("    No workbook models found in documents")
            return []
        
        print(f"    Found {len(workbook_model_ids)} unique workbook model ID(s) in documents")
        
        # Get all workbook models and filter to only those in documents
        all_workbook_models = self.omni_client.get_workbook_models()
        relevant_models = [m for m in all_workbook_models if m.get("id") in workbook_model_ids]
        
        print(f"    Mapped {len(relevant_models)} workbook model(s) from documents")
        
        assets = []
        for model in relevant_models:
            assets.append(self.mapper.map_workbook_model(model))
        
        return assets
    
    def extract_workbook_models(self) -> List[Dict[str, Any]]:
        """Extract Workbook Models - DEPRECATED: Use extract_workbook_models_from_documents instead"""
        return []
    
    def extract_workbook_tabs(self) -> List[Dict[str, Any]]:
        """Extract Workbook Tabs - Not available as separate endpoint, extracted from documents"""
        # Workbook tabs are part of documents, not a separate endpoint
        return []
    
    def extract_dashboard_tiles(self) -> List[Dict[str, Any]]:
        """Extract Dashboard Tiles - Not available as separate endpoint, extracted from documents"""
        # Dashboard tiles are part of documents, not a separate endpoint
        return []
    
    def extract_dashboards(self) -> List[Dict[str, Any]]:
        """Extract Dashboards from documents (hasDashboard: true)"""
        documents = self.omni_client.get_documents()
        assets = []
        
        for document in documents:
            # Dashboards have hasDashboard: true
            if document.get("hasDashboard", False):
                identifier = document.get("identifier")
                if identifier:
                    asset = self.mapper.map_dashboard(document)
                    # Update to use identifier instead of id
                    if "attributes" in asset:
                        asset["attributes"]["qualified_name"] = f"omni://dashboard/{identifier}"
                        asset["attributes"]["omni_document_id"] = identifier
                    assets.append(asset)
        
        return assets
    
    def extract_workbooks(self) -> List[Dict[str, Any]]:
        """Extract Saved Workbooks from documents (hasDashboard: false)"""
        documents = self.omni_client.get_documents()
        assets = []
        
        for document in documents:
            # Workbooks have hasDashboard: false
            if not document.get("hasDashboard", True):  # Default to True to be safe
                identifier = document.get("identifier")
                if identifier:
                    # Map as saved workbook
                    asset = self.mapper.create_asset_definition(
                        asset_type=OmniAssetType.WORKBOOK,
                        attributes={
                            "name": document.get("name", "Unknown Workbook"),
                            "qualified_name": f"omni://workbook/{identifier}",
                            "description": document.get("description", ""),
                            "omni_workbook_id": identifier,
                            "omni_connection_id": document.get("connectionId"),
                            "omni_folder_id": document.get("folder", {}).get("id") if document.get("folder") else None,
                            "omni_folder_name": document.get("folder", {}).get("name") if document.get("folder") else None,
                            "omni_owner_id": document.get("owner", {}).get("id") if document.get("owner") else None,
                            "omni_owner_name": document.get("owner", {}).get("name") if document.get("owner") else None,
                            "omni_scope": document.get("scope"),
                            "omni_updated_at": document.get("updatedAt"),
                        },
                        relationships=self._build_document_relationships(document)
                    )
                    assets.append(asset)
        
        return assets
    
    def extract_queries_as_assets(self, topic_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extract Queries - Queries come from documents"""
        # Get all documents
        documents = self.omni_client.get_documents()
        all_queries = []
        
        print(f"    Fetching queries from {len(documents)} document(s)...")
        # Get queries from each document using identifier
        for idx, document in enumerate(documents, 1):
            identifier = document.get("identifier")
            doc_name = document.get("name", identifier or "Unknown")
            if identifier:
                print(f"    [{idx}/{len(documents)}] Fetching queries from: {doc_name}")
                queries = self.omni_client.get_document_queries(identifier)
                print(f"      Found {len(queries)} query/queries")
                for query in queries:
                    # Add document identifier to query for relationship mapping
                    query["document_identifier"] = identifier
                all_queries.extend(queries)
        
        assets = []
        for query in all_queries:
            query_id = query.get("id")
            query_obj = query.get("query", {})  # Query object contains fields, table, etc.
            
            asset = self.mapper.create_asset_definition(
                asset_type=OmniAssetType.QUERY,
                attributes={
                    "name": query.get("name", "Unknown Query"),
                    "qualified_name": f"omni://query/{query_id}",
                    "description": query.get("description", ""),
                    "omni_query_id": query_id,
                    "omni_document_id": query.get("document_identifier"),
                    "omni_table": query_obj.get("table", ""),  # Table used in query
                    "omni_fields_used": query_obj.get("fields", []),  # Fields used in the query
                    "omni_query_limit": query_obj.get("limit"),
                    "omni_query_sorts": query_obj.get("sorts", []),
                    "omni_query_filters": query_obj.get("filters", {}),
                },
                relationships=self._build_query_relationships(query) if query.get("document_identifier") else None
            )
            assets.append(asset)
        
        return assets
    
    def extract_documents_as_assets(self, topic_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extract Documents (dashboards and workbooks)"""
        print("    Fetching documents (dashboards & workbooks)...")
        documents = self.omni_client.get_documents()
        print(f"    Found {len(documents)} document(s)")
        assets = []
        
        for document in documents:
            # Use hasDashboard to distinguish: true = dashboard, false = workbook
            has_dashboard = document.get("hasDashboard", False)
            identifier = document.get("identifier")
            
            if not identifier:
                continue  # Skip documents without identifier
            
            # Determine document type
            doc_type = "dashboard" if has_dashboard else "workbook"
            
            asset = self.mapper.create_asset_definition(
                asset_type=OmniAssetType.DOCUMENT,
                attributes={
                    "name": document.get("name", "Unknown Document"),
                    "qualified_name": f"omni://document/{identifier}",
                    "description": document.get("description", ""),
                    "omni_document_id": identifier,
                    "omni_document_type": doc_type,
                    "omni_connection_id": document.get("connectionId"),
                    "omni_folder_id": document.get("folder", {}).get("id") if document.get("folder") else None,
                    "omni_folder_name": document.get("folder", {}).get("name") if document.get("folder") else None,
                    "omni_owner_id": document.get("owner", {}).get("id") if document.get("owner") else None,
                    "omni_owner_name": document.get("owner", {}).get("name") if document.get("owner") else None,
                    "omni_scope": document.get("scope"),
                    "omni_updated_at": document.get("updatedAt"),
                },
                relationships=self._build_document_relationships(document)
            )
            assets.append(asset)
        
        return assets
    
    def extract_connections_as_assets(self) -> List[Dict[str, Any]]:
        """Extract Connections"""
        connections = self.omni_client.get_connections()
        assets = []
        
        for connection in connections:
            asset = self.mapper.create_asset_definition(
                asset_type=OmniAssetType.CONNECTION,
                attributes={
                    "name": connection.get("name", "Unknown Connection"),
                    "qualified_name": f"omni://connection/{connection.get('id')}",
                    "description": connection.get("description", ""),
                    "omni_connection_id": connection.get("id"),
                    "omni_dialect": connection.get("dialect", ""),  # postgres, mysql, etc.
                    "omni_database": connection.get("database", ""),
                    "omni_default_schema": connection.get("defaultSchema", ""),
                    "omni_deleted_at": connection.get("deletedAt"),
                    "omni_user_attribute_name_for_connection_environments": connection.get("userAttributeNameForConnectionEnvironments"),
                    "omni_branch_connection_environment_overrides_user_attr": connection.get("branchConnectionEnvironmentOverridesUserAttr", False),
                    "omni_environment_connection_switches_schema_model": connection.get("environmentConnectionSwitchesSchemaModel", False),
                }
            )
            assets.append(asset)
        
        return assets
    
    def _build_query_relationships(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build relationships for a query"""
        relationships = []
        query_id = query.get("id") or query.get("identifier")
        # Link query to document
        if query.get("document_identifier"):
            relationships.append({
                "type_name": "OmniQueryToDocument",
                "attributes": {
                    "qualified_name": f"omni://query/{query_id}->omni://document/{query.get('document_identifier')}"
                }
            })
        # Link query to topic if available
        if query.get("topic_id"):
            relationships.append({
                "type_name": "OmniQueryToTopic",
                "attributes": {
                    "qualified_name": f"omni://query/{query_id}->omni://topic/{query.get('topic_id')}"
                }
            })
        return relationships
    
    def _build_document_relationships(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build relationships for a document"""
        relationships = []
        identifier = document.get("identifier")
        if not identifier:
            return relationships
        
        # Link document to connection
        connection_id = document.get("connectionId")
        if connection_id:
            relationships.append({
                "type_name": "OmniDocumentToConnection",
                "attributes": {
                    "qualified_name": f"omni://document/{identifier}->omni://connection/{connection_id}"
                }
            })
        
        # Link document to workbook model if it has one
        model_id = document.get("modelId") or document.get("workbookModelId") or document.get("baseModelId")
        if model_id:
            # Check if it's a workbook model or shared model
            # For now, assume workbook model if it exists
            relationships.append({
                "type_name": "OmniDocumentToWorkbookModel",
                "attributes": {
                    "qualified_name": f"omni://document/{identifier}->omni://workbookmodel/{model_id}"
                }
            })
        # Documents may have relationships to topics
        if document.get("topic_id"):
            relationships.append({
                "type_name": "OmniDocumentToTopic",
                "attributes": {
                    "qualified_name": f"omni://document/{identifier}->omni://topic/{document.get('topic_id')}"
                }
            })
        return relationships
    
    def extract_all_metadata(self) -> Dict[str, List[Dict[str, Any]]]:
        """Extract all metadata types from Omni (legacy method for backward compatibility)"""
        return self.extract_full_hierarchy()
    
    def create_output_for_atlan_team(self) -> Dict[str, Any]:
        """
        Create formatted output for Atlan team to use for design work
        
        This output includes:
        - All assets organized by type
        - Meta model extension specification
        - Lineage mappings
        - Relationship definitions
        """
        hierarchy = self.extract_full_hierarchy()
        
        # Create lineage mappings
        lineage_mappings = self._create_lineage_mappings(hierarchy)
        
        return {
            "metadata": hierarchy,
            "meta_model_extension_spec": self.mapper.create_meta_model_extension_spec(),
            "lineage_mappings": lineage_mappings,
            "summary": {
                "total_assets": sum(len(assets) for assets in hierarchy.values()),
                "by_type": {key: len(assets) for key, assets in hierarchy.items()}
            }
        }
    
    def _create_lineage_mappings(self, hierarchy: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Create lineage mappings from the hierarchy"""
        mappings = []
        
        # Map Schema Model -> Data Warehouse Schema
        for schema_model in hierarchy.get("schema_models", []):
            # Extract relationships if they exist
            if "relationships" in schema_model:
                for rel in schema_model["relationships"]:
                    if "DataWarehouse" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [schema_model.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "schema_model"
                        })
        
        # Map Topic -> Schema Model
        for topic in hierarchy.get("topics", []):
            if "relationships" in topic:
                for rel in topic["relationships"]:
                    if "SchemaModel" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [topic.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "topic"
                        })
        
        # Map Shared Model -> Topic
        for shared_model in hierarchy.get("shared_models", []):
            if "relationships" in shared_model:
                for rel in shared_model["relationships"]:
                    if "Topic" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [shared_model.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "shared_model"
                        })
        
        # Map Workbook Model -> Shared Model
        for workbook_model in hierarchy.get("workbook_models", []):
            if "relationships" in workbook_model:
                for rel in workbook_model["relationships"]:
                    if "SharedModel" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [workbook_model.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "workbook_model"
                        })
        
        # Map Workbook Tab -> Workbook Model
        for workbook_tab in hierarchy.get("workbook_tabs", []):
            if "relationships" in workbook_tab:
                for rel in workbook_tab["relationships"]:
                    if "WorkbookModel" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [workbook_tab.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "workbook_tab"
                        })
        
        # Map Dashboard Tile -> Workbook Tab
        for dashboard_tile in hierarchy.get("dashboard_tiles", []):
            if "relationships" in dashboard_tile:
                for rel in dashboard_tile["relationships"]:
                    if "WorkbookTab" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [dashboard_tile.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "dashboard_tile"
                        })
        
        # Map Dashboard -> Dashboard Tiles
        for dashboard in hierarchy.get("dashboards", []):
            if "relationships" in dashboard:
                tile_qns = []
                for rel in dashboard["relationships"]:
                    if "DashboardTile" in rel.get("type_name", ""):
                        tile_qns.append(rel.get("attributes", {}).get("qualified_name", "").split("->")[-1])
                if tile_qns:
                    mappings.append({
                        "upstream": tile_qns,
                        "downstream": [dashboard.get("attributes", {}).get("qualified_name")],
                        "transformation_type": "dashboard"
                    })
        
        # Map Document -> Workbook Model
        for document in hierarchy.get("documents", []):
            if "relationships" in document:
                for rel in document["relationships"]:
                    if "WorkbookModel" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [document.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "document"
                        })
        
        # Map Workbook -> Workbook Model
        for workbook in hierarchy.get("workbooks", []):
            if "relationships" in workbook:
                for rel in workbook["relationships"]:
                    if "WorkbookModel" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [workbook.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "workbook"
                        })
        
        # Map Query -> Document
        for query in hierarchy.get("queries", []):
            if "relationships" in query:
                for rel in query["relationships"]:
                    if "Document" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [query.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "query"
                        })
        
        # Map Document -> Connection
        for document in hierarchy.get("documents", []):
            if "relationships" in document:
                for rel in document["relationships"]:
                    if "Connection" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [document.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "document_to_connection"
                        })
        
        # Map Shared Model -> Connection
        for shared_model in hierarchy.get("shared_models", []):
            if "relationships" in shared_model:
                for rel in shared_model["relationships"]:
                    if "Connection" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [shared_model.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "shared_model_to_connection"
                        })
        
        # Map Workbook Model -> Connection
        for workbook_model in hierarchy.get("workbook_models", []):
            if "relationships" in workbook_model:
                for rel in workbook_model["relationships"]:
                    if "Connection" in rel.get("type_name", ""):
                        mappings.append({
                            "upstream": [rel.get("attributes", {}).get("qualified_name", "").split("->")[-1]],
                            "downstream": [workbook_model.get("attributes", {}).get("qualified_name")],
                            "transformation_type": "workbook_model_to_connection"
                        })
        
        return mappings
