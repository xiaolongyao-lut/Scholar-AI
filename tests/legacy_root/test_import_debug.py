#!/usr/bin/env python
# Debug import errors

try:
    from memory_fact_store import MemoryFactStore, TemporalFact
    print("✓ memory_fact_store imported")
except Exception as e:
    print(f"✗ memory_fact_store import failed: {e}")
    import traceback
    traceback.print_exc()

try:
    from memory_policy import MemoryPolicyEngine
    print("✓ memory_policy imported")
except Exception as e:
    print(f"✗ memory_policy import failed: {e}")
    import traceback
    traceback.print_exc()

try:
    from memory_aware_planner import MemoryAwarePlanner
    print("✓ memory_aware_planner imported")
except Exception as e:
    print(f"✗ memory_aware_planner import failed: {e}")
    import traceback
    traceback.print_exc()

try:
    from test_memory_aware_planner import TestPlanningContext
    print("✓ test_memory_aware_planner imported")
except Exception as e:
    print(f"✗ test_memory_aware_planner import failed: {e}")
    import traceback
    traceback.print_exc()

print("\nAll imports successful!")
