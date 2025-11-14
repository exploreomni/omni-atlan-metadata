"""Temporal worker for running Omni-Atlan workflows"""

import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from omni_atlan.workflows import (
    SyncOmniMetadataWorkflow,
    IncrementalSyncWorkflow,
    extract_all_metadata_activity,
    extract_topics_activity,
    extract_queries_activity,
    extract_documents_activity,
    extract_connections_activity,
    ingest_to_atlan_activity
)
from omni_atlan.config import get_temporal_config


async def main():
    """Main entry point for the Temporal worker"""
    temporal_config = get_temporal_config()
    
    # Connect to Temporal
    client = await Client.connect(
        f"{temporal_config.host}",
        namespace=temporal_config.namespace
    )
    
    # Create worker
    worker = Worker(
        client,
        task_queue="omni-atlan-sync",
        workflows=[
            SyncOmniMetadataWorkflow,
            IncrementalSyncWorkflow,
        ],
        activities=[
            extract_all_metadata_activity,
            extract_topics_activity,
            extract_queries_activity,
            extract_documents_activity,
            extract_connections_activity,
            ingest_to_atlan_activity,
        ],
    )
    
    print("Starting Omni-Atlan sync worker...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

