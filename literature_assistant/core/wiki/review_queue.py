from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Iterable, Iterator, Mapping, TypeAlias
from uuid import uuid4

from literature_assistant.core.project_paths import wiki_review_queue_path


_QUEUE_LOCKS_GUARD = RLock()
_QUEUE_LOCKS: dict[Path, RLock] = {}


def _queue_lock(queue_path: Path) -> RLock:
    resolved = queue_path.expanduser().resolve()
    with _QUEUE_LOCKS_GUARD:
        lock = _QUEUE_LOCKS.get(resolved)
        if lock is None:
            lock = RLock()
            _QUEUE_LOCKS[resolved] = lock
        return lock


class ReviewItemStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ReviewItemKind(str, Enum):
    draft = "draft"
    fail = "fail"
    warning = "warning"
    manual_edit = "manual_edit"
    annotation_note = "annotation_note"


class ReviewTargetType(str, Enum):
    """Supported typed review targets."""

    wiki_page_revision = "wiki_page_revision"
    annotation_note = "annotation_note"


@dataclass(frozen=True)
class WikiPageRevisionReviewTarget:
    """Immutable Wiki page revision that a reviewer is being asked to accept."""

    page_id: str
    page_path: str
    expected_content_hash: str
    expected_status: str = "draft"
    target_type: ReviewTargetType = ReviewTargetType.wiki_page_revision
    schema_version: str = "scholar-ai-wiki-page-revision-target/v2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.target_type.value,
            "page_id": self.page_id,
            "page_path": self.page_path,
            "expected_content_hash": self.expected_content_hash,
            "expected_status": self.expected_status,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WikiPageRevisionReviewTarget":
        if not isinstance(payload, Mapping):
            raise TypeError("review target payload must be a mapping")
        target_type = ReviewTargetType(_require_text(payload.get("type"), "target.type"))
        if target_type != ReviewTargetType.wiki_page_revision:
            raise ValueError(f"unsupported review target type: {target_type.value}")
        schema_version = _require_supported_schema_version(
            payload.get("schema_version"),
            {
                "scholar-ai-wiki-page-revision-target/v1",
                "scholar-ai-wiki-page-revision-target/v2",
            },
        )
        raw_page_id = payload.get("page_id")
        page_id = (
            _require_page_id(raw_page_id, "target.page_id")
            if raw_page_id is not None
            else ""
        )
        if schema_version.endswith("/v2") and not page_id:
            raise ValueError("target.page_id is required for v2 review targets")
        return cls(
            page_id=page_id,
            page_path=_require_page_path(payload.get("page_path"), "target.page_path"),
            expected_content_hash=_require_sha256(
                payload.get("expected_content_hash"),
                "target.expected_content_hash",
            ),
            expected_status=_require_review_page_status(payload.get("expected_status")),
            target_type=target_type,
            schema_version=schema_version,
        )


@dataclass(frozen=True)
class AnnotationNoteReviewTarget:
    """Immutable annotation note snapshot submitted for Wiki review."""

    project_id: str
    material_id: str
    note_id: str
    expected_updated_at: str
    expected_content_hash: str
    required_scope: str = "wiki_review"
    target_type: ReviewTargetType = ReviewTargetType.annotation_note
    schema_version: str = "scholar-ai-annotation-note-review-target/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.target_type.value,
            "project_id": self.project_id,
            "material_id": self.material_id,
            "note_id": self.note_id,
            "expected_updated_at": self.expected_updated_at,
            "expected_content_hash": self.expected_content_hash,
            "required_scope": self.required_scope,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AnnotationNoteReviewTarget":
        if not isinstance(payload, Mapping):
            raise TypeError("review target payload must be a mapping")
        _require_exact_keys(
            payload,
            {
                "schema_version",
                "type",
                "project_id",
                "material_id",
                "note_id",
                "expected_updated_at",
                "expected_content_hash",
                "required_scope",
            },
            "annotation note review target",
        )
        target_type = ReviewTargetType(_require_text(payload.get("type"), "target.type"))
        if target_type != ReviewTargetType.annotation_note:
            raise ValueError(f"unsupported review target type: {target_type.value}")
        required_scope = _require_text(
            payload.get("required_scope"),
            "target.required_scope",
        )
        if required_scope != "wiki_review":
            raise ValueError("target.required_scope must be wiki_review")
        return cls(
            project_id=_require_safe_identifier(payload.get("project_id"), "target.project_id"),
            material_id=_require_safe_identifier(payload.get("material_id"), "target.material_id"),
            note_id=_require_safe_identifier(payload.get("note_id"), "target.note_id"),
            expected_updated_at=_require_aware_timestamp(
                payload.get("expected_updated_at"),
                "target.expected_updated_at",
            ),
            expected_content_hash=_require_sha256(
                payload.get("expected_content_hash"),
                "target.expected_content_hash",
            ),
            required_scope=required_scope,
            target_type=target_type,
            schema_version=_require_schema_version(
                payload.get("schema_version"),
                "scholar-ai-annotation-note-review-target/v1",
            ),
        )


ReviewTarget: TypeAlias = WikiPageRevisionReviewTarget | AnnotationNoteReviewTarget


def review_target_from_dict(payload: Mapping[str, Any]) -> ReviewTarget:
    """Parse one strict typed review target from durable queue data."""

    if not isinstance(payload, Mapping):
        raise TypeError("review target payload must be a mapping")
    target_type = ReviewTargetType(_require_text(payload.get("type"), "target.type"))
    if target_type == ReviewTargetType.wiki_page_revision:
        return WikiPageRevisionReviewTarget.from_dict(payload)
    if target_type == ReviewTargetType.annotation_note:
        return AnnotationNoteReviewTarget.from_dict(payload)
    raise ValueError(f"unsupported review target type: {target_type.value}")


@dataclass(frozen=True)
class ReviewPromotionReceipt:
    """Durable receipt proving which Wiki revision was explicitly promoted."""

    receipt_id: str
    review_item_id: str
    request_id: str
    expected_item_revision: str
    request_fingerprint: str
    target: WikiPageRevisionReviewTarget
    before_content_hash: str
    after_content_hash: str
    previous_status: str
    promoted_status: str
    promoted_at: str
    promoted_by: str
    outcome: str = "promoted"
    schema_version: str = "scholar-ai-wiki-promotion-receipt/v2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "review_item_id": self.review_item_id,
            "request_id": self.request_id,
            "expected_item_revision": self.expected_item_revision,
            "request_fingerprint": self.request_fingerprint,
            "outcome": self.outcome,
            "target": self.target.to_dict(),
            "before_content_hash": self.before_content_hash,
            "after_content_hash": self.after_content_hash,
            "previous_status": self.previous_status,
            "promoted_status": self.promoted_status,
            "promoted_at": self.promoted_at,
            "promoted_by": self.promoted_by,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewPromotionReceipt":
        if not isinstance(payload, Mapping):
            raise TypeError("promotion receipt payload must be a mapping")
        target_payload = payload.get("target")
        if not isinstance(target_payload, Mapping):
            raise TypeError("promotion receipt target must be a mapping")
        outcome = _require_text(payload.get("outcome"), "promotion_receipt.outcome")
        if outcome != "promoted":
            raise ValueError("promotion receipt outcome must be promoted")
        schema_version = _require_supported_schema_version(
            payload.get("schema_version"),
            {
                "scholar-ai-wiki-promotion-receipt/v1",
                "scholar-ai-wiki-promotion-receipt/v2",
            },
        )
        expected_item_revision = str(payload.get("expected_item_revision") or "").strip()
        request_fingerprint = str(payload.get("request_fingerprint") or "").strip().lower()
        if schema_version.endswith("/v2"):
            expected_item_revision = _require_text(
                expected_item_revision,
                "promotion_receipt.expected_item_revision",
            )
            request_fingerprint = _require_sha256(
                request_fingerprint,
                "promotion_receipt.request_fingerprint",
            )
        return cls(
            receipt_id=_require_text(payload.get("receipt_id"), "promotion_receipt.receipt_id"),
            review_item_id=_require_text(
                payload.get("review_item_id"),
                "promotion_receipt.review_item_id",
            ),
            request_id=_require_text(payload.get("request_id"), "promotion_receipt.request_id"),
            expected_item_revision=expected_item_revision,
            request_fingerprint=request_fingerprint,
            target=WikiPageRevisionReviewTarget.from_dict(target_payload),
            before_content_hash=_require_sha256(
                payload.get("before_content_hash"),
                "promotion_receipt.before_content_hash",
            ),
            after_content_hash=_require_sha256(
                payload.get("after_content_hash"),
                "promotion_receipt.after_content_hash",
            ),
            previous_status=_require_review_page_status(payload.get("previous_status")),
            promoted_status=_require_promoted_page_status(payload.get("promoted_status")),
            promoted_at=_require_text(payload.get("promoted_at"), "promotion_receipt.promoted_at"),
            promoted_by=_require_text(payload.get("promoted_by"), "promotion_receipt.promoted_by"),
            outcome=outcome,
            schema_version=schema_version,
        )


@dataclass(frozen=True)
class ReviewPromotionWithdrawalReceipt:
    """Durable receipt proving an in-flight promotion was withdrawn."""

    receipt_id: str
    review_item_id: str
    promotion_operation_id: str
    promotion_request_id: str
    promotion_request_fingerprint: str
    expected_item_revision: str
    resulting_item_revision: str
    withdrawal_request_fingerprint: str
    target: WikiPageRevisionReviewTarget
    before_content_hash: str
    planned_after_content_hash: str
    reason: str
    withdrawn_at: str
    withdrawn_by: str
    outcome: str = "withdrawn"
    schema_version: str = "scholar-ai-wiki-promotion-withdrawal-receipt/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "review_item_id": self.review_item_id,
            "promotion_operation_id": self.promotion_operation_id,
            "promotion_request_id": self.promotion_request_id,
            "promotion_request_fingerprint": self.promotion_request_fingerprint,
            "expected_item_revision": self.expected_item_revision,
            "resulting_item_revision": self.resulting_item_revision,
            "withdrawal_request_fingerprint": self.withdrawal_request_fingerprint,
            "outcome": self.outcome,
            "target": self.target.to_dict(),
            "before_content_hash": self.before_content_hash,
            "planned_after_content_hash": self.planned_after_content_hash,
            "reason": self.reason,
            "withdrawn_at": self.withdrawn_at,
            "withdrawn_by": self.withdrawn_by,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewPromotionWithdrawalReceipt":
        if not isinstance(payload, Mapping):
            raise TypeError("promotion withdrawal receipt payload must be a mapping")
        target_payload = payload.get("target")
        if not isinstance(target_payload, Mapping):
            raise TypeError("promotion withdrawal receipt target must be a mapping")
        outcome = _require_text(
            payload.get("outcome"),
            "promotion_withdrawal_receipt.outcome",
        )
        if outcome != "withdrawn":
            raise ValueError("promotion withdrawal receipt outcome must be withdrawn")
        return cls(
            receipt_id=_require_text(
                payload.get("receipt_id"),
                "promotion_withdrawal_receipt.receipt_id",
            ),
            review_item_id=_require_text(
                payload.get("review_item_id"),
                "promotion_withdrawal_receipt.review_item_id",
            ),
            promotion_operation_id=_require_text(
                payload.get("promotion_operation_id"),
                "promotion_withdrawal_receipt.promotion_operation_id",
            ),
            promotion_request_id=_require_text(
                payload.get("promotion_request_id"),
                "promotion_withdrawal_receipt.promotion_request_id",
            ),
            promotion_request_fingerprint=_require_sha256(
                payload.get("promotion_request_fingerprint"),
                "promotion_withdrawal_receipt.promotion_request_fingerprint",
            ),
            expected_item_revision=_require_text(
                payload.get("expected_item_revision"),
                "promotion_withdrawal_receipt.expected_item_revision",
            ),
            resulting_item_revision=_require_text(
                payload.get("resulting_item_revision"),
                "promotion_withdrawal_receipt.resulting_item_revision",
            ),
            withdrawal_request_fingerprint=_require_sha256(
                payload.get("withdrawal_request_fingerprint"),
                "promotion_withdrawal_receipt.withdrawal_request_fingerprint",
            ),
            target=WikiPageRevisionReviewTarget.from_dict(target_payload),
            before_content_hash=_require_sha256(
                payload.get("before_content_hash"),
                "promotion_withdrawal_receipt.before_content_hash",
            ),
            planned_after_content_hash=_require_sha256(
                payload.get("planned_after_content_hash"),
                "promotion_withdrawal_receipt.planned_after_content_hash",
            ),
            reason=_require_text(
                payload.get("reason"),
                "promotion_withdrawal_receipt.reason",
            ),
            withdrawn_at=_require_text(
                payload.get("withdrawn_at"),
                "promotion_withdrawal_receipt.withdrawn_at",
            ),
            withdrawn_by=_require_text(
                payload.get("withdrawn_by"),
                "promotion_withdrawal_receipt.withdrawn_by",
            ),
            outcome=outcome,
            schema_version=_require_schema_version(
                payload.get("schema_version"),
                "scholar-ai-wiki-promotion-withdrawal-receipt/v1",
            ),
        )


@dataclass(frozen=True)
class ReviewPromotionIntent:
    """Durable intent for a page promotion that may span process restarts."""

    operation_id: str
    review_item_id: str
    request_id: str
    expected_item_revision: str
    request_fingerprint: str
    reason: str
    target: WikiPageRevisionReviewTarget
    before_content_hash: str
    after_content_hash: str
    previous_status: str
    promoted_status: str
    promoted_at: str
    promoted_by: str
    schema_version: str = "scholar-ai-wiki-promotion-intent/v2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "review_item_id": self.review_item_id,
            "request_id": self.request_id,
            "expected_item_revision": self.expected_item_revision,
            "request_fingerprint": self.request_fingerprint,
            "reason": self.reason,
            "target": self.target.to_dict(),
            "before_content_hash": self.before_content_hash,
            "after_content_hash": self.after_content_hash,
            "previous_status": self.previous_status,
            "promoted_status": self.promoted_status,
            "promoted_at": self.promoted_at,
            "promoted_by": self.promoted_by,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewPromotionIntent":
        if not isinstance(payload, Mapping):
            raise TypeError("promotion intent payload must be a mapping")
        target_payload = payload.get("target")
        if not isinstance(target_payload, Mapping):
            raise TypeError("promotion intent target must be a mapping")
        schema_version = _require_supported_schema_version(
            payload.get("schema_version"),
            {
                "scholar-ai-wiki-promotion-intent/v1",
                "scholar-ai-wiki-promotion-intent/v2",
            },
        )
        raw_reason = payload.get("reason", "")
        if not isinstance(raw_reason, str):
            raise TypeError("promotion_intent.reason must be a string")
        normalized_reason = raw_reason.strip()
        if schema_version.endswith("/v2") and not normalized_reason:
            raise ValueError("promotion_intent.reason is required for v2 intents")
        intent = cls(
            operation_id=_require_text(payload.get("operation_id"), "promotion_intent.operation_id"),
            review_item_id=_require_text(
                payload.get("review_item_id"),
                "promotion_intent.review_item_id",
            ),
            request_id=_require_text(payload.get("request_id"), "promotion_intent.request_id"),
            expected_item_revision=_require_text(
                payload.get("expected_item_revision"),
                "promotion_intent.expected_item_revision",
            ),
            request_fingerprint=_require_sha256(
                payload.get("request_fingerprint"),
                "promotion_intent.request_fingerprint",
            ),
            reason=normalized_reason,
            target=WikiPageRevisionReviewTarget.from_dict(target_payload),
            before_content_hash=_require_sha256(
                payload.get("before_content_hash"),
                "promotion_intent.before_content_hash",
            ),
            after_content_hash=_require_sha256(
                payload.get("after_content_hash"),
                "promotion_intent.after_content_hash",
            ),
            previous_status=_require_review_page_status(payload.get("previous_status")),
            promoted_status=_require_promoted_page_status(payload.get("promoted_status")),
            promoted_at=_require_text(payload.get("promoted_at"), "promotion_intent.promoted_at"),
            promoted_by=_require_text(payload.get("promoted_by"), "promotion_intent.promoted_by"),
            schema_version=schema_version,
        )
        if intent.before_content_hash == intent.after_content_hash:
            raise ValueError("promotion intent must change the page content hash")
        return intent

    def to_receipt(self) -> ReviewPromotionReceipt:
        """Return the final receipt after the planned page hash is verified."""

        return ReviewPromotionReceipt(
            receipt_id=self.operation_id,
            review_item_id=self.review_item_id,
            request_id=self.request_id,
            expected_item_revision=self.expected_item_revision,
            request_fingerprint=self.request_fingerprint,
            target=self.target,
            before_content_hash=self.before_content_hash,
            after_content_hash=self.after_content_hash,
            previous_status=self.previous_status,
            promoted_status=self.promoted_status,
            promoted_at=self.promoted_at,
            promoted_by=self.promoted_by,
        )


@dataclass(frozen=True)
class ReviewDecision:
    """Explicit human decision attached to a review item."""

    status: ReviewItemStatus
    reason: str
    decided_at: str
    decided_by: str
    request_id: str = ""
    expected_item_revision: str = ""
    request_fingerprint: str = ""
    promotion_receipt: ReviewPromotionReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "request_id": self.request_id,
            "expected_item_revision": self.expected_item_revision,
            "request_fingerprint": self.request_fingerprint,
            "promotion_receipt": self.promotion_receipt.to_dict() if self.promotion_receipt else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewDecision":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        raw_receipt = payload.get("promotion_receipt")
        return cls(
            status=ReviewItemStatus(_require_text(payload.get("status"), "status")),
            reason=str(payload.get("reason") or ""),
            decided_at=_require_text(payload.get("decided_at"), "decided_at"),
            decided_by=str(payload.get("decided_by") or "unknown"),
            request_id=str(payload.get("request_id") or ""),
            expected_item_revision=str(payload.get("expected_item_revision") or ""),
            request_fingerprint=(
                _require_sha256(payload.get("request_fingerprint"), "request_fingerprint")
                if payload.get("request_fingerprint")
                else ""
            ),
            promotion_receipt=(
                ReviewPromotionReceipt.from_dict(raw_receipt)
                if isinstance(raw_receipt, Mapping)
                else None
            ),
        )


@dataclass(frozen=True)
class ReviewItem:
    """A durable review queue item for wiki governance."""

    item_id: str
    kind: ReviewItemKind
    title: str
    page_path: str
    summary: str
    status: ReviewItemStatus = ReviewItemStatus.pending
    created_at: str = ""
    source: str = "wiki"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 2
    item_revision: str = ""
    target: ReviewTarget | None = None
    promotion_intent: ReviewPromotionIntent | None = None
    promotion_withdrawal_receipts: tuple[ReviewPromotionWithdrawalReceipt, ...] = ()
    decision: ReviewDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind.value,
            "title": self.title,
            "page_path": self.page_path,
            "summary": self.summary,
            "status": self.status.value,
            "created_at": self.created_at,
            "source": self.source,
            "metadata": self.metadata,
            "schema_version": self.schema_version,
            "item_revision": self.item_revision,
            "target": self.target.to_dict() if self.target else None,
            "promotion_intent": self.promotion_intent.to_dict() if self.promotion_intent else None,
            "promotion_withdrawal_receipts": [
                receipt.to_dict() for receipt in self.promotion_withdrawal_receipts
            ],
            "decision": self.decision.to_dict() if self.decision else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewItem":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        raw_decision = payload.get("decision")
        raw_target = payload.get("target")
        raw_promotion_intent = payload.get("promotion_intent")
        raw_withdrawal_receipts = payload.get("promotion_withdrawal_receipts", [])
        if not isinstance(raw_withdrawal_receipts, list):
            raise TypeError("promotion_withdrawal_receipts must be a list")
        return cls(
            item_id=_require_text(payload.get("item_id"), "item_id"),
            kind=ReviewItemKind(_require_text(payload.get("kind"), "kind")),
            title=_require_text(payload.get("title"), "title"),
            page_path=_require_text(payload.get("page_path"), "page_path"),
            summary=str(payload.get("summary") or ""),
            status=ReviewItemStatus(str(payload.get("status") or ReviewItemStatus.pending.value)),
            created_at=str(payload.get("created_at") or ""),
            source=str(payload.get("source") or "wiki"),
            metadata=dict(payload.get("metadata") or {}),
            schema_version=int(payload.get("schema_version") or 1),
            item_revision=str(payload.get("item_revision") or ""),
            target=review_target_from_dict(raw_target) if isinstance(raw_target, Mapping) else None,
            promotion_intent=(
                ReviewPromotionIntent.from_dict(raw_promotion_intent)
                if isinstance(raw_promotion_intent, Mapping)
                else None
            ),
            promotion_withdrawal_receipts=tuple(
                ReviewPromotionWithdrawalReceipt.from_dict(receipt)
                for receipt in raw_withdrawal_receipts
            ),
            decision=ReviewDecision.from_dict(raw_decision) if isinstance(raw_decision, Mapping) else None,
        )

    def with_decision(
        self,
        status: ReviewItemStatus,
        *,
        reason: str,
        decided_by: str,
        decided_at: str | None = None,
        request_id: str = "",
        expected_item_revision: str = "",
        request_fingerprint: str = "",
        promotion_receipt: ReviewPromotionReceipt | None = None,
    ) -> "ReviewItem":
        if self.status != ReviewItemStatus.pending:
            raise ValueError(f"review item is already decided: {self.status.value}")
        if status == ReviewItemStatus.pending:
            raise ValueError("decision status cannot be pending")
        if promotion_receipt is not None and status != ReviewItemStatus.approved:
            raise ValueError("promotion receipt requires an approved decision")
        if promotion_receipt is not None and promotion_receipt.review_item_id != self.item_id:
            raise ValueError("promotion receipt review item does not match")
        decision = ReviewDecision(
            status=status,
            reason=reason,
            decided_by=decided_by,
            decided_at=decided_at or utc_now_iso(),
            request_id=request_id,
            expected_item_revision=expected_item_revision,
            request_fingerprint=request_fingerprint,
            promotion_receipt=promotion_receipt,
        )
        return ReviewItem(
            item_id=self.item_id,
            kind=self.kind,
            title=self.title,
            page_path=self.page_path,
            summary=self.summary,
            status=status,
            created_at=self.created_at,
            source=self.source,
            metadata=dict(self.metadata),
            schema_version=2,
            item_revision=new_review_item_revision(),
            target=self.target,
            promotion_intent=None,
            promotion_withdrawal_receipts=self.promotion_withdrawal_receipts,
            decision=decision,
        )


class ReviewQueue:
    """JSONL-backed review queue with explicit approve/reject decisions."""

    def __init__(self, queue_path: Path | None = None) -> None:
        self.queue_path = Path(queue_path) if queue_path is not None else wiki_review_queue_path()
        self._lock = _queue_lock(self.queue_path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize a multi-step page promotion and queue decision in-process."""

        with self._lock:
            yield

    def append(self, item: ReviewItem) -> ReviewItem:
        if not isinstance(item, ReviewItem):
            raise TypeError("item must be a ReviewItem")
        with self._lock:
            existing = {entry.item_id: entry for entry in self.list_items()}
            if item.item_id in existing:
                raise ValueError(f"review item already exists: {item.item_id}")
            normalized = item
            if not normalized.created_at or not normalized.item_revision or normalized.schema_version != 2:
                normalized = ReviewItem(
                    item_id=item.item_id,
                    kind=item.kind,
                    title=item.title,
                    page_path=item.page_path,
                    summary=item.summary,
                    status=item.status,
                    created_at=utc_now_iso(),
                    source=item.source,
                    metadata=dict(item.metadata),
                    schema_version=2,
                    item_revision=item.item_revision or new_review_item_revision(),
                    target=item.target,
                    promotion_intent=item.promotion_intent,
                    promotion_withdrawal_receipts=item.promotion_withdrawal_receipts,
                    decision=item.decision,
                )
            self._write_items([*existing.values(), normalized])
            return normalized

    def list_items(
        self,
        *,
        status: ReviewItemStatus | None = None,
        kind: ReviewItemKind | None = None,
    ) -> list[ReviewItem]:
        with self._lock:
            items = _read_items(self.queue_path)
            if status is not None:
                items = [item for item in items if item.status == status]
            if kind is not None:
                items = [item for item in items if item.kind == kind]
            return sorted(items, key=lambda item: (item.created_at, item.item_id))

    def get(self, item_id: str) -> ReviewItem | None:
        normalized = _require_text(item_id, "item_id")
        for item in self.list_items():
            if item.item_id == normalized:
                return item
        return None

    def update_metadata(self, item_id: str, metadata_updates: Mapping[str, Any]) -> ReviewItem:
        """Merge JSON-safe metadata onto an existing review item.

        Args:
            item_id: Existing review item id.
            metadata_updates: Object-shaped metadata patch used for local audit
                refs. Values are copied as-is and must be JSON serializable.

        Returns:
            Updated review item.

        Raises:
            KeyError: If the review item does not exist.
            TypeError: If metadata_updates is not a mapping.
        """

        normalized = _require_text(item_id, "item_id")
        if not isinstance(metadata_updates, Mapping):
            raise TypeError("metadata_updates must be a mapping")
        with self._lock:
            items = self.list_items()
            updated_items: list[ReviewItem] = []
            updated_item: ReviewItem | None = None
            for item in items:
                if item.item_id != normalized:
                    updated_items.append(item)
                    continue
                updated_item = ReviewItem(
                    item_id=item.item_id,
                    kind=item.kind,
                    title=item.title,
                    page_path=item.page_path,
                    summary=item.summary,
                    status=item.status,
                    created_at=item.created_at,
                    source=item.source,
                    metadata={**dict(item.metadata), **dict(metadata_updates)},
                    schema_version=2,
                    item_revision=new_review_item_revision(),
                    target=item.target,
                    promotion_intent=item.promotion_intent,
                    promotion_withdrawal_receipts=item.promotion_withdrawal_receipts,
                    decision=item.decision,
                )
                updated_items.append(updated_item)
            if updated_item is None:
                raise KeyError(normalized)
            self._write_items(updated_items)
            return updated_item

    def begin_or_resume_promotion(
        self,
        item_id: str,
        intent: ReviewPromotionIntent,
    ) -> ReviewItem:
        """Persist a page-promotion intent before any page write.

        Repeating the same logical request returns the stored intent. A
        different request cannot replace an in-flight promotion.
        """

        normalized = _require_text(item_id, "item_id")
        if not isinstance(intent, ReviewPromotionIntent):
            raise TypeError("intent must be a ReviewPromotionIntent")
        if intent.review_item_id != normalized:
            raise ValueError("promotion intent review item does not match")
        with self._lock:
            items = self.list_items()
            updated_items: list[ReviewItem] = []
            prepared: ReviewItem | None = None
            for item in items:
                if item.item_id != normalized:
                    updated_items.append(item)
                    continue
                if item.status != ReviewItemStatus.pending:
                    raise ValueError(f"review item is already decided: {item.status.value}")
                existing_intent = item.promotion_intent
                if existing_intent is not None:
                    if (
                        existing_intent.request_id != intent.request_id
                        or existing_intent.request_fingerprint != intent.request_fingerprint
                        or existing_intent.expected_item_revision != intent.expected_item_revision
                    ):
                        raise ValueError("review item already has a different promotion request in progress")
                    prepared = item
                    updated_items.append(item)
                    continue
                if intent.expected_item_revision != item.item_revision:
                    raise ValueError("review item revision changed; refresh before deciding")
                if item.target != intent.target:
                    raise ValueError("promotion intent target does not match the review item")
                prepared = ReviewItem(
                    item_id=item.item_id,
                    kind=item.kind,
                    title=item.title,
                    page_path=item.page_path,
                    summary=item.summary,
                    status=item.status,
                    created_at=item.created_at,
                    source=item.source,
                    metadata=dict(item.metadata),
                    schema_version=item.schema_version,
                    item_revision=item.item_revision,
                    target=item.target,
                    promotion_intent=intent,
                    promotion_withdrawal_receipts=item.promotion_withdrawal_receipts,
                    decision=item.decision,
                )
                updated_items.append(prepared)
            if prepared is None:
                raise KeyError(normalized)
            if prepared.promotion_intent is intent:
                self._write_items(updated_items)
            return prepared

    def finalize_promotion(
        self,
        item_id: str,
        *,
        reason: str,
        decided_by: str,
        receipt: ReviewPromotionReceipt,
    ) -> ReviewItem:
        """Commit an approved decision after the planned page hash exists."""

        normalized = _require_text(item_id, "item_id")
        if not isinstance(receipt, ReviewPromotionReceipt):
            raise TypeError("receipt must be a ReviewPromotionReceipt")
        with self._lock:
            items = self.list_items()
            updated: list[ReviewItem] = []
            decided: ReviewItem | None = None
            for item in items:
                if item.item_id != normalized:
                    updated.append(item)
                    continue
                intent = item.promotion_intent
                if intent is None:
                    raise ValueError("review item has no durable promotion intent")
                if intent.to_receipt() != receipt:
                    raise ValueError("promotion receipt does not match the durable intent")
                normalized_reason = str(reason or "").strip()
                # Early v1 intents omitted reason; their request fingerprint
                # still binds the original retry parameters at the router.
                if intent.reason and normalized_reason != intent.reason:
                    raise ValueError("promotion decision reason does not match the durable intent")
                if str(decided_by or "").strip() != intent.promoted_by:
                    raise ValueError("promotion reviewer does not match the durable intent")
                decided = item.with_decision(
                    ReviewItemStatus.approved,
                    reason=reason,
                    decided_by=decided_by,
                    promotion_receipt=receipt,
                )
                updated.append(decided)
            if decided is None:
                raise KeyError(normalized)
            self._write_items(updated)
            return decided

    def withdraw_promotion(
        self,
        item_id: str,
        *,
        expected_item_revision: str,
        expected_promotion_operation_id: str,
        observed_page_content_hash: str,
        withdrawal_request_fingerprint: str,
        reason: str,
        withdrawn_by: str,
    ) -> tuple[ReviewItem, ReviewPromotionWithdrawalReceipt]:
        """Withdraw an unapplied promotion while keeping its candidate pending.

        Args:
            item_id: Pending review item identity.
            expected_item_revision: Queue revision shown to the requester.
            expected_promotion_operation_id: Durable promotion intent identity.
            observed_page_content_hash: Page hash preflighted by the router.
            withdrawal_request_fingerprint: Canonical replay fingerprint.
            reason: Human reason retained in the audit receipt.
            withdrawn_by: Normalized Wiki user identity.

        Returns:
            Updated pending item and its durable withdrawal receipt.

        Raises:
            KeyError: If the item does not exist.
            ValueError: If any compare-and-set precondition no longer matches.
        """

        normalized = _require_text(item_id, "item_id")
        normalized_revision = _require_text(expected_item_revision, "expected_item_revision")
        normalized_operation_id = _require_text(
            expected_promotion_operation_id,
            "expected_promotion_operation_id",
        )
        normalized_page_hash = _require_sha256(
            observed_page_content_hash,
            "observed_page_content_hash",
        )
        normalized_fingerprint = _require_sha256(
            withdrawal_request_fingerprint,
            "withdrawal_request_fingerprint",
        )
        normalized_reason = _require_text(reason, "withdrawal reason")
        normalized_user = _require_text(withdrawn_by, "withdrawn_by")
        with self._lock:
            items = self.list_items()
            updated_items: list[ReviewItem] = []
            withdrawn_item: ReviewItem | None = None
            receipt: ReviewPromotionWithdrawalReceipt | None = None
            for item in items:
                if item.item_id != normalized:
                    updated_items.append(item)
                    continue
                if item.status != ReviewItemStatus.pending:
                    raise ValueError(f"review item is already decided: {item.status.value}")
                intent = item.promotion_intent
                if intent is None:
                    raise ValueError("review item has no promotion request to withdraw")
                if item.item_revision != normalized_revision:
                    raise ValueError("review item revision changed; refresh before withdrawing")
                if intent.operation_id != normalized_operation_id:
                    raise ValueError("promotion operation changed; refresh before withdrawing")
                if intent.expected_item_revision != normalized_revision:
                    raise ValueError("promotion intent is bound to a different review item revision")
                if normalized_page_hash != intent.before_content_hash:
                    raise ValueError("review target page changed outside the pending withdrawal")
                resulting_revision = new_review_item_revision()
                receipt = ReviewPromotionWithdrawalReceipt(
                    receipt_id=uuid4().hex,
                    review_item_id=item.item_id,
                    promotion_operation_id=intent.operation_id,
                    promotion_request_id=intent.request_id,
                    promotion_request_fingerprint=intent.request_fingerprint,
                    expected_item_revision=normalized_revision,
                    resulting_item_revision=resulting_revision,
                    withdrawal_request_fingerprint=normalized_fingerprint,
                    target=intent.target,
                    before_content_hash=intent.before_content_hash,
                    planned_after_content_hash=intent.after_content_hash,
                    reason=normalized_reason,
                    withdrawn_at=utc_now_iso(),
                    withdrawn_by=normalized_user,
                )
                withdrawn_item = ReviewItem(
                    item_id=item.item_id,
                    kind=item.kind,
                    title=item.title,
                    page_path=item.page_path,
                    summary=item.summary,
                    status=item.status,
                    created_at=item.created_at,
                    source=item.source,
                    metadata=dict(item.metadata),
                    schema_version=item.schema_version,
                    item_revision=resulting_revision,
                    target=item.target,
                    promotion_intent=None,
                    promotion_withdrawal_receipts=(
                        *item.promotion_withdrawal_receipts,
                        receipt,
                    ),
                    decision=item.decision,
                )
                updated_items.append(withdrawn_item)
            if withdrawn_item is None or receipt is None:
                raise KeyError(normalized)
            self._write_items(updated_items)
            return withdrawn_item, receipt

    def remove(self, item_id: str) -> bool:
        """Remove a pending local review item during same-transaction rollback.

        Args:
            item_id: Existing review item id.

        Returns:
            True when an item was removed, False when the id was absent.
        """

        normalized = _require_text(item_id, "item_id")
        with self._lock:
            items = self.list_items()
            target = next((item for item in items if item.item_id == normalized), None)
            if target is None:
                return False
            if target.status != ReviewItemStatus.pending:
                raise ValueError("only pending review items can be removed during rollback")
            self._write_items([item for item in items if item.item_id != normalized])
            return True

    def decide_once(
        self,
        item_id: str,
        *,
        status: ReviewItemStatus,
        reason: str,
        decided_by: str,
        request_id: str,
        expected_item_revision: str,
        request_fingerprint: str,
    ) -> ReviewItem:
        """Record one CAS-bound, idempotent, decision-only review outcome.

        This path never creates a promotion intent or receipt. An exact retry
        returns the already persisted item, while reusing ``request_id`` with
        any different parameters fails without rewriting the queue.

        Args:
            item_id: Pending queue item identity.
            status: Final approved or rejected outcome.
            reason: Human decision rationale.
            decided_by: Normalized reviewer identity.
            request_id: Caller-generated idempotency token.
            expected_item_revision: Queue revision observed by the caller.
            request_fingerprint: Canonical SHA-256 of all decision inputs.

        Returns:
            The newly decided item or the exact prior replay result.

        Raises:
            KeyError: If ``item_id`` does not exist.
            ValueError: If CAS, status, or idempotency checks fail.
        """

        normalized_item_id = _require_text(item_id, "item_id")
        normalized_request_id = _require_text(request_id, "request_id")
        normalized_revision = _require_text(expected_item_revision, "expected_item_revision")
        normalized_fingerprint = _require_sha256(
            request_fingerprint,
            "request_fingerprint",
        )
        normalized_reason = str(reason or "").strip()
        normalized_user = _require_text(decided_by, "decided_by")
        if not isinstance(status, ReviewItemStatus):
            raise TypeError("status must be a ReviewItemStatus")
        if status not in {ReviewItemStatus.approved, ReviewItemStatus.rejected}:
            raise ValueError("decision status must be approved or rejected")
        if not normalized_reason:
            raise ValueError("decision reason cannot be empty")

        with self._lock:
            items = self.list_items()
            for queued_item in items:
                decision = queued_item.decision
                promotion_intent = queued_item.promotion_intent
                if (
                    promotion_intent is not None
                    and promotion_intent.request_id == normalized_request_id
                ):
                    raise ValueError(
                        "review request_id was already used with different parameters"
                    )
                if decision is None:
                    continue
                prior_request_id = decision.request_id
                prior_fingerprint = decision.request_fingerprint
                if decision.promotion_receipt is not None:
                    prior_request_id = prior_request_id or decision.promotion_receipt.request_id
                    prior_fingerprint = (
                        prior_fingerprint or decision.promotion_receipt.request_fingerprint
                    )
                if prior_request_id != normalized_request_id:
                    continue
                if (
                    queued_item.item_id == normalized_item_id
                    and queued_item.status == status
                    and decision.expected_item_revision == normalized_revision
                    and prior_fingerprint == normalized_fingerprint
                ):
                    return queued_item
                raise ValueError("review request_id was already used with different parameters")

            updated: list[ReviewItem] = []
            decided: ReviewItem | None = None
            for item in items:
                if item.item_id != normalized_item_id:
                    updated.append(item)
                    continue
                if item.item_revision != normalized_revision:
                    raise ValueError("review item revision changed; refresh before deciding")
                if item.status != ReviewItemStatus.pending:
                    raise ValueError(f"review item is already decided: {item.status.value}")
                if item.promotion_intent is not None:
                    raise ValueError(
                        "review item promotion request is in progress; retry the original approval"
                    )
                decided = item.with_decision(
                    status,
                    reason=normalized_reason,
                    decided_by=normalized_user,
                    request_id=normalized_request_id,
                    expected_item_revision=normalized_revision,
                    request_fingerprint=normalized_fingerprint,
                    promotion_receipt=None,
                )
                updated.append(decided)
            if decided is None:
                raise KeyError(normalized_item_id)
            self._write_items(updated)
            return decided

    def approve(
        self,
        item_id: str,
        *,
        reason: str = "",
        decided_by: str = "user",
        promotion_receipt: ReviewPromotionReceipt | None = None,
    ) -> ReviewItem:
        return self._decide(
            item_id,
            status=ReviewItemStatus.approved,
            reason=reason,
            decided_by=decided_by,
            promotion_receipt=promotion_receipt,
        )

    def reject(self, item_id: str, *, reason: str, decided_by: str = "user") -> ReviewItem:
        if not reason.strip():
            raise ValueError("reject reason cannot be empty")
        return self._decide(
            item_id,
            status=ReviewItemStatus.rejected,
            reason=reason,
            decided_by=decided_by,
            promotion_receipt=None,
        )

    def _decide(
        self,
        item_id: str,
        *,
        status: ReviewItemStatus,
        reason: str,
        decided_by: str,
        promotion_receipt: ReviewPromotionReceipt | None,
    ) -> ReviewItem:
        normalized = _require_text(item_id, "item_id")
        with self._lock:
            items = self.list_items()
            updated: list[ReviewItem] = []
            decided: ReviewItem | None = None
            for item in items:
                if item.item_id != normalized:
                    updated.append(item)
                    continue
                if item.promotion_intent is not None:
                    raise ValueError(
                        "review item promotion request is in progress; retry the original approval"
                    )
                decided = item.with_decision(
                    status,
                    reason=reason,
                    decided_by=decided_by,
                    promotion_receipt=promotion_receipt,
                )
                updated.append(decided)
            if decided is None:
                raise KeyError(normalized)
            self._write_items(updated)
            return decided

    def _write_items(self, items: Iterable[ReviewItem]) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) for item in items]
        _atomic_write_text(self.queue_path, "\n".join(lines) + ("\n" if lines else ""))


def make_review_item(
    *,
    item_id: str,
    kind: ReviewItemKind,
    title: str,
    page_path: str,
    summary: str,
    source: str = "wiki",
    metadata: Mapping[str, Any] | None = None,
    target: ReviewTarget | None = None,
) -> ReviewItem:
    """Create a pending review item with defensive input validation."""

    return ReviewItem(
        item_id=_require_text(item_id, "item_id"),
        kind=kind,
        title=_require_text(title, "title"),
        page_path=_require_text(page_path, "page_path"),
        summary=str(summary or ""),
        status=ReviewItemStatus.pending,
        created_at=utc_now_iso(),
        source=str(source or "wiki"),
        metadata=dict(metadata or {}),
        schema_version=2,
        item_revision=new_review_item_revision(),
        target=target,
        promotion_intent=None,
    )


def make_wiki_page_revision_review_target(
    *,
    page_id: str,
    page_path: str,
    expected_content_hash: str,
    expected_status: str = "draft",
) -> WikiPageRevisionReviewTarget:
    """Build a validated, immutable Wiki page revision review target."""

    return WikiPageRevisionReviewTarget(
        page_id=_require_page_id(page_id, "target.page_id"),
        page_path=_require_page_path(page_path, "target.page_path"),
        expected_content_hash=_require_sha256(
            expected_content_hash,
            "target.expected_content_hash",
        ),
        expected_status=_require_review_page_status(expected_status),
    )


def make_annotation_note_review_target(
    *,
    project_id: str,
    material_id: str,
    note_id: str,
    expected_updated_at: str,
    expected_content_hash: str,
) -> AnnotationNoteReviewTarget:
    """Build a validated, immutable project-owned annotation target."""

    return AnnotationNoteReviewTarget(
        project_id=_require_safe_identifier(project_id, "target.project_id"),
        material_id=_require_safe_identifier(material_id, "target.material_id"),
        note_id=_require_safe_identifier(note_id, "target.note_id"),
        expected_updated_at=_require_aware_timestamp(
            expected_updated_at,
            "target.expected_updated_at",
        ),
        expected_content_hash=_require_sha256(
            expected_content_hash,
            "target.expected_content_hash",
        ),
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_review_item_revision() -> str:
    """Return an opaque revision token for compare-and-set review decisions."""

    return uuid4().hex


def _read_items(queue_path: Path) -> list[ReviewItem]:
    if not queue_path.exists():
        return []
    items: list[ReviewItem] = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        items.append(ReviewItem.from_dict(payload))
    return items


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _require_page_path(value: Any, field_name: str) -> str:
    normalized = _require_text(value, field_name).replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
        raise ValueError(f"{field_name} must be a relative Markdown page path")
    return path.as_posix()


def _require_page_id(value: Any, field_name: str) -> str:
    normalized = _require_text(value, field_name)
    if len(normalized) > 256:
        raise ValueError(f"{field_name} is too long")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _require_safe_identifier(value: Any, field_name: str) -> str:
    normalized = _require_text(value, field_name)
    if len(normalized) > 256:
        raise ValueError(f"{field_name} is too long")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", normalized) is None:
        raise ValueError(f"{field_name} contains unsupported characters")
    return normalized


def _require_aware_timestamp(value: Any, field_name: str) -> str:
    normalized = _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return normalized


def _require_exact_keys(
    payload: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(payload)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(extra)}")


def _require_sha256(value: Any, field_name: str) -> str:
    normalized = _require_text(value, field_name).lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    return normalized


def _require_review_page_status(value: Any) -> str:
    normalized = _require_text(value, "target.expected_status")
    if normalized not in {"draft", "review"}:
        raise ValueError("target.expected_status must be draft or review")
    return normalized


def _require_promoted_page_status(value: Any) -> str:
    normalized = _require_text(value, "promotion_receipt.promoted_status")
    if normalized != "final":
        raise ValueError("promotion receipt promoted_status must be final")
    return normalized


def _require_schema_version(value: Any, expected: str) -> str:
    normalized = _require_text(value, "schema_version")
    if normalized != expected:
        raise ValueError(f"unsupported schema_version: {normalized}")
    return normalized


def _require_supported_schema_version(value: Any, supported: set[str]) -> str:
    normalized = _require_text(value, "schema_version")
    if normalized not in supported:
        raise ValueError(f"unsupported schema_version: {normalized}")
    return normalized
