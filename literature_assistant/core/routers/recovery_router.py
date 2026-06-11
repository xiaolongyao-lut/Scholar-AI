# -*- coding: utf-8 -*-
"""Recovery API Router - Final version with complete recommendations alignment."""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from models import (
    RecoveryEventPayload,
    EventTimelinePayload,
    MemoryFactPayload,
    MemorySnapshotPayload,
    InvalidFactRequest,
    FactInvalidationPayload,
    RecommendationsResponsePayload,
    RecoveryRecommendationPayload,
    RecommendationEvidencePayload,
)
from recovery_console import InspectionContext
from datetime_utils import to_iso_z

logger = logging.getLogger("RecoveryRouter")
router = APIRouter(prefix="/recovery", tags=["Recovery"])


def get_console():
    """Import and return the shared recovery console."""
    from python_adapter_server import get_recovery_console
    return get_recovery_console()


@router.get("/events", response_model=EventTimelinePayload)
async def get_recovery_events(
    session_id: str | None = Query(None),
    job_id: str | None = Query(None),
    time_filter: str | None = Query(None),
) -> EventTimelinePayload:
    """Get event timeline for recovery inspection."""
    try:
        console = get_console()
        context = InspectionContext(
            session_id=session_id,
            job_id=job_id,
        )
        timeline = console.inspect_event_timeline(context)
        
        events = [
            RecoveryEventPayload(
                event_id=evt.event_id,
                event_type=evt.event_type,
                timestamp=evt.timestamp.isoformat() if hasattr(evt.timestamp, 'isoformat') else str(evt.timestamp),
                source_job_id=getattr(evt, 'source_job_id', None),
                source_session_id=getattr(evt, 'source_session_id', None),
                event_data=getattr(evt, 'event_data', {}),
            )
            for evt in timeline.events
        ]
        
        return EventTimelinePayload(
            events=events,
            event_count=timeline.event_count,
            start_time=timeline.earliest_timestamp.isoformat() if hasattr(timeline.earliest_timestamp, "isoformat") else None,
            end_time=timeline.latest_timestamp.isoformat() if hasattr(timeline.latest_timestamp, "isoformat") else None,
            session_filter=session_id,
            job_filter=job_id,
        )
    except Exception as exc:
        logger.error("Failed to fetch recovery events: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch recovery events")


@router.get("/memory", response_model=MemorySnapshotPayload)
async def get_recovery_memory(
    session_id: str | None = Query(None),
    job_id: str | None = Query(None),
) -> MemorySnapshotPayload:
    """Get current memory state snapshot."""
    try:
        console = get_console()
        context = InspectionContext(
            session_id=session_id or "inspection",
            job_id=job_id
        )
        snapshot = console.inspect_memory_state(context)
        
        facts = [
            MemoryFactPayload(
                fact_id=fact.fact_id,
                namespace=fact.namespace,
                subject=fact.subject,
                predicate=fact.predicate,
                object=fact.object,
                object_type=getattr(fact, 'object_type', 'string'),
                valid_from=fact.valid_from.isoformat() if hasattr(fact.valid_from, 'isoformat') else str(fact.valid_from),
                valid_to=fact.valid_to.isoformat() if hasattr(fact.valid_to, 'isoformat') and fact.valid_to else None,
                source_event_id=fact.source_event_id,
            )
            for fact in snapshot.current_facts
        ]
        
        return MemorySnapshotPayload(
            facts=facts,
            fact_count=snapshot.fact_count,
            namespaces=list(snapshot.namespaces),
            last_updated=snapshot.timestamp.isoformat() if hasattr(snapshot.timestamp, 'isoformat') else str(snapshot.timestamp),
            session_filter=session_id or "inspection",
        )
    except Exception as exc:
        logger.error("Failed to fetch memory snapshot: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch memory snapshot")


@router.post("/facts/invalidate", response_model=FactInvalidationPayload)
async def invalidate_fact(request: InvalidFactRequest) -> FactInvalidationPayload:
    """Invalidate a fact discovered erroneously."""
    try:
        console = get_console()
        invalidation = console.invalidate_fact(
            fact_id=request.fact_id,
            namespace=request.namespace,
            reason=request.reason,
            invalidated_by=request.invalidated_by,
        )
        return FactInvalidationPayload(
            fact_id=invalidation.fact_id,
            namespace=invalidation.namespace,
            reason=invalidation.reason,
            previous_value=getattr(invalidation, 'previous_value', None),
            invalidated_at=invalidation.invalidated_at.isoformat() if hasattr(invalidation.invalidated_at, 'isoformat') else str(invalidation.invalidated_at),
            invalidated_by=invalidation.invalidated_by,
            success=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to invalidate fact: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to invalidate fact")


def _to_recommendation_payload(rec) -> RecoveryRecommendationPayload:
    """Helper to convert a recommendation object to its payload."""
    return RecoveryRecommendationPayload(
        recommendation_id=rec.recommendation_id,
        job_id=rec.job_id,
        action_type=rec.action_type.value,
        rationale=rec.rationale,
        confidence=rec.confidence,
        priority=rec.priority,
        approval_level=rec.approval_level.name,
        dry_run_preview=rec.dry_run_preview,
        time_to_remediate_minutes=int(rec.time_to_remediate.total_seconds() / 60) if rec.time_to_remediate else None,
        risk_level=rec.risk_level,
        risk_description=rec.risk_description,
        reversibility=rec.reversibility,
        evidence=[
            RecommendationEvidencePayload(
                source_type=e.source_type,
                source_id=e.source_id,
                relevance=e.relevance,
                description=e.description,
            )
            for e in rec.evidence
        ],
        source_event_ids=rec.source_event_ids,
        source_fact_ids=rec.source_fact_ids,
        memory_hit_ids=rec.memory_hit_ids,
        created_at=to_iso_z(rec.created_at),
    )


@router.get("/recommendations", response_model=RecommendationsResponsePayload)
async def get_recovery_recommendations(
    job_id: str = Query(...),
    session_id: str | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
) -> RecommendationsResponsePayload:
    """Get recovery recommendations for a job."""
    try:
        from python_adapter_server import get_event_store, get_fact_store, get_memory_adapter
        event_store = get_event_store()
        fact_store = get_fact_store()
        memory_adapter = get_memory_adapter()
        
        from recovery_recommendation_engine import RecoveryRecommendationEngine, RecommendationRequest
        engine = RecoveryRecommendationEngine(event_store, fact_store, memory_adapter=memory_adapter)
        
        request = RecommendationRequest(
            session_id=session_id or job_id,
            job_id=job_id,
            max_recommendations=limit,
            include_alternatives=True,
        )
        result = engine.generate_recommendations(request)
        
        primary_payload = _to_recommendation_payload(result.primary_recommendation) if result.primary_recommendation else None
        alternatives_payloads = [_to_recommendation_payload(rec) for rec in result.alternatives]
        
        return RecommendationsResponsePayload(
            request_id=result.request_id,
            generated_at=to_iso_z(result.generated_at),
            primary_recommendation=primary_payload,
            alternatives=alternatives_payloads,
            total_evidence_considered=result.total_evidence_considered,
            generation_duration_ms=result.generation_duration_ms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to generate recommendations: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate recovery recommendations")


@router.get("/health")
async def recovery_health_check():
    """Consistency-enforced recovery stack health check."""
    from python_adapter_server import get_event_store, get_fact_store
    try:
        event_store = get_event_store()
        fact_store = get_fact_store()
        from datetime_utils import utc_now_iso_z
        return {
            "status": "healthy",
            "components": {
                "event_store": "ok",
                "fact_store": "ok",
                "metrics": "ok",
            },
            "timestamp": utc_now_iso_z(),
        }
    except Exception as e:
        logger.error("Recovery health check failed: %s", str(e))
        raise HTTPException(status_code=503, detail=str(e))
@router.get("/metrics")
async def get_recovery_metrics():
    """Expose recovery observability metrics in Prometheus format."""
    from recovery_metrics_exporter import get_recovery_metrics_collector
    collector = get_recovery_metrics_collector()
    from fastapi import Response
    return Response(content=collector.render_prometheus_text(), media_type="text/plain")
