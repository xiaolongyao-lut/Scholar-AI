"""Independent API for explicitly promoted, reviewed graph knowledge."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, NoReturn, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from literature_assistant.core.knowledge_graph.citation_store import (
    CitationCandidateStore,
    CitationStoreError,
)
from literature_assistant.core.knowledge_graph.reviewed_knowledge_models import (
    AcceptedCandidateReview,
    AcceptedGraphFact,
    PromoteAcceptedGraphFactRequest,
    ReviewedCandidateKind,
    ReviewedKnowledgeFreshnessRequest,
    ReviewedKnowledgeMutationResult,
    ReviewedKnowledgeReceipt,
    WithdrawAcceptedGraphFactRequest,
)
from literature_assistant.core.knowledge_graph.reviewed_knowledge_store import (
    ReviewedKnowledgeConflictError,
    ReviewedKnowledgeCorruptionError,
    ReviewedKnowledgeNotFoundError,
    ReviewedKnowledgeStore,
    ReviewedKnowledgeStoreError,
)
from literature_assistant.core.project_paths import project_data_path

router = APIRouter(prefix="/api/reviewed-knowledge", tags=["Reviewed Knowledge"])
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")


class AcceptedReviewReceiptProvider(Protocol):
    """Lookup contract for canonical, durable candidate review receipts."""

    def find_accepted_review(
        self,
        *,
        project_id: str,
        target_kind: ReviewedCandidateKind,
        candidate_id: str,
        decision_receipt_id: str,
    ) -> AcceptedCandidateReview | None:
        """Return canonical accepted-review evidence or ``None`` when unproven."""


class AcceptedReviewReceiptProviderError(RuntimeError):
    """Raised when a configured review ledger cannot be read safely."""


class ProjectAcceptedReviewReceiptProvider:
    """Verify only review sources that expose a complete durable receipt.

    Citation lifecycle events currently prove project, candidate, accepted
    state, actor, and decision time in one SQLite transaction. Other candidate
    families are rejected until they expose an equivalent immutable receipt;
    their mutable status rows alone are not promotion evidence.
    """

    def find_accepted_review(
        self,
        *,
        project_id: str,
        target_kind: ReviewedCandidateKind,
        candidate_id: str,
        decision_receipt_id: str,
    ) -> AcceptedCandidateReview | None:
        """Read one canonical accepted citation review without creating a ledger."""

        if target_kind != "citation":
            return None
        db_path = project_data_path(project_id, "citation_graph", "citation_graph.db")
        try:
            if not db_path.is_file() or db_path.stat().st_size <= 0:
                return None
            store = CitationCandidateStore(db_path)
            candidate = store.get_candidate(candidate_id)
            if (
                candidate is None
                or candidate.project_id != project_id
                or candidate.review_status != "accepted"
                or candidate.freshness_status != "fresh"
            ):
                return None
            events = store.list_transition_events(
                candidate_id=candidate_id,
                axis="review",
                limit=500,
            )
        except (CitationStoreError, OSError, ValueError) as exc:
            raise AcceptedReviewReceiptProviderError(
                "citation review receipt ledger is unavailable"
            ) from exc

        for event in events:
            if (
                event.event_id == decision_receipt_id
                and event.project_id == project_id
                and event.candidate_id == candidate_id
                and event.axis == "review"
                and event.to_status == "accepted"
            ):
                return AcceptedCandidateReview(
                    project_id=event.project_id,
                    target_kind="citation",
                    candidate_id=event.candidate_id,
                    decision="accepted",
                    decision_receipt_id=event.event_id,
                    decided_by=event.changed_by,
                    decided_at=event.occurred_at,
                )
        return None


class ReviewedKnowledgeMutationResponse(BaseModel):
    """API result for a committed or idempotently replayed mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact: AcceptedGraphFact
    receipt: ReviewedKnowledgeReceipt
    replayed: bool


_DEFAULT_REVIEW_PROVIDER = ProjectAcceptedReviewReceiptProvider()


def get_accepted_review_receipt_provider() -> AcceptedReviewReceiptProvider:
    """Return the injectable canonical accepted-review receipt provider."""

    return _DEFAULT_REVIEW_PROVIDER


def reviewed_knowledge_db_path(project_id: str) -> Path:
    """Return the independent project ledger path for accepted graph facts."""

    normalized = str(project_id or "").strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError("project_id has an unsupported identifier shape")
    return project_data_path(normalized, "reviewed_knowledge", "reviewed_knowledge.db")


def get_reviewed_knowledge_store(project_id: str) -> ReviewedKnowledgeStore:
    """Open the independent project-scoped reviewed-knowledge store."""

    return ReviewedKnowledgeStore(reviewed_knowledge_db_path(project_id))


def _verified_review_or_409(
    request: PromoteAcceptedGraphFactRequest,
    provider: AcceptedReviewReceiptProvider,
) -> AcceptedCandidateReview:
    try:
        verified = provider.find_accepted_review(
            project_id=request.project_id,
            target_kind=request.accepted_review.target_kind,
            candidate_id=request.accepted_review.candidate_id,
            decision_receipt_id=request.accepted_review.decision_receipt_id,
        )
    except AcceptedReviewReceiptProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail="accepted review receipt ledger is unavailable",
        ) from exc
    if verified is None:
        raise HTTPException(
            status_code=409,
            detail="accepted review receipt could not be verified",
        )
    if verified != request.accepted_review:
        raise HTTPException(
            status_code=409,
            detail="accepted review receipt does not match the promotion request",
        )
    if verified.decided_at > request.requested_at:
        raise HTTPException(
            status_code=409,
            detail="accepted review receipt postdates the promotion request",
        )
    return verified


def _mutation_response(
    result: ReviewedKnowledgeMutationResult,
) -> ReviewedKnowledgeMutationResponse:
    return ReviewedKnowledgeMutationResponse(
        fact=result.fact,
        receipt=result.receipt,
        replayed=result.replayed,
    )


def _raise_store_http_error(exc: ReviewedKnowledgeStoreError) -> NoReturn:
    if isinstance(exc, ReviewedKnowledgeNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ReviewedKnowledgeConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ReviewedKnowledgeCorruptionError):
        raise HTTPException(
            status_code=500,
            detail="reviewed-knowledge ledger contains invalid data",
        ) from exc
    raise HTTPException(
        status_code=500, detail="reviewed-knowledge ledger unavailable"
    ) from exc


@router.post(
    "/facts/promote",
    response_model=ReviewedKnowledgeMutationResponse,
)
def promote_accepted_graph_fact(
    request: PromoteAcceptedGraphFactRequest,
    review_provider: AcceptedReviewReceiptProvider = Depends(
        get_accepted_review_receipt_provider
    ),
) -> ReviewedKnowledgeMutationResponse:
    """Explicitly promote one separately accepted candidate into the fact ledger."""

    _verified_review_or_409(request, review_provider)
    try:
        result = get_reviewed_knowledge_store(request.project_id).promote(request)
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return _mutation_response(result)


@router.post(
    "/facts/mark-stale",
    response_model=ReviewedKnowledgeMutationResponse,
)
def mark_accepted_graph_fact_stale(
    request: ReviewedKnowledgeFreshnessRequest,
) -> ReviewedKnowledgeMutationResponse:
    """Mark one active fresh fact stale using exact source-revision evidence."""

    if request.operation != "mark_stale":
        raise HTTPException(status_code=422, detail="operation must be mark_stale")
    try:
        result = get_reviewed_knowledge_store(request.project_id).transition_freshness(
            request
        )
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return _mutation_response(result)


@router.post(
    "/facts/revalidate",
    response_model=ReviewedKnowledgeMutationResponse,
)
def revalidate_accepted_graph_fact(
    request: ReviewedKnowledgeFreshnessRequest,
) -> ReviewedKnowledgeMutationResponse:
    """Revalidate one stale fact using the complete provenance locator set."""

    if request.operation != "revalidate":
        raise HTTPException(status_code=422, detail="operation must be revalidate")
    try:
        result = get_reviewed_knowledge_store(request.project_id).transition_freshness(
            request
        )
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return _mutation_response(result)


@router.post(
    "/facts/withdraw",
    response_model=ReviewedKnowledgeMutationResponse,
)
def withdraw_accepted_graph_fact(
    request: WithdrawAcceptedGraphFactRequest,
) -> ReviewedKnowledgeMutationResponse:
    """Withdraw one fact while retaining all revisions and receipts."""

    try:
        result = get_reviewed_knowledge_store(request.project_id).withdraw(request)
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return _mutation_response(result)


@router.get(
    "/projects/{project_id}/facts/{fact_id}",
    response_model=AcceptedGraphFact,
)
def read_accepted_graph_fact(project_id: str, fact_id: str) -> AcceptedGraphFact:
    """Read one project-scoped current fact without invoking Wiki or graph code."""

    try:
        fact = get_reviewed_knowledge_store(project_id).get_fact(
            project_id=project_id,
            fact_id=fact_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    if fact is None:
        raise HTTPException(status_code=404, detail="accepted graph fact was not found")
    return fact


@router.get(
    "/projects/{project_id}/facts",
    response_model=list[AcceptedGraphFact],
)
def list_accepted_graph_facts(
    project_id: str,
    freshness_status: Literal["fresh", "stale"] | None = None,
    availability_status: Literal["active", "withdrawn"] | None = "active",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AcceptedGraphFact]:
    """List a bounded project-scoped current-fact page."""

    try:
        facts = get_reviewed_knowledge_store(project_id).list_facts(
            project_id=project_id,
            freshness_status=freshness_status,
            availability_status=availability_status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return list(facts)


@router.get(
    "/projects/{project_id}/facts/{fact_id}/revisions",
    response_model=list[AcceptedGraphFact],
)
def list_accepted_graph_fact_revisions(
    project_id: str,
    fact_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AcceptedGraphFact]:
    """List immutable revisions for one project-scoped fact."""

    try:
        revisions = get_reviewed_knowledge_store(project_id).list_fact_revisions(
            project_id=project_id,
            fact_id=fact_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return list(revisions)


@router.get(
    "/projects/{project_id}/receipts/{operation_id}",
    response_model=ReviewedKnowledgeReceipt,
)
def read_reviewed_knowledge_receipt(
    project_id: str,
    operation_id: str,
) -> ReviewedKnowledgeReceipt:
    """Read one durable mutation receipt by project and idempotency key."""

    try:
        receipt = get_reviewed_knowledge_store(project_id).get_receipt(
            project_id=project_id,
            operation_id=operation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    if receipt is None:
        raise HTTPException(
            status_code=404, detail="reviewed-knowledge receipt was not found"
        )
    return receipt


@router.get(
    "/projects/{project_id}/receipts",
    response_model=list[ReviewedKnowledgeReceipt],
)
def list_reviewed_knowledge_receipts(
    project_id: str,
    fact_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ReviewedKnowledgeReceipt]:
    """List bounded durable mutation receipts for one project."""

    try:
        receipts = get_reviewed_knowledge_store(project_id).list_receipts(
            project_id=project_id,
            fact_id=fact_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewedKnowledgeStoreError as exc:
        _raise_store_http_error(exc)
    return list(receipts)


__all__ = [
    "AcceptedReviewReceiptProvider",
    "AcceptedReviewReceiptProviderError",
    "ProjectAcceptedReviewReceiptProvider",
    "ReviewedKnowledgeMutationResponse",
    "get_accepted_review_receipt_provider",
    "get_reviewed_knowledge_store",
    "reviewed_knowledge_db_path",
    "router",
]
