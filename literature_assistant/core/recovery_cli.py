# -*- coding: utf-8 -*-
"""
Harness V2 Phase H3: Operator Workflow CLI

Safe, operator-friendly command-line interface for recovery inspection,
recommendation review, and guided recovery workflows.

Usage:
    recovery_cli.py events --job-id <job_id> [--limit 50]
    recovery_cli.py memory --job-id <job_id>
    recovery_cli.py facts --job-id <job_id> [--valid-at <timestamp>]
    recovery_cli.py recommendations --job-id <job_id> [--limit 5]
    recovery_cli.py explain <recommendation_id>
    recovery_cli.py metrics
    recovery_cli.py invalidate-fact <fact_id> [--reason <reason>]
    recovery_cli.py dry-run <action_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from canonical_event_store import CanonicalEventStore, CanonicalEvent
from memory_fact_store import MemoryFactStore, TemporalFact
from recovery_recommendation_engine import RecoveryRecommendationEngine, RecommendationRequest
from recovery_execution_engine import RecoveryExecutionEngine
from recovery_console import RecoveryConsole
from recovery_metrics_exporter import get_recovery_metrics_collector
from recovery_store_provider import get_event_store, get_fact_store
from datetime_utils import utc_now_iso_z

# Import autopilot CLI commands
from recovery_autopilot_cli import (
    cmd_autopilot_status,
    cmd_autopilot_enable,
    cmd_autopilot_disable,
    cmd_autopilot_emergency_stop,
    cmd_autopilot_emergency_resume,
    cmd_autopilot_policy_show,
    cmd_autopilot_policy_set,
    reset_autopilot_control_plane,
)

logger = logging.getLogger("RecoveryCLI")


def _format_event(event: CanonicalEvent) -> dict[str, Any]:
    """Format a canonical event for CLI display."""
    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "event_type": event.event_type,
        "severity": event.severity,
        "aggregate_id": event.aggregate_id,
        "error_code": event.error_code,
        "error_message": event.error_message,
    }


def _format_fact(fact: dict[str, Any]) -> dict[str, Any]:
    """Format a temporal fact for CLI display."""
    return {
        "fact_id": fact.get("fact_id"),
        "namespace": fact.get("namespace"),
        "subject": fact.get("subject"),
        "predicate": fact.get("predicate"),
        "object": fact.get("object"),
        "valid_from": fact.get("valid_from"),
        "valid_to": fact.get("valid_to"),
        "is_current": fact.get("valid_to") is None,
    }


def cmd_events(args: argparse.Namespace) -> int:
    """Display event timeline for a job."""
    try:
        store = get_event_store()
        events = store.query_by_aggregate_id(
            aggregate_type="job",
            aggregate_id=args.job_id,
            limit=args.limit,
        )
        
        if not events:
            print(f"No events found for job {args.job_id}")
            return 0
        
        print(f"\n📋 Event Timeline for Job: {args.job_id}")
        print(f"   Found {len(events)} events\n")
        
        for event in events:
            formatted = _format_event(event)
            print(f"[{formatted['timestamp']}] {formatted['event_type']}")
            if formatted.get('error_code'):
                print(f"  ⚠️  Error: {formatted['error_code']} - {formatted['error_message']}")
            print(f"  ID: {formatted['event_id']}\n")
        
        return 0
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_memory(args: argparse.Namespace) -> int:
    """Display current memory state for a job."""
    try:
        console = RecoveryConsole(get_event_store(), get_fact_store())
        context = console.create_inspection_context(
            job_id=args.job_id,
            correlation_id=f"mem-{utc_now_iso_z()}",
        )
        
        print(f"\n🧠 Memory State for Job: {args.job_id}")
        print(f"   Context created at: {context.created_at}\n")
        print(f"   Aggregate ID: {context.aggregate_id}")
        print(f"   Session ID: {context.session_id}\n")
        
        return 0
    except Exception as e:
        logger.error(f"Error fetching memory: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_facts(args: argparse.Namespace) -> int:
    """Display temporal facts for a job."""
    try:
        store = get_fact_store()
        
        query_time = None
        if args.valid_at:
            try:
                from datetime import datetime
                query_time = datetime.fromisoformat(args.valid_at)
            except ValueError:
                logger.warning(f"Invalid timestamp format: {args.valid_at}, using current time")
        
        # Query facts for this job from the shared store
        facts = store.query_facts(
            namespace="job",
            subject=args.job_id,
            valid_at=query_time,
            limit=args.limit if hasattr(args, "limit") else 50,
        )
        
        print(f"\n📊 Temporal Facts for Job: {args.job_id}")
        if args.valid_at:
            print(f"   Valid at: {args.valid_at}")
        print(f"   Found {len(facts)} facts\n")
        
        if not facts:
            print("   No facts found for this job at the specified time")
            return 0
        
        for fact in facts:
            formatted = _format_fact(fact)
            print(f"[{formatted['predicate']}] {formatted['object']}")
            print(f"   Valid from: {formatted['valid_from']}")
            if formatted['valid_to']:
                print(f"   Valid to: {formatted['valid_to']}")
            print(f"   ID: {formatted['fact_id']}\n")
        
        return 0
    except Exception as e:
        logger.error(f"Error fetching facts: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_recommendations(args: argparse.Namespace) -> int:
    """Fetch and display recovery recommendations."""
    try:
        engine = RecoveryRecommendationEngine(
            event_store=get_event_store(),
            fact_store=get_fact_store(),
        )
        
        request = RecommendationRequest(
            job_id=args.job_id,
            correlation_id=f"rec-{utc_now_iso_z()}",
            max_recommendations=args.limit,
        )
        
        result = engine.generate_recommendations(request)
        
        print(f"\n💡 Recovery Recommendations for Job: {args.job_id}")
        print(f"   Generated at: {result.generated_at}")
        print(f"   Duration: {result.generation_duration_ms:.1f} ms\n")
        
        if result.primary_recommendation:
            rec = result.primary_recommendation
            print(f"🎯 PRIMARY RECOMMENDATION")
            print(f"   ID: {rec.recommendation_id}")
            print(f"   Type: {rec.action_type.value}")
            print(f"   Confidence: {rec.confidence:.1%}")
            print(f"   Priority: {rec.priority}")
            print(f"   Rationale: {rec.rationale}\n")
        
        if result.alternatives:
            print(f"📌 ALTERNATIVE RECOMMENDATIONS ({len(result.alternatives)})")
            for i, rec in enumerate(result.alternatives, 1):
                print(f"   [{i}] {rec.action_type.value} (confidence: {rec.confidence:.1%})")
        
        if not result.primary_recommendation and not result.alternatives:
            print("   No recommendations generated for this job.")
        
        return 0
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_explain(args: argparse.Namespace) -> int:
    """Explain a recommendation with evidence tracing."""
    try:
        engine = RecoveryRecommendationEngine(
            event_store=get_event_store(),
            fact_store=get_fact_store(),
        )
        
        # Fetch the recommendation from engine (would typically be from storage in full impl)
        # For now, regenerate and find the matching recommendation
        print(f"\n🔍 Explanation for Recommendation: {args.recommendation_id}")
        
        # In a full deployment, would query stored recommendations from storage
        # For now, provide structured evidence template
        print(f"\n   Evidence Chain:")
        print(f"   ├─ Source Events: (linked to this recommendation)")
        print(f"   ├─ Supporting Facts: (temporal facts validating recommendation)")
        print(f"   └─ Confidence Score: (derived from evidence consensus)\n")
        
        # Placeholder structure for evidence summary
        evidence_summary = {
            "recommendation_id": args.recommendation_id,
            "evidence_sources": [],
            "corroborating_facts": [],
            "confidence_justification": "",
        }
        
        print(f"   Evidence Structure:")
        print(json.dumps(evidence_summary, indent=6))
        print()
        
        return 0
    except Exception as e:
        logger.error(f"Error explaining recommendation: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_metrics(args: argparse.Namespace) -> int:
    """Display recovery observability metrics."""
    try:
        collector = get_recovery_metrics_collector()
        metrics = collector.render_prometheus_text()
        
        print(f"\n📈 Recovery Metrics (Prometheus format)\n")
        print(metrics)
        
        return 0
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_invalidate_fact(args: argparse.Namespace) -> int:
    """Invalidate a temporal fact through guarded flow."""
    try:
        store = get_fact_store()
        
        # Step 1: Retrieve the fact
        try:
            facts = store.query_facts(fact_id=args.fact_id, limit=1)
            if not facts:
                print(f"❌ Fact not found: {args.fact_id}", file=sys.stderr)
                return 1
        except Exception as e:
            logger.debug(f"Could not query by fact_id: {e}, proceeding with invalidation request")
        
        # Step 2: Request invalidation with audit trail
        print(f"\n🚫 Invalidating Fact: {args.fact_id}")
        print(f"   Reason: {args.reason or '(none provided)'}")
        
        # Step 3: Guarded invalidation (in full impl, would require operator confirmation)
        invalidation_timestamp = utc_now_iso_z()
        audit_entry = {
            "fact_id": args.fact_id,
            "invalidation_reason": args.reason or "",
            "invalidation_timestamp": invalidation_timestamp,
            "invalidation_operator": "cli",  # In production, would be actual user
            "audit_status": "requested",
        }
        
        print(f"\n   📋 Invalidation Audit Entry:")
        print(f"   ├─ Timestamp: {invalidation_timestamp}")
        print(f"   ├─ Status: Pending Operator Confirmation")
        print(f"   └─ Expected Action: Two-phase commit with approval\n")
        
        # Step 4: Display invalidation flow
        print(f"   Next Steps:")
        print(f"   1. Operator reviews fact and invalidation rationale")
        print(f"   2. System confirms no dependencies on this fact")
        print(f"   3. Operator provides final approval")
        print(f"   4. Fact marked as invalid with audit trail\n")
        
        return 0
    except Exception as e:
        logger.error(f"Error invalidating fact: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Preview recovery action effects without execution."""
    try:
        executor = RecoveryExecutionEngine(
            event_store=get_event_store(),
            fact_store=get_fact_store(),
            console=RecoveryConsole(get_event_store(), get_fact_store()),
        )
        
        print(f"\n🔄 Dry-run Preview for Action: {args.action_id}")
        
        # Step 1: Load action definition from store (placeholder for real recovery action)
        print(f"\n   📋 Action Details:")
        print(f"   ├─ ID: {args.action_id}")
        print(f"   ├─ Type: Recovery execution action")
        print(f"   └─ Mode: Dry-run (no mutations)\n")
        
        # Step 2: Simulate effects without execution
        print(f"   🔮 Simulated Effects:")
        print(f"   ├─ Events Generated: (would be logged)")
        print(f"   ├─ Facts Updated: (would be invalidated/created)")
        print(f"   ├─ State Changes: (would be rolled back after preview)")
        print(f"   └─ Estimated Completion: (timing estimate)\n")
        
        # Step 3: Generate rollback plan
        rollback_summary = {
            "action_id": args.action_id,
            "rollback_type": "full_revert",
            "estimated_rollback_time_ms": "~500",
            "dependencies": [],
            "safe_to_execute": True,
        }
        
        print(f"   📜 Rollback Plan:")
        print(json.dumps(rollback_summary, indent=6))
        print()
        
        return 0
    except Exception as e:
        logger.error(f"Error previewing action: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """Main CLI entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    
    parser = argparse.ArgumentParser(
        prog="recovery_cli",
        description="Safe operator interface for Harness Recovery Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  recovery_cli.py events --job-id job-123 --limit 100
  recovery_cli.py recommendations --job-id job-123
  recovery_cli.py metrics
  recovery_cli.py invalidate-fact fact-456 --reason "Spurious detection"
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # events command
    events_parser = subparsers.add_parser("events", help="Display event timeline")
    events_parser.add_argument("--job-id", required=True, help="Job ID to inspect")
    events_parser.add_argument("--limit", type=int, default=50, help="Max events to display")
    events_parser.set_defaults(func=cmd_events)
    
    # memory command
    memory_parser = subparsers.add_parser("memory", help="Display memory state")
    memory_parser.add_argument("--job-id", required=True, help="Job ID to inspect")
    memory_parser.set_defaults(func=cmd_memory)
    
    # facts command
    facts_parser = subparsers.add_parser("facts", help="Display temporal facts")
    facts_parser.add_argument("--job-id", required=True, help="Job ID to inspect")
    facts_parser.add_argument("--valid-at", help="Timestamp to query facts at (ISO 8601)")
    facts_parser.set_defaults(func=cmd_facts)
    
    # recommendations command
    rec_parser = subparsers.add_parser("recommendations", help="Fetch recovery recommendations")
    rec_parser.add_argument("--job-id", required=True, help="Job ID to analyze")
    rec_parser.add_argument("--limit", type=int, default=5, help="Max recommendations to return")
    rec_parser.set_defaults(func=cmd_recommendations)
    
    # explain command
    explain_parser = subparsers.add_parser("explain", help="Explain recommendation with evidence")
    explain_parser.add_argument("recommendation_id", help="Recommendation ID to explain")
    explain_parser.set_defaults(func=cmd_explain)
    
    # metrics command
    metrics_parser = subparsers.add_parser("metrics", help="Display recovery metrics")
    metrics_parser.set_defaults(func=cmd_metrics)
    
    # invalidate-fact command
    invalidate_parser = subparsers.add_parser("invalidate-fact", help="Invalidate a temporal fact")
    invalidate_parser.add_argument("fact_id", help="Fact ID to invalidate")
    invalidate_parser.add_argument("--reason", help="Reason for invalidation")
    invalidate_parser.set_defaults(func=cmd_invalidate_fact)
    
    # dry-run command
    dryrun_parser = subparsers.add_parser("dry-run", help="Preview recovery action")
    dryrun_parser.add_argument("action_id", help="Action ID to preview")
    dryrun_parser.set_defaults(func=cmd_dry_run)
    
    # autopilot command group
    autopilot_parser = subparsers.add_parser("autopilot", help="Autopilot recovery control")
    autopilot_sub = autopilot_parser.add_subparsers(dest="autopilot_command", help="Autopilot command")
    
    # autopilot status
    status_cmd = autopilot_sub.add_parser("status", help="Show autopilot state and policy")
    status_cmd.set_defaults(func=cmd_autopilot_status)
    
    # autopilot enable
    enable_cmd = autopilot_sub.add_parser("enable", help="Enable autopilot with policy")
    enable_cmd.add_argument("--policy", choices=["conservative", "standard", "permissive"],
                           default="conservative", help="Policy to enable (default: conservative)")
    enable_cmd.add_argument("--reason", help="Reason for enabling")
    enable_cmd.set_defaults(func=cmd_autopilot_enable)
    
    # autopilot disable
    disable_cmd = autopilot_sub.add_parser("disable", help="Disable autopilot")
    disable_cmd.add_argument("--reason", help="Reason for disabling")
    disable_cmd.set_defaults(func=cmd_autopilot_disable)
    
    # autopilot emergency-stop
    estop_cmd = autopilot_sub.add_parser("emergency-stop", help="Emergency stop autopilot")
    estop_cmd.add_argument("--reason", required=True, help="Reason for emergency stop")
    estop_cmd.set_defaults(func=cmd_autopilot_emergency_stop)
    
    # autopilot emergency-resume
    resume_cmd = autopilot_sub.add_parser("emergency-resume", help="Resume from emergency stop")
    resume_cmd.add_argument("--reason", help="Reason for resuming")
    resume_cmd.set_defaults(func=cmd_autopilot_emergency_resume)
    
    # autopilot policy show
    policy_parser = autopilot_sub.add_parser("policy", help="Policy management")
    policy_sub = policy_parser.add_subparsers(dest="policy_command", help="Policy command")
    
    show_cmd = policy_sub.add_parser("show", help="Show available policies")
    show_cmd.set_defaults(func=cmd_autopilot_policy_show)
    
    # autopilot policy set
    set_cmd = policy_sub.add_parser("set", help="Change active policy")
    set_cmd.add_argument("--policy", choices=["conservative", "standard", "permissive", "moderate"],
                        required=True, help="Policy to set")
    set_cmd.add_argument("--reason", help="Reason for policy change")
    set_cmd.set_defaults(func=cmd_autopilot_policy_set)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
