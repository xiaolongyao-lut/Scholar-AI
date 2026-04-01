# FocusRegistry Persistence Fix - Summary

## Problem Statement

The `FocusRegistry.load()` method failed to restore critical lookup state after a save/load cycle:

1. **Missing alias and category mappings**: `alias_map` and `category_map` were not persisted to JSON
2. **Incomplete cache rebuild**: `_normalized_to_canonical` cache wasn't fully rebuilt from alias mappings
3. **Inconsistent canonicalization**: Calling `canonicalize_focus()` on a previously seen alias text after a load could produce different results than before the save

This meant that a registry extracted from LLM output could work correctly in-memory, but after being saved and reloaded, it would lose its ability to properly resolve aliases and apply category mappings.

## Solution

### Changes Made

#### 1. **Modified `to_dict()` method** (lines 523-554)
   - Added serialization of `alias_map` and `category_map` to the JSON output
   - These are now preserved alongside focus_registry, doc_map, and mentions

#### 2. **Enhanced `load()` method** (lines 556-628)
   - Restored `alias_map` and `category_map` from JSON during load (with defaults to empty dicts for backward compatibility)
   - Passed these to the registry constructor to properly initialize the instance
   - Added explicit cache rebuild: `_normalized_to_canonical` is now repopulated from alias mappings

### Key Benefits

- ✅ **State Preservation**: `alias_map` and `category_map` are now fully persisted and restored
- ✅ **Canonicalization Consistency**: After a save/load cycle, `canonicalize_focus()` produces identical results
- ✅ **Backward Compatible**: Old JSON files without these fields still load correctly (maps default to empty dicts)
- ✅ **Logging Enhanced**: Load log now includes alias mapping count for transparency

## Test Results

### Test 1: Save/Load Canonicalization Preservation ✅
- Verifies that after save/load, all test inputs canonicalize to their expected values
- Tests with 5 different alias mappings across 2 focus points
- All assertions pass

### Test 2: Backward Compatibility ✅
- Loads old-format JSON files (without alias_map/category_map fields)
- Verifies data integrity and correct initialization of empty maps
- Successfully loads and reconstructs focus records

## Files Modified

- `layers/focus_registry.py`
  - `to_dict()`: Added `alias_map` and `category_map` to serialization
  - `load()`: Added restoration of mapping tables and cache rebuild

## Files Created (for testing)

- `test_focus_registry_persistence.py`: Comprehensive persistence test
- `test_backward_compatibility.py`: Backward compatibility verification

## Example Usage

```python
from layers.focus_registry import FocusRegistry

# Create with alias mappings
alias_map = {
    "热输入": "热输入控制",
    "heat input": "热输入控制"
}
registry = FocusRegistry(alias_map=alias_map)

# Use the registry
registry.upsert_focus("热输入")  # Maps to "热输入控制"
registry.save("output.json")

# Load later - mappings are preserved!
loaded = FocusRegistry.load("output.json")
loaded.canonicalize_focus("heat input")  # Still maps to "热输入控制" ✓
```

## Verified Behaviors

1. **Idempotent Load/Save Cycles**: Multiple save/load iterations preserve state
2. **Alias Resolution**: All alias mappings work consistently after load
3. **Record Integrity**: Focus records, mentions, and doc_map all remain intact
4. **Cache Consistency**: Internal lookup caches are properly rebuilt
5. **Safe Paths**: Path security checks still function correctly (safe_root enforcement)
