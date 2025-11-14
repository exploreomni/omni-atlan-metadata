"""Format metadata output for Atlan team

This module formats the extracted metadata in a way that's easy for
the Atlan team to use for:
- Asset profile design
- Lineage graph construction
- Meta model extensions
- Publishing
"""

import json
from typing import Dict, Any, List
from datetime import datetime


class OutputFormatter:
    """Format metadata output for Atlan team consumption"""
    
    @staticmethod
    def format_for_atlan_team(
        metadata_output: Dict[str, Any],
        output_format: str = "json"
    ) -> str:
        """
        Format the metadata output for Atlan team
        
        Args:
            metadata_output: Output from MetadataExtractor.create_output_for_atlan_team()
            output_format: Output format ('json', 'pretty_json')
        
        Returns:
            Formatted string
        """
        if output_format == "pretty_json":
            return json.dumps(metadata_output, indent=2, default=str)
        else:
            return json.dumps(metadata_output, default=str)
    
    @staticmethod
    def create_meta_model_spec_file(metadata_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a standalone meta model specification file
        
        This can be used by Atlan team to understand what extensions are needed
        """
        return {
            "specification_version": "1.0",
            "created_at": datetime.utcnow().isoformat(),
            "source": "Omni Integration",
            "meta_model_extension": metadata_output.get("meta_model_extension_spec", {}),
            "asset_type_summary": metadata_output.get("summary", {}).get("by_type", {}),
        }
    
    @staticmethod
    def create_lineage_spec_file(metadata_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a standalone lineage specification file
        
        This can be used by Atlan team to build lineage graphs
        """
        return {
            "specification_version": "1.0",
            "created_at": datetime.utcnow().isoformat(),
            "source": "Omni Integration",
            "lineage_mappings": metadata_output.get("lineage_mappings", []),
            "total_lineage_edges": len(metadata_output.get("lineage_mappings", [])),
        }
    
    @staticmethod
    def create_asset_profile_spec(metadata_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create asset profile specifications for Atlan team
        
        This helps Atlan team design asset profiles
        """
        profiles = {}
        
        for asset_type, assets in metadata_output.get("metadata", {}).items():
            if assets:
                # Use first asset as template
                sample_asset = assets[0]
                profiles[asset_type] = {
                    "type_name": sample_asset.get("type_name"),
                    "required_attributes": list(sample_asset.get("attributes", {}).keys()),
                    "optional_attributes": [],
                    "sample_attributes": sample_asset.get("attributes", {}),
                    "relationship_types": [
                        rel.get("type_name") for rel in sample_asset.get("relationships", [])
                    ] if sample_asset.get("relationships") else [],
                }
        
        return {
            "specification_version": "1.0",
            "created_at": datetime.utcnow().isoformat(),
            "source": "Omni Integration",
            "asset_profiles": profiles,
        }
    
    @staticmethod
    def save_output_files(
        metadata_output: Dict[str, Any],
        output_dir: str = "output"
    ) -> Dict[str, str]:
        """
        Save all output files for Atlan team
        
        Returns:
            Dictionary mapping file type to file path
        """
        import os
        
        os.makedirs(output_dir, exist_ok=True)
        
        files = {}
        
        # Full metadata output
        full_output_path = os.path.join(output_dir, "omni_metadata_full.json")
        with open(full_output_path, "w") as f:
            json.dump(metadata_output, f, indent=2, default=str)
        files["full_metadata"] = full_output_path
        
        # Meta model spec
        meta_model_spec = OutputFormatter.create_meta_model_spec_file(metadata_output)
        meta_model_path = os.path.join(output_dir, "meta_model_spec.json")
        with open(meta_model_path, "w") as f:
            json.dump(meta_model_spec, f, indent=2, default=str)
        files["meta_model_spec"] = meta_model_path
        
        # Lineage spec
        lineage_spec = OutputFormatter.create_lineage_spec_file(metadata_output)
        lineage_path = os.path.join(output_dir, "lineage_spec.json")
        with open(lineage_path, "w") as f:
            json.dump(lineage_spec, f, indent=2, default=str)
        files["lineage_spec"] = lineage_path
        
        # Asset profile spec
        profile_spec = OutputFormatter.create_asset_profile_spec(metadata_output)
        profile_path = os.path.join(output_dir, "asset_profile_spec.json")
        with open(profile_path, "w") as f:
            json.dump(profile_spec, f, indent=2, default=str)
        files["asset_profile_spec"] = profile_path
        
        return files

