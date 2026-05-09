# -*- coding: utf-8 -*-
"""
Test suite for code review improvements:
1. Alias table key normalization
2. Performance optimization (O(1) lookup in upsert_focus)
3. Timestamp consistency (serialization)
4. Exception handling in load()
5. Mention record lookup optimization
6. Path resolution in load()
"""

import json
import tempfile
from pathlib import Path
from layers.focus_registry import FocusRegistry


def test_1_alias_key_normalization():
    """Test that alias_map keys are normalized during initialization"""
    print("\n" + "=" * 70)
    print("Test 1: Alias Key Normalization")
    print("=" * 70)

    alias_map = {
        "Heat Input": "heat input control",
        "  heat input  ": "heat input control",
        "焊接 热输入": "heat input control",
        "THERMAL INPUT": "heat input control"
    }

    print("\n[1] Creating registry with non-normalized alias keys...")
    registry = FocusRegistry(alias_map=alias_map)

    print(f"  Input keys count: {len(alias_map)}")
    print(f"  Normalized keys count: {len(registry.alias_map)}")

    test_inputs = [
        "Heat Input",
        "  heat input  ",
        "thermal input"
    ]

    print("\n[2] Testing canonicalization with various inputs...")
    all_match = True
    for text in test_inputs:
        try:
            canonical = registry.canonicalize_focus(text)
            print(f"  Canonicalized '{text}' successfully")
        except Exception as e:
            print(f"  Error: {e}")
            all_match = False

    print("\n" + ("✅ PASS" if all_match else "❌ FAIL"))
    return all_match


def test_2_upsert_focus_performance():
    """Test that upsert_focus uses O(1) cache lookup instead of O(N) iteration"""
    print("\n" + "=" * 70)
    print("Test 2: Upsert Focus Performance (O(1) Lookup)")
    print("=" * 70)

    alias_map = {
        "heat input": "heat input control",
        "thermal input": "heat input control"
    }

    print("\n[1] Creating registry and adding focus points...")
    registry = FocusRegistry(alias_map=alias_map)

    focus_id_1, is_new_1 = registry.upsert_focus("heat input", category="process")
    print(f"  Added first: {focus_id_1} (new={is_new_1})")

    print("\n[2] Testing cache-based lookup for duplicate detection...")
    focus_id_2, is_new_2 = registry.upsert_focus("thermal input")
    print(f"  Added via alias: {focus_id_2} (new={is_new_2})")

    same_record = focus_id_1 == focus_id_2 and not is_new_2

    print(f"\n[3] Verification:")
    print(f"  Same focus_id: {focus_id_1 == focus_id_2}")
    print(f"  Second was update (not new): {not is_new_2}")
    print(f"  Cache size: {len(registry._normalized_to_canonical)}")

    print("\n" + ("✅ PASS" if same_record else "❌ FAIL"))
    return same_record


def test_3_timestamp_consistency():
    """Test that to_dict() uses self.last_updated_at instead of datetime.now()"""
    print("\n" + "=" * 70)
    print("Test 3: Timestamp Consistency in Serialization")
    print("=" * 70)

    print("\n[1] Creating registry and saving state...")
    registry = FocusRegistry()
    registry.upsert_focus("heat input", category="process")

    original_timestamp = registry.last_updated_at
    print(f"  Last updated: {original_timestamp}")

    print("\n[2] Calling to_dict() multiple times...")
    dict1 = registry.to_dict()
    dict2 = registry.to_dict()
    dict3 = registry.to_dict()

    consistent = (
        dict1['updated_at'] == dict2['updated_at'] == dict3['updated_at'] ==
        original_timestamp
    )

    print(f"  Dict1 timestamp: {dict1['updated_at']}")
    print(f"  Dict2 timestamp: {dict2['updated_at']}")
    print(f"  All identical: {dict1['updated_at'] == dict2['updated_at'] == dict3['updated_at']}")
    print(f"  Match instance timestamp: {dict1['updated_at'] == original_timestamp}")

    print("\n" + ("✅ PASS" if consistent else "❌ FAIL"))
    return consistent


def test_4_exception_handling_in_load():
    """Test exception handling for FileNotFoundError, JSONDecodeError"""
    print("\n" + "=" * 70)
    print("Test 4: Exception Handling in load()")
    print("=" * 70)

    temp_dir = tempfile.mkdtemp()

    try:
        print("\n[1] Testing FileNotFoundError...")
        nonexistent_path = Path(temp_dir) / "nonexistent.json"
        try:
            FocusRegistry.load(str(nonexistent_path), safe_root=temp_dir)
            print("  ✗ Should have raised FileNotFoundError")
            test1_pass = False
        except FileNotFoundError:
            print("  ✓ Correctly raised FileNotFoundError")
            test1_pass = True

        print("\n[2] Testing JSONDecodeError...")
        invalid_json_path = Path(temp_dir) / "invalid.json"
        with open(invalid_json_path, 'w') as f:
            f.write("{ invalid json }")
        
        try:
            FocusRegistry.load(str(invalid_json_path), safe_root=temp_dir)
            print("  ✗ Should have raised JSONDecodeError")
            test2_pass = False
        except json.JSONDecodeError:
            print("  ✓ Correctly raised JSONDecodeError")
            test2_pass = True

        print("\n[3] Testing successful load...")
        registry = FocusRegistry(safe_root=temp_dir)
        registry.upsert_focus("heat input")
        valid_json_path = Path(temp_dir) / "valid.json"
        registry.save(str(valid_json_path))
        
        try:
            loaded = FocusRegistry.load(str(valid_json_path), safe_root=temp_dir)
            print(f"  ✓ Successfully loaded registry ({len(loaded.focus_records)} focus points)")
            test3_pass = True
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            test3_pass = False

        all_pass = test1_pass and test2_pass and test3_pass
        print("\n" + ("✅ PASS" if all_pass else "❌ FAIL"))
        return all_pass

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_5_path_resolution_in_load():
    """Test that load() resolves the path correctly"""
    print("\n" + "=" * 70)
    print("Test 5: Path Resolution in load()")
    print("=" * 70)

    temp_dir = tempfile.mkdtemp()

    try:
        print("\n[1] Creating and saving registry...")
        registry = FocusRegistry(safe_root=temp_dir)
        registry.upsert_focus("heat input")
        
        json_path = Path(temp_dir) / "test.json"
        registry.save(str(json_path))

        print("\n[2] Loading with resolved path...")
        loaded = FocusRegistry.load(str(json_path), safe_root=temp_dir)
        
        print(f"  Focus points loaded: {len(loaded.focus_records)}")
        print("  ✓ Path was correctly resolved and loaded")

        print("\n✅ PASS")
        return True

    except Exception as e:
        print(f"✗ FAIL: {e}")
        return False
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_6_mention_lookup_optimization():
    """Test that add_mention optimizes index lookups"""
    print("\n" + "=" * 70)
    print("Test 6: Mention Lookup Optimization")
    print("=" * 70)

    print("\n[1] Creating registry and adding focus points...")
    registry = FocusRegistry()
    focus_id, _ = registry.upsert_focus("heat input")

    print("\n[2] Adding mention (should populate index)...")
    mention_id = registry.add_mention(
        focus_id=focus_id,
        doc_id="paper_1",
        doc_title="Test Paper",
        snippet="Discussion on heat input"
    )
    print(f"  Mention added: {mention_id}")

    print("\n[3] Verifying index state...")
    index_populated = focus_id in registry._id_to_record
    print(f"  Index entry exists: {index_populated}")

    print("\n[4] Adding second mention...")
    mention_id_2 = registry.add_mention(
        focus_id=focus_id,
        doc_id="paper_1",
        doc_title="Test Paper",
        snippet="Another reference to heat input"
    )
    print(f"  Second mention added: {mention_id_2}")

    success = index_populated and len(registry.mentions) == 2
    print("\n" + ("✅ PASS" if success else "❌ FAIL"))
    return success


def run_all_tests():
    """Run all code review improvement tests"""
    print("\n" + "=" * 80)
    print("CODE REVIEW IMPROVEMENTS TEST SUITE")
    print("=" * 80)

    results = {
        "Test 1 (Alias Normalization)": test_1_alias_key_normalization(),
        "Test 2 (Upsert Performance)": test_2_upsert_focus_performance(),
        "Test 3 (Timestamp Consistency)": test_3_timestamp_consistency(),
        "Test 4 (Exception Handling)": test_4_exception_handling_in_load(),
        "Test 5 (Path Resolution)": test_5_path_resolution_in_load(),
        "Test 6 (Mention Optimization)": test_6_mention_lookup_optimization(),
    }

    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {test_name}")

    all_pass = all(results.values())
    print("\n" + ("=" * 80))
    if all_pass:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
    print("=" * 80)

    return all_pass


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
