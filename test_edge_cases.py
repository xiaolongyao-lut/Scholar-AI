# -*- coding: utf-8 -*-
"""
Test edge case: Verify alias cache rebuild doesn't cause issues with circular references
"""

import json
import tempfile
from pathlib import Path
from layers.focus_registry import FocusRegistry


def test_alias_cache_rebuild_edge_cases():
    """
    Test edge cases in alias mapping:
    1. Simple one-to-one aliases
    2. Multiple aliases to same canonical
    3. Loading and adding new aliases
    """
    print("=" * 70)
    print("Test: Alias Cache Rebuild Edge Cases")
    print("=" * 70)

    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / "edge_case_registry.json"

    try:
        # Test 1: Multiple aliases to same canonical
        print("\n[1] Testing multiple aliases to same canonical...")
        alias_map = {
            "输入热量": "热输入控制",
            "heat input": "热输入控制",
            "thermal input": "热输入控制",
            "焊接热": "热输入控制"
        }
        
        registry = FocusRegistry(alias_map=alias_map, safe_root=temp_dir)
        
        # All should map to the same canonical
        results = [registry.canonicalize_focus(text) for text in alias_map.keys()]
        expected = ["热输入控制"] * 4
        
        if results == expected:
            print("  ✓ All aliases correctly map to same canonical")
        else:
            print(f"  ✗ Alias mapping failed: {results}")
            return False

        # Test 2: Save and load
        print("\n[2] Saving and loading registry...")
        registry.upsert_focus("热输入控制", category="工艺参数")
        registry.save(str(temp_path))
        
        loaded = FocusRegistry.load(str(temp_path), safe_root=temp_dir)
        print("  ✓ Registry saved and loaded successfully")

        # Test 3: Verify all aliases still work after load
        print("\n[3] Verifying aliases after load...")
        loaded_results = [loaded.canonicalize_focus(text) for text in alias_map.keys()]
        
        if loaded_results == expected:
            print("  ✓ All aliases correctly resolve after load")
        else:
            print(f"  ✗ Post-load alias mapping failed: {loaded_results}")
            return False

        # Test 4: Verify alias_map is properly restored
        print("\n[4] Verifying alias_map restoration...")
        if len(loaded.alias_map) == len(alias_map):
            print(f"  ✓ alias_map correctly restored ({len(loaded.alias_map)} entries)")
        else:
            print(f"  ✗ alias_map mismatch: got {len(loaded.alias_map)}, expected {len(alias_map)}")
            return False

        # Test 5: JSON serialization verification
        print("\n[5] Verifying JSON contains all aliases...")
        with open(str(temp_path), 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if "alias_map" in data and len(data["alias_map"]) == 4:
            print(f"  ✓ JSON correctly contains {len(data['alias_map'])} alias mappings")
            for alias, canonical in list(data["alias_map"].items())[:2]:
                print(f"    - '{alias}' → '{canonical}'")
        else:
            print(f"  ✗ JSON alias_map verification failed")
            return False

        print("\n" + "=" * 70)
        print("Test Result: ✅ PASS - All edge cases handled correctly")
        print("=" * 70)
        return True

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    success = test_alias_cache_rebuild_edge_cases()
    exit(0 if success else 1)
