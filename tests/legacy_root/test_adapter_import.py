#!/usr/bin/env python
"""Test adapter import - pytest-compatible module."""
import pytest
import python_adapter_server


def test_adapter_imports_successfully() -> None:
    """Verify python_adapter_server module imports without errors."""
    assert python_adapter_server is not None, "Failed to import python_adapter_server"


def test_fastapi_app_exists() -> None:
    """Verify FastAPI app object is created."""
    assert hasattr(python_adapter_server, 'app'), "python_adapter_server missing 'app' attribute"
    assert python_adapter_server.app is not None, "FastAPI app object is None"


def test_fastapi_app_type() -> None:
    """Verify app is a FastAPI instance."""
    from fastapi import FastAPI
    assert isinstance(python_adapter_server.app, FastAPI), \
        f"app is not a FastAPI instance, got {type(python_adapter_server.app)}"


if __name__ == "__main__":
    # Allow running as a standalone script for quick validation
    import sys
    import traceback
    
    try:
        # Run all tests
        pytest.main([__file__, "-v", "--tb=short"])
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)

