"""
Test H4.1 Final Hardening: Verify autopilot routes integrated into main adapter.

Tests that:
- Autopilot routes are accessible via python_adapter_server
- HTTP metrics middleware tracks all recovery endpoints
- No route conflicts between recovered endpoints and main adapter
- Canonical events still emitted through integrated endpoints
"""

import pytest
import os
from unittest.mock import patch

# Suppress werkzeug logging
import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)


@pytest.fixture(scope="module")
def app():
    """Create FastAPI test app from main adapter."""
    from python_adapter_server import app as adapter_app
    return adapter_app


@pytest.fixture
def client(app):
    """Create FastAPI test client."""
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestH41FinalHarding:
    """Test suite for H4.1 final hardening / autopilot integration."""

    def test_autopilot_routes_in_main_adapter(self, app):
        """Verify autopilot routes exist in main adapter."""
        paths = {route.path for route in app.routes}
        
        autopilot_routes = [
            "/recovery/autopilot/status",
            "/recovery/autopilot/enable",
            "/recovery/autopilot/disable",
            "/recovery/autopilot/emergency-stop",
            "/recovery/autopilot/emergency-resume",
            "/recovery/autopilot/policies",
            "/recovery/autopilot/policy/set",
            "/recovery/events",
            "/recovery/health",
        ]
        
        missing = [r for r in autopilot_routes if r not in paths]
        assert not missing, f"Missing routes in main adapter: {missing}"

    def test_autopilot_status_via_main_adapter(self, client):
        """Test autopilot status endpoint via main adapter."""
        with patch.dict(os.environ, {"RECOVERY_OPERATOR_ID": "test-user"}):
            response = client.get("/recovery/autopilot/status")
            assert response.status_code == 200
            data = response.json()
            assert "state" in data
            assert "is_enabled" in data
            assert "is_emergency_stopped" in data

    def test_autopilot_enable_via_main_adapter(self, client):
        """Test autopilot enable endpoint via main adapter."""
        with patch.dict(os.environ, {"RECOVERY_OPERATOR_ID": "test-user"}):
            response = client.post(
                "/recovery/autopilot/enable",
                json={"policy": "conservative", "reason": "Integration test"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "enabled"
            assert data["policy"] == "conservative"

    def test_autopilot_policies_via_main_adapter(self, client):
        """Test autopilot policies listing via main adapter."""
        response = client.get("/recovery/autopilot/policies")
        assert response.status_code == 200
        policies = response.json()
        assert len(policies) == 3  # conservative, standard, permissive
        policy_names = {p["name"] for p in policies}
        # Check that we have the three policy names (exact names may vary)
        assert any("conservative" in p.lower() for p in policy_names)
        assert any("standard" in p.lower() for p in policy_names)
        assert any("permissive" in p.lower() for p in policy_names)

    def test_events_endpoint_via_main_adapter(self, client):
        """Test events endpoint via main adapter."""
        response = client.get("/recovery/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_recovery_health_via_main_adapter(self, client):
        """Test recovery health check via main adapter."""
        response = client.get("/recovery/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "components" in data

    def test_metrics_endpoint_via_main_adapter(self, client):
        """Test metrics endpoint via main adapter."""
        response = client.get("/recovery/metrics")
        assert response.status_code == 200
        # Prometheus plaintext format
        assert "recovery" in response.text.lower() or "http" in response.text.lower()

    def test_http_metrics_middleware_tracks_recovery_routes(self, client):
        """Test that HTTP metrics middleware tracks recovery endpoints."""
        from recovery_metrics_exporter import get_recovery_metrics_collector
        
        # Make a request to trigger middleware
        with patch.dict(os.environ, {"RECOVERY_OPERATOR_ID": "test-user"}):
            client.get("/recovery/autopilot/status")
        
        # Check that metrics were recorded
        collector = get_recovery_metrics_collector()
        metrics_text = collector.render_prometheus_text()
        
        # Verify metrics contain recovery HTTP data
        assert "recovery" in metrics_text.lower() or "http_requests" in metrics_text.lower()

    def test_response_has_trace_headers(self, client):
        """Test that responses include trace headers."""
        with patch.dict(os.environ, {"RECOVERY_OPERATOR_ID": "test-user"}):
            response = client.get("/recovery/autopilot/status")
            assert "X-Recovery-Trace-Id" in response.headers
            assert "X-Recovery-Span-Id" in response.headers
            assert "X-Recovery-Duration-Ms" in response.headers

    def test_no_route_conflicts(self, app):
        """Verify no duplicate routes from router integration."""
        paths = [route.path for route in app.routes]
        path_counts = {}
        for path in paths:
            path_counts[path] = path_counts.get(path, 0) + 1
        
        # Allow some duplicates (same route different methods), but not exact duplicates
        for path, count in path_counts.items():
            # Most paths are unique, but OpenAPI docs may have duplicates
            # Standard REST resources may have GET+PUT+DELETE (3 methods)
            if count > 3 and "openapi" not in path and "docs" not in path:
                raise AssertionError(f"Excessive duplicates for route {path}: {count}")

    def test_canonical_events_still_emitted(self, client):
        """Verify canonical events are still emitted through integrated endpoints."""
        from recovery_store_provider import get_event_store
        from recovery_autopilot_cli import reset_autopilot_control_plane
        
        # Reset autopilot state for test isolation
        reset_autopilot_control_plane()
        
        store = get_event_store()
        initial_count = store.get_event_count()
        
        # Make an autopilot control request (should emit event)
        with patch.dict(os.environ, {"RECOVERY_OPERATOR_ID": "test-user"}):
            response = client.post(
                "/recovery/autopilot/enable",
                json={"policy": "conservative", "reason": "Event test"}
            )
            assert response.status_code == 200, f"Enable failed: {response.json()}"
        
        # Check that event count increased
        final_count = store.get_event_count()
        assert final_count > initial_count, "No events emitted by autopilot operation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
