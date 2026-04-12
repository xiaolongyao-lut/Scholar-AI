#!/usr/bin/env python
"""Final verification of all Harness V2 Phases A-E"""

import unittest
import sys

def run_final_verification():
    """Run all tests and report final status."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Load all test modules for Phases A-E
    test_modules = [
        'test_harness_store',
        'test_canonical_events',
        'test_canonical_event_store',
        'test_memory_policy',
        'test_event_integration_layer',
        'test_memory_fact_store',
        'test_memory_aware_planner'
    ]
    
    for module in test_modules:
        try:
            suite.addTests(loader.loadTestsFromName(module))
        except Exception as e:
            print(f"Error loading {module}: {e}")
            return False
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    
    # Report
    print("\n" + "="*60)
    print("HARNESS V2 FINAL VERIFICATION")
    print("="*60)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    status = "PASS ✅" if result.wasSuccessful() else "FAIL ❌"
    print(f"Status: {status}")
    print("="*60)
    
    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_final_verification()
    sys.exit(0 if success else 1)
