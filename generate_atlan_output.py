"""Generate output files for Atlan team

This script extracts metadata from Omni and creates formatted output files
that the Atlan team can use for:
- Asset profile design
- Lineage graph construction
- Meta model extensions
- Publishing
"""

import asyncio
import sys
from omni_atlan.metadata_extractor import MetadataExtractor
from omni_atlan.omni_client import OmniClient
from omni_atlan.config import get_omni_config
from omni_atlan.output_formatter import OutputFormatter


async def generate_output(output_dir: str = "output"):
    """Generate all output files for Atlan team"""
    print("Starting metadata extraction from Omni...")
    print(f"Omni URL: {get_omni_config().base_url}")
    print()
    
    # Get configuration
    config = get_omni_config()
    omni_client = OmniClient(config)
    extractor = MetadataExtractor(omni_client)
    
    # Test connection first
    print("Testing connection...")
    try:
        connections = omni_client.get_connections()
        print(f"✓ Found {len(connections)} connection(s)")
        if connections:
            print(f"  Sample: {connections[0].get('name', 'N/A')}")
    except Exception as e:
        print(f"⚠ Connection test failed: {e}")
    print()
    
    # Extract and format metadata
    print("Extracting full hierarchy...")
    print("(Rate limiting: ~1 second between requests to stay under 60/min)")
    print()
    import time
    start_time = time.time()
    metadata_output = extractor.create_output_for_atlan_team()
    elapsed = time.time() - start_time
    print(f"\n✓ Extraction completed in {elapsed:.1f} seconds")
    
    # Save output files
    print(f"Saving output files to {output_dir}...")
    files = OutputFormatter.save_output_files(metadata_output, output_dir)
    
    print("\n✅ Output files generated successfully:")
    for file_type, file_path in files.items():
        print(f"  - {file_type}: {file_path}")
    
    print(f"\n📊 Summary:")
    print(f"  - Total assets: {metadata_output['summary']['total_assets']}")
    print(f"  - Asset types: {len(metadata_output['summary']['by_type'])}")
    print(f"  - Lineage mappings: {len(metadata_output['lineage_mappings'])}")
    
    print("\n📋 Asset breakdown:")
    for asset_type, count in metadata_output['summary']['by_type'].items():
        print(f"  - {asset_type}: {count}")
    
    return files


def main():
    """Main entry point"""
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    
    print("=" * 60)
    print("Omni-Atlan Integration - Output Generator")
    print("=" * 60)
    print(f"\nThis script generates output files for Atlan team to use for:")
    print("  - Asset profile design")
    print("  - Lineage graph construction")
    print("  - Meta model extensions")
    print("  - Publishing")
    print()
    
    try:
        files = asyncio.run(generate_output(output_dir))
        print("\n✅ Success! Output files are ready for Atlan team.")
    except Exception as e:
        import traceback
        print(f"\n❌ Error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

