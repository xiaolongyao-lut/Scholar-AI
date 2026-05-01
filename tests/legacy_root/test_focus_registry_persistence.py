# -*- coding: utf-8 -*-
"""
Test script to verify FocusRegistry save/load cycle preserves canonicalization behavior
"""

import json
import tempfile
from pathlib import Path
from layers.focus_registry import FocusRegistry


def test_save_load_preserves_canonicalization():
    """
    Test that after save/load, the registry maintains identical canonicalization behavior
    """
    print("=" * 70)
    print("Test: Save/Load Canonicalization Preservation")
    print("=" * 70)

    # Create a registry with alias mappings
    alias_map = {
        "热输入": "热输入控制",
        "heat input": "热输入控制",
        "焊接热输入": "热输入控制",
        "晶粒": "晶粒细化",
        "grain refinement": "晶粒细化"
    }

    category_map = {
        "热输入控制": "工艺参数",
        "晶粒细化": "组织控制"
    }

    # Create temp directory for the test
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / "test_registry.json"

    try:
        # Original registry
        print("\n[1] Creating original registry...")
        registry1 = FocusRegistry(alias_map=alias_map, category_map=category_map, safe_root=temp_dir)

        # Insert some focus points
        test_inputs = [
            ("热输入", "热输入控制"),
            ("Heat Input", "热输入控制"),
            ("焊接热输入", "热输入控制"),
            ("晶粒", "晶粒细化"),
            ("grain refinement", "晶粒细化"),
        ]

        print("\n[2] Upserting focus points...")
        focus_ids = {}
        for text, expected_canonical in test_inputs:
            focus_id, is_new = registry1.upsert_focus(text)
            record = registry1.get_focus_by_id(focus_id)
            actual_canonical = record.canonical_name if record else None
            
            status = "✓" if actual_canonical == expected_canonical else "✗"
            print(f"  {status} '{text}' → canonical='{actual_canonical}' (expected='{expected_canonical}')")
            
            focus_ids[expected_canonical] = focus_id

        # Add mentions
        print("\n[3] Adding mentions...")
        for focus_name, focus_id in focus_ids.items():
            registry1.add_mention(
                focus_id=focus_id,
                doc_id="paper_1",
                doc_title="Test Paper",
                snippet=f"Sample text containing {focus_name}",
                section="introduction"
            )
            print(f"  Added mention for '{focus_name}'")

        # Update doc map
        registry1.update_doc_map("paper_1", "Test Paper", "/path/to/paper.pdf")

        # Save to temp file
        print("\n[4] Saving registry to JSON...")
        registry1.save(str(temp_path))
        print(f"  Saved to: {temp_path}")

        # Verify serialization includes new fields
        print("\n[5] Verifying serialization...")
        with open(str(temp_path), 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        has_alias_map = "alias_map" in saved_data
        has_category_map = "category_map" in saved_data
        
        print(f"  {'✓' if has_alias_map else '✗'} alias_map present in JSON: {has_alias_map}")
        print(f"  {'✓' if has_category_map else '✗'} category_map present in JSON: {has_category_map}")
        
        if has_alias_map:
            print(f"    - Contains {len(saved_data['alias_map'])} alias mappings")
        if has_category_map:
            print(f"    - Contains {len(saved_data['category_map'])} category mappings")

        # Load from file
        print("\n[6] Loading registry from JSON...")
        registry2 = FocusRegistry.load(str(temp_path), safe_root=temp_dir)
        print(f"  Loaded successfully")
        print(f"  - Focus points: {len(registry2.focus_records)}")
        print(f"  - Alias map entries: {len(registry2.alias_map)}")
        print(f"  - Category map entries: {len(registry2.category_map)}")

        # Test canonicalization consistency after load
        print("\n[7] Testing canonicalization after load...")
        all_consistent = True
        
        for text, expected_canonical in test_inputs:
            # Test canonicalize_focus behavior
            canonical_result = registry2.canonicalize_focus(text)
            is_consistent = canonical_result == expected_canonical
            
            status = "✓" if is_consistent else "✗"
            print(f"  {status} canonicalize_focus('{text}') = '{canonical_result}' (expected='{expected_canonical}')")
            
            if not is_consistent:
                all_consistent = False

        # Verify focus records are identical
        print("\n[8] Verifying focus records consistency...")
        for expected_canonical, focus_id in focus_ids.items():
            record1 = registry1.get_focus_by_name(expected_canonical)
            record2 = registry2.get_focus_by_name(expected_canonical)
            
            if record1 and record2:
                is_same = (
                    record1.id == record2.id and
                    record1.canonical_name == record2.canonical_name and
                    record1.mention_count == record2.mention_count
                )
                status = "✓" if is_same else "✗"
                print(f"  {status} '{expected_canonical}': id={record2.id}, mention_count={record2.mention_count}")
            else:
                print(f"  ✗ '{expected_canonical}': missing in loaded registry")
                all_consistent = False

        # Verify mentions consistency
        print("\n[9] Verifying mentions consistency...")
        mentions_consistent = len(registry1.mentions) == len(registry2.mentions)
        status = "✓" if mentions_consistent else "✗"
        print(f"  {status} Mention count: {len(registry2.mentions)} (original had {len(registry1.mentions)})")

        # Verify doc_map consistency
        print("\n[10] Verifying doc_map consistency...")
        doc_map_consistent = len(registry1.doc_map) == len(registry2.doc_map)
        status = "✓" if doc_map_consistent else "✗"
        print(f"  {status} Doc map entries: {len(registry2.doc_map)} (original had {len(registry1.doc_map)})")

        # Final result
        print("\n" + "=" * 70)
        overall_success = all_consistent and mentions_consistent and doc_map_consistent
        result = "✅ PASS" if overall_success else "❌ FAIL"
        print(f"Test Result: {result}")
        print("=" * 70)

        return overall_success

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\nCleaned up temp directory: {temp_dir}")


if __name__ == "__main__":
    success = test_save_load_preserves_canonicalization()
    exit(0 if success else 1)
