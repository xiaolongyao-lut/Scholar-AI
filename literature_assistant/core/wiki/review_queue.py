from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from literature_assistant.core.project_paths import wiki_review_queue_path


class ReviewItemStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ReviewItemKind(str, Enum):
    draft = "draft"
    fail = "fail"
    warning = "warning"
    manual_edit = "manual_edit"


@dataclass(frozen=True)
class ReviewDecision:
    """Explicit human decision attached to a review item."""

    status: ReviewItemStatus
    reason: str
    decided_at: str
    decided_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewDecision":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        return cls(
            status=ReviewItemStatus(_require_text(payload.get("status"), "status")),
            reason=str(payload.get("reason") or ""),
            decided_at=_require_text(payload.get("decided_at"), "decided_at"),
            decided_by=str(payload.get("decided_by") or "unknown"),
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
            "decision": self.decision.to_dict() if self.decision else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewItem":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        raw_decision = payload.get("decision")
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
            decision=ReviewDecision.from_dict(raw_decision) if isinstance(raw_decision, Mapping) else None,
        )

    def with_decision(
        self,
        status: ReviewItemStatus,
        *,
        reason: str,
        decided_by: str,
        decided_at: str | None = None,
    ) -> "ReviewItem":
        if self.status != ReviewItemStatus.pending:
            raise ValueError(f"review item is already decided: {self.status.value}")
        if status == ReviewItemStatus.pending:
            raise ValueError("decision status cannot be pending")
        decision = ReviewDecision(
            status=status,
            reason=reason,
            decided_by=decided_by,
            decided_at=decided_at or utc_now_iso(),
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
            decision=decision,
        )


class ReviewQueue:
    """JSONL-backed review queue with explicit approve/reject decisions."""

    def __init__(self, queue_path: Path | None = None) -> None:
        self.queue_path = Path(queue_path) if queue_path is not None else wiki_review_queue_path()

    def append(self, item: ReviewItem) -> ReviewItem:
        if not isinstance(item, ReviewItem):
            raise TypeError("item must be a ReviewItem")
        existing = {entry.item_id: entry for entry in self.list_items()}
        if item.item_id in existing:
            raise ValueError(f"review item already exists: {item.item_id}")
        normalized = item
        if not normalized.created_at:
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
                decision=item.decision,
            )
            updated_items.append(updated_item)
        if updated_item is None:
            raise KeyError(normalized)
        self._write_items(updated_items)
        return updated_item

    def remove(self, item_id: str) -> bool:
        """Remove a pending local review item during same-transaction rollback.

        Args:
            item_id: Existing review item id.

        Returns:
            True when an item was removed, False when the id was absent.
        """

        normalized = _require_text(item_id, "item_id")
        items = self.list_items()
        kept = [item for item in items if item.item_id != normalized]
        if len(kept) == len(items):
            return False
        self._write_items(kept)
        return True

    def approve(self, item_id: str, *, reason: str = "", decided_by: str = "user") -> ReviewItem:
        return self._decide(
            item_id,
            status=ReviewItemStatus.approved,
            reason=reason,
            decided_by=decided_by,
        )

    def reject(self, item_id: str, *, reason: str, decided_by: str = "user") -> ReviewItem:
        if not reason.strip():
            raise ValueError("reject reason cannot be empty")
        return self._decide(
            item_id,
            status=ReviewItemStatus.rejected,
            reason=reason,
            decided_by=decided_by,
        )

    def _decide(
        self,
        item_id: str,
        *,
        status: ReviewItemStatus,
        reason: str,
        decided_by: str,
    ) -> ReviewItem:
        normalized = _require_text(item_id, "item_id")
        items = self.list_items()
        updated: list[ReviewItem] = []
        decided: ReviewItem | None = None
        for item in items:
            if item.item_id != normalized:
                updated.append(item)
                continue
            decided = item.with_decision(status, reason=reason, decided_by=decided_by)
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
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
