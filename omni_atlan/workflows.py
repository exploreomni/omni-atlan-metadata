"""Temporal workflows for Omni-Atlan integration"""

from temporalio import workflow, activity
from typing import Dict, List, Any


@workflow.defn
class SyncOmniMetadataWorkflow:
    """Workflow to sync metadata from Omni to Atlan"""
    
    @workflow.run
    async def run(self, sync_type: str = "all") -> Dict[str, Any]:
        """
        Sync metadata from Omni to Atlan
        
        Args:
            sync_type: Type of metadata to sync ('all', 'topics', 'queries', 'documents', 'connections')
        
        Returns:
            Dictionary with sync results
        """
        # Extract metadata based on sync type
        if sync_type == "all":
            metadata = await workflow.execute_activity(
                extract_all_metadata_activity,
                sync_type,
                start_to_close_timeout=300
            )
        elif sync_type == "topics":
            metadata = {
                "topics": await workflow.execute_activity(
                    extract_topics_activity,
                    sync_type,
                    start_to_close_timeout=300
                ),
                "queries": [],
                "documents": [],
                "connections": []
            }
        elif sync_type == "queries":
            metadata = {
                "topics": [],
                "queries": await workflow.execute_activity(
                    extract_queries_activity,
                    sync_type,
                    start_to_close_timeout=300
                ),
                "documents": [],
                "connections": []
            }
        elif sync_type == "documents":
            metadata = {
                "topics": [],
                "queries": [],
                "documents": await workflow.execute_activity(
                    extract_documents_activity,
                    sync_type,
                    start_to_close_timeout=300
                ),
                "connections": []
            }
        elif sync_type == "connections":
            metadata = {
                "topics": [],
                "queries": [],
                "documents": [],
                "connections": await workflow.execute_activity(
                    extract_connections_activity,
                    sync_type,
                    start_to_close_timeout=300
                )
            }
        else:
            raise ValueError(f"Unknown sync_type: {sync_type}")
        
        # Ingest metadata into Atlan
        result = await workflow.execute_activity(
            ingest_to_atlan_activity,
            metadata,
            start_to_close_timeout=600
        )
        
        return {
            "status": "success",
            "sync_type": sync_type,
            "assets_synced": sum(len(assets) for assets in metadata.values()),
            "details": metadata,
            "atlan_result": result
        }


@workflow.defn
class IncrementalSyncWorkflow:
    """Workflow for incremental metadata sync from Omni to Atlan"""
    
    @workflow.run
    async def run(self, last_sync_timestamp: str) -> Dict[str, Any]:
        """
        Perform incremental sync of metadata changed since last sync
        
        Args:
            last_sync_timestamp: ISO timestamp of last sync
        
        Returns:
            Dictionary with sync results
        """
        # Extract all metadata (filtering by timestamp would be done in Omni API if supported)
        metadata = await workflow.execute_activity(
            extract_all_metadata_activity,
            "all",
            start_to_close_timeout=300
        )
        
        # Filter by timestamp (if Omni API supports it, this would be done in the client)
        # For now, we'll sync all and let Atlan handle deduplication
        
        # Ingest into Atlan
        result = await workflow.execute_activity(
            ingest_to_atlan_activity,
            metadata,
            start_to_close_timeout=600
        )
        
        return {
            "status": "success",
            "sync_type": "incremental",
            "last_sync_timestamp": last_sync_timestamp,
            "assets_synced": sum(len(assets) for assets in metadata.values()),
            "atlan_result": result
        }


# Activity functions (these are registered with Temporal)
@activity.defn
async def extract_all_metadata_activity(sync_type: str) -> Dict[str, Any]:
    """Activity to extract all metadata from Omni and format for Atlan team"""
    from omni_atlan.metadata_extractor import MetadataExtractor
    from omni_atlan.omni_client import OmniClient
    from omni_atlan.config import get_omni_config
    
    config = get_omni_config()
    omni_client = OmniClient(config)
    extractor = MetadataExtractor(omni_client)
    return extractor.create_output_for_atlan_team()


@activity.defn
async def extract_topics_activity(sync_type: str) -> List[Dict[str, Any]]:
    """Activity to extract topics from Omni"""
    from omni_atlan.metadata_extractor import MetadataExtractor
    from omni_atlan.omni_client import OmniClient
    from omni_atlan.config import get_omni_config
    
    config = get_omni_config()
    omni_client = OmniClient(config)
    extractor = MetadataExtractor(omni_client)
    return extractor.extract_topics_as_assets()


@activity.defn
async def extract_queries_activity(sync_type: str) -> List[Dict[str, Any]]:
    """Activity to extract queries from Omni"""
    from omni_atlan.metadata_extractor import MetadataExtractor
    from omni_atlan.omni_client import OmniClient
    from omni_atlan.config import get_omni_config
    
    config = get_omni_config()
    omni_client = OmniClient(config)
    extractor = MetadataExtractor(omni_client)
    return extractor.extract_queries_as_assets()


@activity.defn
async def extract_documents_activity(sync_type: str) -> List[Dict[str, Any]]:
    """Activity to extract documents from Omni"""
    from omni_atlan.metadata_extractor import MetadataExtractor
    from omni_atlan.omni_client import OmniClient
    from omni_atlan.config import get_omni_config
    
    config = get_omni_config()
    omni_client = OmniClient(config)
    extractor = MetadataExtractor(omni_client)
    return extractor.extract_documents_as_assets()


@activity.defn
async def extract_connections_activity(sync_type: str) -> List[Dict[str, Any]]:
    """Activity to extract connections from Omni"""
    from omni_atlan.metadata_extractor import MetadataExtractor
    from omni_atlan.omni_client import OmniClient
    from omni_atlan.config import get_omni_config
    
    config = get_omni_config()
    omni_client = OmniClient(config)
    extractor = MetadataExtractor(omni_client)
    return extractor.extract_connections_as_assets()


@activity.defn
async def ingest_to_atlan_activity(metadata: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Activity to ingest metadata into Atlan"""
    # This would use the Atlan SDK to create/update assets
    from omni_atlan.config import get_atlan_config
    # Note: Import Atlan SDK when available
    # from atlan import Atlan
    
    config = get_atlan_config()
    # client = Atlan(
    #     base_url=config.base_url,
    #     api_key=config.api_key
    # )
    
    results = {
        "topics_created": 0,
        "queries_created": 0,
        "documents_created": 0,
        "connections_created": 0,
        "errors": []
    }
    
    # Ingest topics
    for topic_asset in metadata.get("topics", []):
        try:
            # Use Atlan SDK to create asset
            # client.assets.create(topic_asset)
            results["topics_created"] += 1
        except Exception as e:
            results["errors"].append(f"Error creating topic: {e}")
    
    # Ingest queries
    for query_asset in metadata.get("queries", []):
        try:
            # Use Atlan SDK to create asset
            # client.assets.create(query_asset)
            results["queries_created"] += 1
        except Exception as e:
            results["errors"].append(f"Error creating query: {e}")
    
    # Ingest documents
    for document_asset in metadata.get("documents", []):
        try:
            # Use Atlan SDK to create asset
            # client.assets.create(document_asset)
            results["documents_created"] += 1
        except Exception as e:
            results["errors"].append(f"Error creating document: {e}")
    
    # Ingest connections
    for connection_asset in metadata.get("connections", []):
        try:
            # Use Atlan SDK to create asset
            # client.assets.create(connection_asset)
            results["connections_created"] += 1
        except Exception as e:
            results["errors"].append(f"Error creating connection: {e}")
    
    return results

