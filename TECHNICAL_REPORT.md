# FocusRegistry Persistence Enhancement - Technical Report

## Executive Summary

Fixed a critical issue in `FocusRegistry` where the save/load cycle failed to preserve canonicalization lookup state. The registry now correctly persists and restores `alias_map` and `category_map`, ensuring consistent canonicalization behavior across load cycles.

## Problem Description

### Original Issue

When `FocusRegistry.load()` was called to restore a previously saved registry:

1. **Lost Alias Mappings**: The `alias_map` dictionary (mapping variations to canonical names) was not persisted to JSON
2. **Lost Category Mappings**: The `category_map` dictionary was not persisted
3. **Incomplete Cache**: The `_normalized_to_canonical` cache was not fully rebuilt from alias information
4. **Inconsistent Results**: Calling `canonicalize_focus()` on a known alias after load could produce different results than before save

**Example**:
```python
# Before save/load
registry.canonicalize_focus("heat input")  # → "热输入控制" ✓

# After save/load  
loaded.canonicalize_focus("heat input")    # → "heat input" ✗ (WRONG)
```

### Impact

- Extracted focus points could be canonicalized differently after persistence
- Duplicate detection across multiple load cycles would fail
- Multi-session processing pipelines would produce inconsistent results

## Solution

### Changes to `layers/focus_registry.py`

#### Change 1: Enhanced `to_dict()` method (lines 523-554)

**Before:**
```python
def to_dict(self) -> dict:
    return {
        "version": self.version,
        "points": points,
        "focus_registry": [...],
        "doc_map": {...},
        "mentions": [...],
        "metadata": {...}
    }
```

**After:**
```python
def to_dict(self) -> dict:
    return {
        "version": self.version,
        "points": points,
        "focus_registry": [...],
        "doc_map": {...},
        "mentions": [...],
        "alias_map": self.alias_map,           # ← NEW
        "category_map": self.category_map,      # ← NEW
        "metadata": {...}
    }
```

**Rationale**: Serialize the mapping tables alongside records for persistence.

---

#### Change 2: Enhanced `load()` method (lines 556-628)

**Key improvements:**

1. **Extract mapping tables from JSON**:
   ```python
   alias_map = data.get("alias_map", {})        # Default to {} for backward compatibility
   category_map = data.get("category_map", {})
   ```

2. **Pass to constructor**:
   ```python
   registry = cls(alias_map=alias_map, category_map=category_map, safe_root=safe_root)
   ```

3. **Rebuild alias cache**:
   ```python
   # 重建 _normalized_to_canonical 缓存，包括所有别名映射
   for alias_text, canonical in alias_map.items():
       registry._normalized_to_canonical[alias_text] = canonical
   ```

4. **Enhanced logging**:
   ```python
   logger.info(f"  - Alias mappings: {len(registry.alias_map)}")
   ```

**Rationale**: 
- Maps are restored before any operations, ensuring `canonicalize_focus()` works correctly
- Explicit cache rebuild ensures all alias paths are indexed for O(1) lookup
- Backward compatibility maintained for old JSON files (missing fields default to empty dicts)

## Verification

### Test 1: Full Persistence Cycle ✅
- Creates registry with 5 alias mappings across 2 focus points
- Saves to JSON
- Loads from JSON
- Verifies all aliases resolve identically before and after load
- **Result**: All 5 aliases resolve correctly post-load

### Test 2: Backward Compatibility ✅
- Loads old-format JSON (without alias_map/category_map)
- Verifies graceful degradation (maps default to empty dicts)
- All existing data (records, mentions, doc_map) remains intact
- **Result**: Old files load without error, categories preserved

### Test 3: Edge Cases ✅
- Multiple aliases to same canonical name
- Complex alias chains after load
- JSON serialization verification
- **Result**: All edge cases handled correctly

## Behavior Verification

### Canonicalization Consistency

```python
# Setup
alias_map = {
    "热输入": "热输入控制",
    "heat input": "热输入控制"
}
registry = FocusRegistry(alias_map=alias_map, safe_root=temp_dir)
registry.upsert_focus("热输入控制")
registry.save("output.json")

# Load and verify
loaded = FocusRegistry.load("output.json", safe_root=temp_dir)

# Before: FAIL ✗
# loaded.canonicalize_focus("heat input") → "heat input"

# After: PASS ✓
# loaded.canonicalize_focus("heat input") → "热输入控制"
```

### Data Integrity

| Aspect | Before | After |
|--------|--------|-------|
| Focus records | ✓ | ✓ |
| Mentions | ✓ | ✓ |
| Doc mappings | ✓ | ✓ |
| Alias mappings | ✗ | ✓ |
| Category mappings | ✗ | ✓ |
| Canonicalization | ✗ | ✓ |

## Backward Compatibility

✅ **Fully backward compatible**

Old JSON files created before this fix:
- Load successfully without errors
- Maps default to empty dicts
- All existing fields (records, mentions, doc_map) restore correctly
- No data loss

New JSON files created after this fix:
- Include `alias_map` and `category_map`
- Can be loaded by code with or without this fix
- Fully support alias-driven canonicalization

## Performance Impact

- **Save**: +minimal (dict serialization)
- **Load**: +O(n) where n = number of aliases (cache rebuild)
- **Runtime**: No impact (same indices used)

## Recommendations

1. **Immediate**: Use updated `FocusRegistry` for all new extractions
2. **Migration**: Consider re-saving existing registries with the new format to ensure full functionality
3. **Testing**: Run test suite to verify canonicalization in your pipeline:
   ```bash
   python test_focus_registry_persistence.py
   python test_backward_compatibility.py
   python test_edge_cases.py
   ```

## Code References

- Main file: `layers/focus_registry.py`
- Modified methods:
  - `FocusRegistry.to_dict()` (lines 523-554)
  - `FocusRegistry.load()` (lines 556-628)
- Test files:
  - `test_focus_registry_persistence.py`
  - `test_backward_compatibility.py`
  - `test_edge_cases.py`

## Conclusion

The fix ensures that `FocusRegistry` maintains full state fidelity across save/load cycles, enabling reliable multi-session focus extraction pipelines with consistent canonicalization and deduplication behavior.
