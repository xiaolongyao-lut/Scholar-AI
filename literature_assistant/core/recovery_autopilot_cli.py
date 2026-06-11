"""
Phase H4.1: Autopilot CLI Commands

Integration of autopilot control plane into recovery CLI.
Provides operator commands for enabling/disabling autopilot with policy management.

Commands:
  - status: Show autopilot control plane state and current policy
  - enable: Enable autopilot with explicit policy
  - disable: Disable autopilot
  - emergency-stop: Trigger emergency stop
  - emergency-resume: Resume from emergency stop
  - policy show: Display available policies
  - policy set: Change active policy

Design Principle: All commands emit canonical events via control plane for complete audit trail.
"""

import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any

# Local imports
try:
    from recovery_autopilot_control_plane import AutopilotControlPlane, ControlPlaneState
    from recovery_autopilot_policy import (
        create_conservative_policy,
        create_standard_policy,
        create_permissive_policy,
        AutopilotPolicy,
    )
    from recovery_store_provider import get_event_store, get_fact_store
    from datetime_utils import utc_now_iso_z
except ImportError as e:
    print(f"WARNING: Failed to import required modules: {e}", file=sys.stderr)
    print("WARNING: Autopilot CLI functionality will be restricted.", file=sys.stderr)

# Map policy names to their creation functions
POLICY_REGISTRY = {
    "conservative": create_conservative_policy,
    "standard": create_standard_policy,
    "permissive": create_permissive_policy,
}


# Global control plane instance (singleton)
_control_plane_instance: Optional[AutopilotControlPlane] = None


def reset_autopilot_control_plane() -> None:
    """Reset control plane singleton (for testing)."""
    global _control_plane_instance
    _control_plane_instance = None


def get_autopilot_control_plane() -> AutopilotControlPlane:
    """Get or create autopilot control plane singleton."""
    global _control_plane_instance
    if _control_plane_instance is None:
        _control_plane_instance = AutopilotControlPlane(
            event_store=get_event_store(),
            fact_store=get_fact_store(),
        )
    return _control_plane_instance


def _get_operator_id(args: Any = None) -> str:
    """Get current operator ID.

    优先级:args.operator_id(REST 入口显式传入,避免并发线程互相覆盖
    进程级环境变量) → ``RECOVERY_OPERATOR_ID`` env → ``"unknown-operator"``.
    """
    import os
    if args is not None:
        candidate = getattr(args, "operator_id", None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return os.environ.get("RECOVERY_OPERATOR_ID", "unknown-operator")


# --- Command: status ---


def cmd_autopilot_status(args: Any) -> int:
    """
    Show autopilot control plane state and current policy.
    
    Display:
      - Current state (DISABLED, ENABLED, EMERGENCY_STOPPED)
      - Current policy (if enabled)
      - Last state change timestamp
    """
    try:
        control_plane = get_autopilot_control_plane()
        status = control_plane.get_status()
        
        print("\n=== Autopilot Control Plane Status ===")
        print(f"State: {status['state']}")
        
        if status.get("policy"):
            policy_info = status["policy"]
            print(f"Policy: {policy_info.get('policy_name', 'N/A')}")
            print(f"  - Scope: {policy_info.get('scope', 'N/A')}")
            print(f"  - Max Concurrent: {policy_info.get('max_concurrent_actions', 'N/A')}")
        else:
            print("Policy: None (autopilot disabled)")
        
        if status.get("operator"):
            print(f"Enabled By: {status['operator']}")
        
        if status.get("timestamp"):
            print(f"Last Change: {status['timestamp']}")
        
        print("=" * 40)
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to get autopilot status: {e}", file=sys.stderr)
        return 1


# --- Command: enable ---


def cmd_autopilot_enable(args: Any) -> int:
    """
    Enable autopilot with explicit policy.
    
    Options:
      --policy <name>: Policy name (conservative, standard, permissive)
      --reason <text>: Reason for enabling (optional)
    """
    try:
        # Get policy by name
        policy_name = getattr(args, "policy", None) or "conservative"
        
        # Map "moderate" to "standard" for backwards-compat with tests
        normalized_name = policy_name
        if policy_name == "moderate":
            normalized_name = "standard"
        
        if normalized_name not in POLICY_REGISTRY:
            print(f"ERROR: Unknown policy '{policy_name}'", file=sys.stderr)
            print("Valid policies: conservative, standard, permissive", file=sys.stderr)
            return 1
        
        policy = POLICY_REGISTRY[normalized_name]()
        
        # Get reason
        reason = getattr(args, "reason", None) or f"Enabled via CLI at {utc_now_iso_z()}"
        
        # Get control plane and enable
        control_plane = get_autopilot_control_plane()
        operator_id = _get_operator_id(args)
        
        # Check if already enabled
        if control_plane.is_enabled():
            print(f"Autopilot already enabled with policy: {control_plane.get_current_policy().policy_name}", file=sys.stderr)
            return 1
        
        # Enable autopilot
        control_plane.enable(
            operator_id=operator_id,
            policy=policy,
            reason=reason,
        )
        
        print(f"✓ Autopilot enabled with policy '{policy_name}'")
        print(f"  Policy ID: {policy.policy_id}")
        print(f"  Operator: {operator_id}")
        print(f"  Reason: {reason}")
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to enable autopilot: {e}", file=sys.stderr)
        return 1


# --- Command: disable ---


def cmd_autopilot_disable(args: Any) -> int:
    """
    Disable autopilot.
    
    Options:
      --reason <text>: Reason for disabling (optional)
    """
    try:
        reason = getattr(args, "reason", None) or f"Disabled via CLI at {utc_now_iso_z()}"
        
        control_plane = get_autopilot_control_plane()
        operator_id = _get_operator_id(args)
        
        # Check if already disabled
        if not control_plane.is_enabled() and not control_plane.is_emergency_stopped():
            print("Autopilot already disabled", file=sys.stderr)
            return 1
        
        # Disable autopilot
        control_plane.disable(
            operator_id=operator_id,
            reason=reason,
        )
        
        print(f"✓ Autopilot disabled")
        print(f"  Operator: {operator_id}")
        print(f"  Reason: {reason}")
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to disable autopilot: {e}", file=sys.stderr)
        return 1


# --- Command: emergency-stop ---


def cmd_autopilot_emergency_stop(args: Any) -> int:
    """
    Trigger emergency stop on autopilot.
    
    Emergency stop immediately halts all autonomous execution and prevents resumption
    without explicit operator intervention.
    
    Options:
      --reason <text>: Reason for emergency stop (required)
    """
    try:
        reason = getattr(args, "reason", None)
        if not reason:
            print("ERROR: --reason is required for emergency-stop", file=sys.stderr)
            return 1
        
        control_plane = get_autopilot_control_plane()
        operator_id = _get_operator_id(args)
        
        # Check if already in emergency stop
        if control_plane.is_emergency_stopped():
            print("Autopilot already in emergency stop state", file=sys.stderr)
            return 1
        
        # Trigger emergency stop
        control_plane.emergency_stop(
            operator_id=operator_id,
            reason=reason,
        )
        
        print(f"🛑 EMERGENCY STOP activated")
        print(f"  State: {ControlPlaneState.EMERGENCY_STOPPED.value}")
        print(f"  Operator: {operator_id}")
        print(f"  Reason: {reason}")
        print(f"  Timestamp: {utc_now_iso_z()}")
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to trigger emergency stop: {e}", file=sys.stderr)
        return 1


# --- Command: emergency-resume ---


def cmd_autopilot_emergency_resume(args: Any) -> int:
    """
    Resume from emergency stop.
    
    Resume allows autopilot to re-enable after emergency stop.
    
    Options:
      --reason <text>: Reason for resuming (optional)
    """
    try:
        reason = getattr(args, "reason", None) or f"Resumed via CLI at {utc_now_iso_z()}"
        
        control_plane = get_autopilot_control_plane()
        operator_id = _get_operator_id(args)
        
        # Check if in emergency stop
        if not control_plane.is_emergency_stopped():
            print("Autopilot is not in emergency stop", file=sys.stderr)
            return 1
        
        # Resume from emergency
        control_plane.resume_from_emergency(
            operator_id=operator_id,
            reason=reason,
        )
        
        print(f"✓ Resumed from emergency stop")
        print(f"  State: ENABLED")
        print(f"  Operator: {operator_id}")
        print(f"  Reason: {reason}")
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to resume from emergency: {e}", file=sys.stderr)
        return 1


# --- Command: policy show ---


def cmd_autopilot_policy_show(args: Any) -> int:
    """
    Show available policies.
    
    Displays all available policy templates with scope and constraints.
    """
    try:
        print("\n=== Available Autopilot Policies ===\n")
        
        policies = [
            create_conservative_policy(),
            create_standard_policy(),
            create_permissive_policy(),
        ]
        
        for policy in policies:
            print(f"Policy: {policy.policy_name}")
            print(f"  ID: {policy.policy_id}")
            print(f"  Status: {policy.status.value if hasattr(policy.status, 'value') else policy.status}")
            print(f"  Confidence Threshold: {policy.global_confidence_threshold:.0%}")
            print(f"  Max Concurrent: {policy.global_max_concurrent_actions}")
            print(f"  Emergency Stop Enabled: {policy.enable_emergency_stop}")
            print(f"  Operator Override Enabled: {policy.enable_operator_override}")
            print()
        
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to list policies: {e}", file=sys.stderr)
        return 1


# --- Command: policy set ---


def cmd_autopilot_policy_set(args: Any) -> int:
    """
    Change the active autopilot policy.
    
    Options:
      --policy <name>: New policy name (conservative, standard, permissive)
      --reason <text>: Reason for policy change (optional)
    """
    try:
        policy_name = getattr(args, "policy", None)
        if not policy_name:
            print("ERROR: --policy is required", file=sys.stderr)
            return 1
        
        # Map "moderate" to "standard" for backwards-compat with tests
        normalized_name = policy_name
        if policy_name == "moderate":
            normalized_name = "standard"
        
        # Get policy by name
        if normalized_name not in POLICY_REGISTRY:
            print(f"ERROR: Unknown policy '{policy_name}'", file=sys.stderr)
            return 1
        
        policy = POLICY_REGISTRY[normalized_name]()
        reason = getattr(args, "reason", None) or f"Policy changed via CLI to {policy_name}"
        
        control_plane = get_autopilot_control_plane()
        operator_id = _get_operator_id(args)
        
        # Check if enabled
        if not control_plane.is_enabled():
            print("Autopilot must be enabled to change policy", file=sys.stderr)
            return 1
        
        # Update policy
        control_plane.set_policy(
            operator_id=operator_id,
            policy=policy,
            reason=reason,
        )
        
        print(f"✓ Policy updated to '{policy_name}'")
        print(f"  Policy ID: {policy.policy_id}")
        print(f"  Operator: {operator_id}")
        print(f"  Reason: {reason}")
        return 0
        
    except Exception as e:
        print(f"ERROR: Failed to set policy: {e}", file=sys.stderr)
        return 1


# --- CLI Registration ---


def register_autopilot_commands(parser) -> None:
    """
    Register autopilot subcommands with argparse parser.
    
    Expected parser structure:
      parser.add_subparsers(dest='subcommand')
      ...(other commands)...
      # Call this function to add autopilot commands
    """
    try:
        subparsers = parser._subparsers._actions[-1]  # Get existing subparsers
    except (IndexError, AttributeError):
        # Create subparsers if they don't exist
        subparsers = parser.add_subparsers(dest="subcommand")
    
    # Add autopilot parser
    autopilot_parser = subparsers.add_parser(
        "autopilot",
        help="Autopilot control plane commands",
    )
    
    # Autopilot subcommands
    autopilot_sub = autopilot_parser.add_subparsers(dest="autopilot_command")
    
    # status
    status_cmd = autopilot_sub.add_parser("status", help="Show autopilot status")
    status_cmd.set_defaults(func=cmd_autopilot_status)
    
    # enable
    enable_cmd = autopilot_sub.add_parser("enable", help="Enable autopilot")
    enable_cmd.add_argument(
        "--policy",
        choices=["conservative", "standard", "permissive"],
        default="conservative",
        help="Policy to enable (default: conservative)",
    )
    enable_cmd.add_argument("--reason", help="Reason for enabling")
    enable_cmd.set_defaults(func=cmd_autopilot_enable)
    
    # disable
    disable_cmd = autopilot_sub.add_parser("disable", help="Disable autopilot")
    disable_cmd.add_argument("--reason", help="Reason for disabling")
    disable_cmd.set_defaults(func=cmd_autopilot_disable)
    
    # emergency-stop
    estop_cmd = autopilot_sub.add_parser("emergency-stop", help="Trigger emergency stop")
    estop_cmd.add_argument("--reason", required=True, help="Reason for emergency stop")
    estop_cmd.set_defaults(func=cmd_autopilot_emergency_stop)
    
    # emergency-resume
    resume_cmd = autopilot_sub.add_parser("emergency-resume", help="Resume from emergency stop")
    resume_cmd.add_argument("--reason", help="Reason for resuming")
    resume_cmd.set_defaults(func=cmd_autopilot_emergency_resume)
    
    # policy show
    policy_parser = autopilot_sub.add_parser("policy", help="Policy management")
    policy_sub = policy_parser.add_subparsers(dest="policy_command")
    
    show_cmd = policy_sub.add_parser("show", help="Show available policies")
    show_cmd.set_defaults(func=cmd_autopilot_policy_show)
    
    set_cmd = policy_sub.add_parser("set", help="Change active policy")
    set_cmd.add_argument(
        "--policy",
        choices=["conservative", "standard", "permissive"],
        required=True,
        help="New policy name",
    )
    set_cmd.add_argument("--reason", help="Reason for policy change")
    set_cmd.set_defaults(func=cmd_autopilot_policy_set)


# Standalone CLI execution (for testing)
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Autopilot CLI")
    register_autopilot_commands(parser)
    
    args = parser.parse_args()
    
    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(0)
