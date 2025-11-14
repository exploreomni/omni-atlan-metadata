"""Main entry point for the Omni-Atlan integration application"""

import asyncio
import sys
from temporalio.client import Client
from omni_atlan.workflows import SyncOmniMetadataWorkflow, IncrementalSyncWorkflow
from omni_atlan.config import get_temporal_config


async def run_full_sync():
    """Run a full sync of all metadata from Omni to Atlan"""
    temporal_config = get_temporal_config()
    
    # Connect to Temporal
    client = await Client.connect(
        f"{temporal_config.host}",
        namespace=temporal_config.namespace
    )
    
    # Start workflow
    handle = await client.start_workflow(
        SyncOmniMetadataWorkflow.run,
        "all",
        id="omni-atlan-sync-full",
        task_queue="omni-atlan-sync",
    )
    
    print(f"Started workflow: {handle.id}")
    result = await handle.result()
    print(f"Workflow completed: {result}")
    return result


async def run_incremental_sync(last_sync_timestamp: str):
    """Run an incremental sync from Omni to Atlan"""
    temporal_config = get_temporal_config()
    
    # Connect to Temporal
    client = await Client.connect(
        f"{temporal_config.host}",
        namespace=temporal_config.namespace
    )
    
    # Start workflow
    handle = await client.start_workflow(
        IncrementalSyncWorkflow.run,
        last_sync_timestamp,
        id="omni-atlan-sync-incremental",
        task_queue="omni-atlan-sync",
    )
    
    print(f"Started workflow: {handle.id}")
    result = await handle.result()
    print(f"Workflow completed: {result}")
    return result


def main():
    """Main CLI entry point"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py full-sync          # Run full sync")
        print("  python main.py incremental-sync <timestamp>  # Run incremental sync")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "full-sync":
        asyncio.run(run_full_sync())
    elif command == "incremental-sync":
        if len(sys.argv) < 3:
            print("Error: timestamp required for incremental sync")
            sys.exit(1)
        asyncio.run(run_incremental_sync(sys.argv[2]))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()

