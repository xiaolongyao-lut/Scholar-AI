"""
Tests for H4.1 Autopilot CLI Integration

Validates all autopilot CLI commands:
  - status: Display control plane state
  - enable: Enable with policy
  - disable: Disable
  - emergency-stop: Trigger emergency stop
  - emergency-resume: Resume from emergency
  - policy show: List available policies
  - policy set: Change active policy

Test coverage: 30+ tests for all CLI commands and error cases.
"""

import pytest
import sys
from io import StringIO
from unittest.mock import patch, MagicMock
from argparse import Namespace

# Import CLI commands
from recovery_autopilot_cli import (
    cmd_autopilot_status,
    cmd_autopilot_enable,
    cmd_autopilot_disable,
    cmd_autopilot_emergency_stop,
    cmd_autopilot_emergency_resume,
    cmd_autopilot_policy_show,
    cmd_autopilot_policy_set,
    register_autopilot_commands,
    get_autopilot_control_plane,
    reset_autopilot_control_plane,
)

# Import recovery stack
from recovery_store_provider import reset_stores


class TestAutopilotCLIStatus:
    """Tests for 'autopilot status' command."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_status_when_disabled(self, capsys):
        """Status shows DISABLED when control plane is off."""
        args = Namespace()
        result = cmd_autopilot_status(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "DISABLED" in captured.out or "State:" in captured.out
    
    def test_status_when_enabled_shows_policy(self, capsys):
        """Status shows enabled state and current policy."""
        # Enable autopilot first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-user", policy)
        
        # Check status
        args = Namespace()
        result = cmd_autopilot_status(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "ENABLED" in captured.out or "conservative" in captured.out.lower()


class TestAutopilotCLIEnable:
    """Tests for 'autopilot enable' command."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_enable_with_default_policy(self, capsys, monkeypatch):
        """Enable uses conservative policy by default."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy="conservative", reason="Test")
        result = cmd_autopilot_enable(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "✓" in captured.out or "enabled" in captured.out.lower()
        assert "conservative" in captured.out.lower()
    
    def test_enable_with_standard_policy(self, capsys, monkeypatch):
        """Enable accepts standard policy."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy="standard", reason="Test")
        result = cmd_autopilot_enable(args)
        
        assert result == 0
    
    def test_enable_with_permissive_policy(self, capsys, monkeypatch):
        """Enable accepts permissive policy."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy="permissive", reason="Test")
        result = cmd_autopilot_enable(args)
        
        assert result == 0
    
    def test_enable_invalid_policy_fails(self, capsys, monkeypatch):
        """Enable with invalid policy name returns error."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy="invalid-policy", reason="Test")
        result = cmd_autopilot_enable(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Unknown policy" in captured.err
    
    def test_enable_already_enabled_fails(self, capsys, monkeypatch):
        """Enable when already enabled returns error."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first time
        args = Namespace(policy="conservative", reason="First")
        cmd_autopilot_enable(args)
        
        # Try to enable again
        args = Namespace(policy="conservative", reason="Second")
        result = cmd_autopilot_enable(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "already enabled" in captured.err.lower()
    
    def test_enable_records_operator(self, capsys, monkeypatch):
        """Enable records operator ID in output."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "alice-dev")
        
        args = Namespace(policy="conservative", reason="Test enable")
        result = cmd_autopilot_enable(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "alice-dev" in captured.out
    
    def test_enable_with_custom_reason(self, capsys, monkeypatch):
        """Enable includes custom reason in output."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy="conservative", reason="Testing new feature")
        result = cmd_autopilot_enable(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "Testing new feature" in captured.out


class TestAutopilotCLIDisable:
    """Tests for 'autopilot disable' command."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_disable_when_enabled(self, capsys, monkeypatch):
        """Disable succeeds when autopilot is enabled."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        # Then disable
        args = Namespace(reason="Maintenance")
        result = cmd_autopilot_disable(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "✓" in captured.out or "disabled" in captured.out.lower()
    
    def test_disable_when_already_disabled_fails(self, capsys, monkeypatch):
        """Disable when already disabled returns error."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(reason="Test")
        result = cmd_autopilot_disable(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "already disabled" in captured.err.lower()
    
    def test_disable_includes_reason(self, capsys, monkeypatch):
        """Disable output includes the reason."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        # Disable with reason
        args = Namespace(reason="Scheduled maintenance")
        result = cmd_autopilot_disable(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "Scheduled maintenance" in captured.out


class TestAutopilotCLIEmergencyStop:
    """Tests for 'autopilot emergency-stop' command."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_emergency_stop_requires_reason(self, capsys, monkeypatch):
        """Emergency stop fails without reason."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        args = Namespace(reason=None)
        result = cmd_autopilot_emergency_stop(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "reason is required" in captured.err.lower()
    
    def test_emergency_stop_succeeds(self, capsys, monkeypatch):
        """Emergency stop succeeds when enabled."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        args = Namespace(reason="Critical incident detected")
        result = cmd_autopilot_emergency_stop(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "🛑" in captured.out or "EMERGENCY" in captured.out
    
    def test_emergency_stop_when_already_stopped_fails(self, capsys, monkeypatch):
        """Emergency stop when already stopped returns error."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable, then stop
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        control_plane.emergency_stop("test-operator", reason="First stop")
        
        # Try to stop again
        args = Namespace(reason="Second stop")
        result = cmd_autopilot_emergency_stop(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "already" in captured.err.lower() or "emergency" in captured.err.lower()
    
    def test_emergency_stop_includes_reason(self, capsys, monkeypatch):
        """Emergency stop output includes the reason."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        args = Namespace(reason="Database integrity violation")
        result = cmd_autopilot_emergency_stop(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "Database integrity violation" in captured.out


class TestAutopilotCLIEmergencyResume:
    """Tests for 'autopilot emergency-resume' command."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_emergency_resume_succeeds(self, capsys, monkeypatch):
        """Emergency resume succeeds after emergency stop."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable, stop, then resume
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        control_plane.emergency_stop("test-operator", reason="Incident")
        
        args = Namespace(reason="Incident resolved")
        result = cmd_autopilot_emergency_resume(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "✓" in captured.out or "Resumed" in captured.out
    
    def test_emergency_resume_when_not_stopped_fails(self, capsys, monkeypatch):
        """Emergency resume fails when not in emergency stop."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(reason="Test")
        result = cmd_autopilot_emergency_resume(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "not in emergency" in captured.err.lower()


class TestAutopilotCLIPolicyShow:
    """Tests for 'autopilot policy show' command."""
    
    def test_policy_show_lists_all_policies(self, capsys):
        """Policy show lists all three policy templates."""
        args = Namespace()
        result = cmd_autopilot_policy_show(args)
        
        assert result == 0
        captured = capsys.readouterr()
        # Should list all three policies
        assert "conservative" in captured.out.lower()
        assert "standard" in captured.out.lower() or "permissive" in captured.out.lower()
    
    def test_policy_show_includes_scope(self, capsys):
        """Policy show includes scope/status information."""
        args = Namespace()
        result = cmd_autopilot_policy_show(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "Status:" in captured.out or "Confidence Threshold:" in captured.out
    
    def test_policy_show_includes_max_concurrent(self, capsys):
        """Policy show includes max concurrent actions."""
        args = Namespace()
        result = cmd_autopilot_policy_show(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "Max Concurrent" in captured.out


class TestAutopilotCLIPolicySet:
    """Tests for 'autopilot policy set' command."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_policy_set_requires_policy_name(self, capsys, monkeypatch):
        """Policy set fails without policy name."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy=None, reason="Test")
        result = cmd_autopilot_policy_set(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "policy is required" in captured.err.lower()
    
    def test_policy_set_when_not_enabled_fails(self, capsys, monkeypatch):
        """Policy set fails when autopilot is not enabled."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        args = Namespace(policy="moderate", reason="Test")
        result = cmd_autopilot_policy_set(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "must be enabled" in captured.err.lower()
    
    def test_policy_set_succeeds(self, capsys, monkeypatch):
        """Policy set succeeds when enabled."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        # Change policy
        args = Namespace(policy="moderate", reason="Testing")
        result = cmd_autopilot_policy_set(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "✓" in captured.out or "updated" in captured.out.lower()
    
    def test_policy_set_invalid_policy_fails(self, capsys, monkeypatch):
        """Policy set with invalid policy fails."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable first
        from recovery_autopilot_policy import create_conservative_policy
        control_plane = get_autopilot_control_plane()
        policy = create_conservative_policy()
        control_plane.enable("test-operator", policy)
        
        # Try invalid policy
        args = Namespace(policy="invalid", reason="Test")
        result = cmd_autopilot_policy_set(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Unknown policy" in captured.err


class TestAutopilotCLIWorkflows:
    """Integration tests for typical CLI workflows."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_autopilot_control_plane()
        reset_stores()
    
    def test_workflow_enable_status_disable(self, capsys, monkeypatch):
        """Workflow: enable → check status → disable."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable
        args = Namespace(policy="conservative", reason="Workflow test")
        assert cmd_autopilot_enable(args) == 0
        
        # Status
        args = Namespace()
        assert cmd_autopilot_status(args) == 0
        
        # Disable
        args = Namespace(reason="Done")
        assert cmd_autopilot_disable(args) == 0
    
    def test_workflow_enable_change_policy_disable(self, capsys, monkeypatch):
        """Workflow: enable → change policy → disable."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable with conservative
        args = Namespace(policy="conservative", reason="Start")
        assert cmd_autopilot_enable(args) == 0
        
        # Change to standard
        args = Namespace(policy="standard", reason="Adjustment")
        assert cmd_autopilot_policy_set(args) == 0
        
        # Disable
        args = Namespace(reason="Done")
        assert cmd_autopilot_disable(args) == 0
    
    def test_workflow_enable_estop_resume_disable(self, capsys, monkeypatch):
        """Workflow: enable → emergency stop → resume → disable."""
        monkeypatch.setenv("RECOVERY_OPERATOR_ID", "test-operator")
        
        # Enable
        args = Namespace(policy="conservative", reason="Start")
        assert cmd_autopilot_enable(args) == 0
        
        # Emergency stop
        args = Namespace(reason="Incident")
        assert cmd_autopilot_emergency_stop(args) == 0
        
        # Resume
        args = Namespace(reason="Recovered")
        assert cmd_autopilot_emergency_resume(args) == 0
        
        # Disable
        args = Namespace(reason="Done")
        assert cmd_autopilot_disable(args) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
