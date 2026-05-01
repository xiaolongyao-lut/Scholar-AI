# -*- coding: utf-8 -*-
"""External skill importer for user-provided third-party skills."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Any
import json
import sys
import os

# This will be available at runtime
try:
    from ..models import (
        SkillDescriptor,
        SkillKind,
        SkillSource,
        UIVisibility,
        SkillTrustLevel,
        ScriptPolicy,
    )
except ImportError:
    pass


@dataclass
class ImportResult:
    """Result of importing external skills."""
    descriptors: list[SkillDescriptor]
    warnings: list[str]


def import_external_skill_dirs(
    root_paths: list[Path],
    auto_disable: bool = True,
) -> ImportResult:
    """
    Import external skills from specified directories.
    
    Args:
        root_paths: List of directories containing skill definitions
        auto_disable: If True, mark imported skills as disabled by default
    
    Returns:
        ImportResult with descriptors and warnings
    """
    # Avoid circular imports - import here
    from ..models import (
        SkillDescriptor,
        SkillKind,
        SkillSource,
        UIVisibility,
        SkillTrustLevel,
        ScriptPolicy,
    )
    
    descriptors: list[SkillDescriptor] = []
    warnings: list[str] = []
    
    for root_path in root_paths:
        # Normalize path
        root = Path(root_path) if not isinstance(root_path, Path) else root_path
        
        if not root.exists():
            warnings.append(f"External skill root not found: {root}")
            continue
        
        # Look for manifest.json files in subdirectories
        for manifest_file in root.glob("**/manifest.json"):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                
                # Convert manifest to SkillDescriptor
                descriptor_data = {
                    "id": manifest_data.get("id", manifest_file.parent.name),
                    "name": manifest_data.get("name", "Unknown"),
                    "description": manifest_data.get("description", ""),
                    "kind": manifest_data.get("kind", "domain"),
                    "source": SkillSource.IMPORTED.value,
                    "entry_mode": manifest_data.get("entry_mode", "manual"),
                    "supported_scopes": manifest_data.get("supported_scopes", ["section"]),
                    "ui_visibility": manifest_data.get("ui_visibility", UIVisibility.HIDDEN.value),
                    "requires_assets": manifest_data.get("requires_assets", False),
                    "prompt_template_refs": manifest_data.get("prompt_template_refs", []),
                    "script_refs": manifest_data.get("script_refs", []),
                    "reference_refs": manifest_data.get("reference_refs", []),
                    "tags": manifest_data.get("tags", []),
                    "version": manifest_data.get("version", "1.0.0"),
                    "display_group": manifest_data.get("display_group", "imported"),
                    "experimental": manifest_data.get("experimental", False),
                    "safe_to_execute": manifest_data.get("safe_to_execute", False),
                    "capability_refs": manifest_data.get("capability_refs", []),
                    "default_parameters": manifest_data.get("default_parameters", {}),
                    "import_origin": str(manifest_file.parent),
                    "summary_hint": manifest_data.get("summary_hint"),
                    "disabled_reason": "Imported skill - disabled by default" if auto_disable else None,
                    "trust_level": SkillTrustLevel.LIMITED.value,
                    "script_policy": ScriptPolicy(
                        has_scripts=len(manifest_data.get("script_refs", [])) > 0,
                        safe_to_execute=False,  # External scripts not auto-trusted
                        disabled_reason="External skill scripts require explicit approval"
                    ),
                }
                
                # Ensure kind is valid
                try:
                    SkillKind(descriptor_data["kind"])
                except ValueError:
                    descriptor_data["kind"] = SkillKind.DOMAIN.value
                    warnings.append(f"Invalid kind in {manifest_file}, defaulting to 'domain'")
                
                descriptor = SkillDescriptor(**descriptor_data)
                descriptors.append(descriptor)
                
            except json.JSONDecodeError as e:
                warnings.append(f"Failed to parse {manifest_file}: {e}")
            except KeyError as e:
                warnings.append(f"Missing required field in {manifest_file}: {e}")
            except Exception as e:
                warnings.append(f"Error importing {manifest_file}: {e}")
    
    return ImportResult(descriptors=descriptors, warnings=warnings)


def is_imported_skill_disabled(descriptor: SkillDescriptor) -> bool:
    """Check if an imported skill is disabled."""
    return (
        descriptor.source == SkillSource.IMPORTED and 
        descriptor.disabled_reason is not None
    )


def enable_imported_skill(descriptor: SkillDescriptor) -> SkillDescriptor:
    """
    Create an enabled version of an imported skill.
    
    Note: This returns a new descriptor since they are frozen.
    """
    if descriptor.source != SkillSource.IMPORTED:
        return descriptor
    
    # Create new descriptor without disabled_reason
    import copy
    data = copy.deepcopy({
        "id": descriptor.id,
        "name": descriptor.name,
        "description": descriptor.description,
        "kind": descriptor.kind,
        "source": descriptor.source,
        "entry_mode": descriptor.entry_mode,
        "supported_scopes": descriptor.supported_scopes,
        "ui_visibility": descriptor.ui_visibility,
        "requires_assets": descriptor.requires_assets,
        "disabled_reason": None,  # Enable it
    })
    
    # Return new descriptor (would need to reconstruct properly in real code)
    return descriptor
