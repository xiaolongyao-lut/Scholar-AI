# -*- coding: utf-8 -*-
"""
Test backward compatibility: Loading old JSON files without alias_map/category_map
"""

import json
import tempfile
from pathlib import Path
from layers.focus_registry import FocusRegistry


def test_backward_compatibility_load_old_format():
    """
    Test that we can still load JSON files that were created with the old format
    (without alias_map and category_map fields)
    """
    print("=" * 70)
    print("Test: Backward Compatibility - Loading Old Format JSON")
    print("=" * 70)

    # Create temp directory for the test
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / "old_format_registry.json"

    try:
        # Create an old-format registry and save it
        print("\n[1] Creating old-format registry (without alias_map/category_map)...")
        registry1 = FocusRegistry(safe_root=temp_dir)
        
        # Add some focus points
        focus_id_1, _ = registry1.upsert_focus("热输入", category="工艺参数")
        focus_id_2, _ = registry1.upsert_focus("晶粒细化", category="组织控制")
        
        # Add mentions
        registry1.add_mention(
            focus_id=focus_id_1,
            doc_id="paper_a",
            doc_title="Test Paper",
            snippet="Discussion on heat input",
            section="discussion"
        )
        registry1.update_doc_map("paper_a", "Test Paper", "/path/to/paper.pdf")
        
        # Manually save with the old format (without alias_map/category_map)
        print("\n[2] Saving in old format...")
        old_data = registry1.to_dict()
        # Remove the new fields to simulate old format
        del old_data['alias_map']
        del old_data['category_map']
        
        with open(str(temp_path), 'w', encoding='utf-8') as f:
            json.dump(old_data, f, ensure_ascii=False, indent=2)
        print(f"  Saved old format to: {temp_path}")

        # Load the old-format file
        print("\n[3] Loading old-format JSON...")
        try:
            registry2 = FocusRegistry.load(str(temp_path), safe_root=temp_dir)
            print("  ✓ Successfully loaded old-format JSON")
            
            # Verify data is intact
            print("\n[4] Verifying loaded data...")
            print(f"  - Focus points: {len(registry2.focus_records)}")
            print(f"  - Documents: {len(registry2.doc_map)}")
            print(f"  - Mentions: {len(registry2.mentions)}")
            print(f"  - Alias map entries: {len(registry2.alias_map)}")
            print(f"  - Category map entries: {len(registry2.category_map)}")
            
            # Verify empty maps are initialized
            if len(registry2.alias_map) == 0:
                print("  ✓ alias_map correctly initialized as empty dict")
            if len(registry2.category_map) == 0:
                print("  ✓ category_map correctly initialized as empty dict")
            
            # Verify focus records
            focus1 = registry2.get_focus_by_name("热输入")
            focus2 = registry2.get_focus_by_name("晶粒细化")
            
            if focus1 and focus2:
                print(f"  ✓ Found both focus points")
                print(f"    - '热输入': category='{focus1.category}'")
                print(f"    - '晶粒细化': category='{focus2.category}'")
            else:
                print(f"  ✗ Failed to find focus points")
                return False
            
            print("\n" + "=" * 70)
            print("Test Result: ✅ PASS - Backward compatibility maintained")
            print("=" * 70)
            return True
            
        except Exception as e:
            print(f"  ✗ Failed to load old-format JSON: {e}")
            import traceback
            traceback.print_exc()
            return False

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\nCleaned up temp directory: {temp_dir}")


if __name__ == "__main__":
    success = test_backward_compatibility_load_old_format()
    exit(0 if success else 1)
