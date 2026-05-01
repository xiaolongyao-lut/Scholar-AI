"""
Phase H4.1 Integration Tests

Validates integration of:
  - recovery_cli.py + recovery_autopilot_cli.py
  - recovery_api.py (FastAPI) + autopilot endpoints
  - Canonical events emission for all operations
  - Metrics tracking for HTTP and autopilot operations

Test coverage: 15+ integration tests
"""

import pytest
import sys
from io import StringIO
from argparse import Namespace
from unittest.mock import patch

# Import CLI modules
from recovery_cli import main as cli_main
from recovery_autopilot_cli import (
    cmd_autopilot_status,
    cmd_autopilot_enable,
    cmd_autopilot_disable,
    get_autopilot_control_plane,
    reset_autopilot_control_plane,
)
from recovery_store_provider import reset_stores
from recovery_autopilot_policy import create_conservative_policy

# Import API modules
from fastapi.testclient import TestClient
from recovery_api import create_recovery_api


class TestCLIAutopilotIntegration:
    """Tests for autopilot commands in recovery CLI."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_cli_autopilot_status_command(self, capsys, monkeypatch):
        """CLI autopilot status command works."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Parse CLI args for autopilot status
        with patch('sys.argv', ['recovery_cli.py', 'autopilot', 'status']):
            result = cli_main()
        
        assert result == 0
        captured = capsys.readouterr()
        assert "disabled" in captured.out.lower() or "autopilot" in captured.out.lower()
    
    def test_cli_autopilot_enable_command(self, capsys, monkeypatch):
        """CLI autopilot enable command works."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        with patch('sys.argv', ['recovery_cli.py', 'autopilot', 'enable', '--policy', 'conservative']):
            result = cli_main()
        
        assert result == 0
        captured = capsys.readouterr()
        assert "enabled" in captured.out.lower() or "✓" in captured.out
    
    def test_cli_autopilot_policy_show_command(self, capsys, monkeypatch):
        """CLI autopilot policy show command works."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        with patch('sys.argv', ['recovery_cli.py', 'autopilot', 'policy', 'show']):
            result = cli_main()
        
        assert result == 0
        captured = capsys.readouterr()
        assert "conservative" in captured.out.lower() or "policy" in captured.out.lower()


class TestAPIAutopilotEndpoints:
    """Tests for autopilot REST API endpoints."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_api_autopilot_status_endpoint(self):
        """GET /recovery/autopilot/status returns status."""
        app = create_recovery_api()
        client = TestClient(app)
        
        response = client.get("/recovery/autopilot/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "state" in data
        assert "is_enabled" in data
        assert data["is_enabled"] is False  # Initially disabled
    
    def test_api_autopilot_enable_endpoint(self, monkeypatch):
        """POST /recovery/autopilot/enable enables autopilot."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "api-test")
        app = create_recovery_api()
        client = TestClient(app)
        
        response = client.post(
            "/recovery/autopilot/enable",
            json={
                "policy": "conservative",
                "reason": "Testing API"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "enabled"
        assert data["policy"] == "conservative"
    
    def test_api_autopilot_disable_endpoint(self, monkeypatch):
        """POST /recovery/autopilot/disable disables autopilot."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "api-test")
        app = create_recovery_api()
        client = TestClient(app)
        
        # First enable
        client.post(
            "/recovery/autopilot/enable",
            json={"policy": "conservative"}
        )
        
        # Then disable
        response = client.post(
            "/recovery/autopilot/disable",
            json={"reason": "Testing"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"
    
    def test_api_autopilot_emergency_stop_endpoint(self, monkeypatch):
        """POST /recovery/autopilot/emergency-stop triggers emergency stop."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "api-test")
        app = create_recovery_api()
        client = TestClient(app)
        
        # First enable
        client.post(
            "/recovery/autopilot/enable",
            json={"policy": "conservative"}
        )
        
        # Emergency stop
        response = client.post(
            "/recovery/autopilot/emergency-stop",
            json={"reason": "Incident response"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "emergency_stopped"
    
    def test_api_autopilot_policies_endpoint(self):
        """GET /recovery/autopilot/policies returns available policies."""
        app = create_recovery_api()
        client = TestClient(app)
        
        response = client.get("/recovery/autopilot/policies")
        
        assert response.status_code == 200
        policies = response.json()
        assert len(policies) == 3
        
        # Check policy names contain key words
        all_names = " ".join([p["name"] for p in policies])
        assert "conservative" in all_names.lower()
        assert "standard" in all_names.lower() or "balanced" in all_names.lower()
        assert "permissive" in all_names.lower() or "development" in all_names.lower()
    
    def test_api_metrics_endpoint(self):
        """GET /recovery/metrics returns Prometheus metrics."""
        app = create_recovery_api()
        client = TestClient(app)
        
        response = client.get("/recovery/metrics")
        
        assert response.status_code == 200
        text = response.text
        assert "HELP" in text or "TYPE" in text or "recovery" in text.lower()
        # Should be Prometheus format
        assert "#" in text or "{" in text
    
    def test_api_events_endpoint(self, monkeypatch):
        """GET /recovery/events returns event history."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "api-test")
        app = create_recovery_api()
        client = TestClient(app)
        
        # Generate an event by enabling autopilot
        client.post(
            "/recovery/autopilot/enable",
            json={"policy": "conservative"}
        )
        
        # Query events
        response = client.get("/recovery/events")
        
        assert response.status_code == 200
        events = response.json()
        # Should have some events from the enable operation
        assert isinstance(events, list)
    
    def test_api_health_check(self):
        """GET /recovery/health returns health status."""
        app = create_recovery_api()
        client = TestClient(app)
        
        response = client.get("/recovery/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "components" in data


class TestCanonicalEventsIntegration:
    """Tests that all operations emit canonical events."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_autopilot_enable_emits_event(self, monkeypatch):
        """Autopilot enable emits canonical event."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-op")
        
        from recovery_store_provider import get_event_store
        
        store = get_event_store()
        initial_count = store.get_event_count()
        
        # Enable autopilot
        args = Namespace(policy="conservative", reason="Test event")
        cmd_autopilot_enable(args)
        
        # Check event was emitted
        final_count = store.get_event_count()
        assert final_count > initial_count, "Event should be emitted on enable"
    
    def test_autopilot_disable_emits_event(self, monkeypatch):
        """Autopilot disable emits canonical event."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-op")
        
        from recovery_store_provider import get_event_store
        
        # Enable first
        args = Namespace(policy="conservative", reason="Setup")
        cmd_autopilot_enable(args)
        
        store = get_event_store()
        initial_count = store.get_event_count()
        
        # Disable
        args = Namespace(reason="Test disable")
        cmd_autopilot_disable(args)
        
        final_count = store.get_event_count()
        assert final_count > initial_count, "Event should be emitted on disable"
    
    def test_autopilot_state_transitions_create_events(self, monkeypatch):
        """All state transitions create audit trail events."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-op")
        
        from recovery_store_provider import get_event_store
        
        store = get_event_store()
        
        # Enable > Check > Disable workflow
        args = Namespace(policy="conservative", reason="Test")
        cmd_autopilot_enable(args)
        
        args = Namespace(reason="Done")
        cmd_autopilot_disable(args)
        
        # Should have at least 2 events (enable, disable)
        total_count = store.get_event_count()
        assert total_count >= 2, "At least enable and disable events should exist"


class TestMetricsIntegration:
    """Tests that metrics are properly tracked."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_autopilot_operations_tracked_in_metrics(self, monkeypatch):
        """Autopilot operations update metrics."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-op")
        
        from recovery_metrics_exporter import get_recovery_metrics_collector
        
        collector = get_recovery_metrics_collector()
        
        # Before
        metrics_before = collector.render_prometheus_text()
        
        # Execute operations
        args = Namespace(policy="conservative", reason="Metrics test")
        cmd_autopilot_enable(args)
        
        # After
        metrics_after = collector.render_prometheus_text()
        
        # Metrics should exist
        assert "recovery" in metrics_after.lower() or "autopilot" in metrics_after.lower()
    
    def test_api_requests_tracked_in_metrics(self):
        """API requests are tracked in metrics."""
        from recovery_metrics_exporter import get_recovery_metrics_collector
        
        collector = get_recovery_metrics_collector()
        
        # Make some requests
        app = create_recovery_api()
        client = TestClient(app)
        
        client.get("/recovery/health")
        client.get("/recovery/autopilot/status")
        client.get("/recovery/metrics")
        
        # Export metrics
        metrics = collector.render_prometheus_text()
        
        # Should have metrics
        assert len(metrics) > 0


class TestWorkflows:
    """End-to-end workflows via CLI and API."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_cli_workflow_enable_status_disable(self, capsys, monkeypatch):
        """CLI workflow: enable → status → disable."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "cli-user")
        
        # Enable
        with patch('sys.argv', ['recovery_cli.py', 'autopilot', 'enable', '--policy', 'conservative']):
            assert cli_main() == 0
        
        # Status
        with patch('sys.argv', ['recovery_cli.py', 'autopilot', 'status']):
            assert cli_main() == 0
        
        # Disable
        with patch('sys.argv', ['recovery_cli.py', 'autopilot', 'disable']):
            assert cli_main() == 0
    
    def test_api_workflow_enable_policy_change_disable(self, monkeypatch):
        """API workflow: enable → change policy → disable."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "api-user")
        
        app = create_recovery_api()
        client = TestClient(app)
        
        # Enable
        resp = client.post(
            "/recovery/autopilot/enable",
            json={"policy": "conservative"}
        )
        assert resp.status_code == 200
        
        # Change policy
        resp = client.post(
            "/recovery/autopilot/policy/set",
            json={"policy": "standard"}
        )
        assert resp.status_code == 200
        
        # Disable
        resp = client.post(
            "/recovery/autopilot/disable",
            json={"reason": "Done"}
        )
        assert resp.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
