from __future__ import annotations

import json
from pathlib import Path

import pytest

from literature_assistant.core.wiki.review_queue import (
    ReviewItemKind,
    ReviewItemStatus,
    ReviewQueue,
    make_review_item,
)


def test_append_and_list_pending_items(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    item = make_review_item(
        item_id="draft-1",
        kind=ReviewItemKind.draft,
        title="Draft 1",
        page_path="concepts/draft-1.md",
        summary="Needs review.",
    )

    queue.append(item)
    items = queue.list_items(status=ReviewItemStatus.pending)

    assert len(items) == 1
    assert items[0].item_id == "draft-1"
    assert items[0].status == ReviewItemStatus.pending


def test_append_rejects_duplicate_item_id(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    item = make_review_item(
        item_id="draft-1",
        kind=ReviewItemKind.draft,
        title="Draft 1",
        page_path="concepts/draft-1.md",
        summary="Needs review.",
    )

    queue.append(item)

    with pytest.raises(ValueError, match="already exists"):
        queue.append(item)


def test_approve_records_decision_without_modifying_page(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    page_path = tmp_path / "concepts" / "draft-1.md"
    page_path.parent.mkdir(parents=True)
    page_path.write_text("draft body", encoding="utf-8")
    item = make_review_item(
        item_id="draft-1",
        kind=ReviewItemKind.draft,
        title="Draft 1",
        page_path=str(page_path),
        summary="Needs review.",
    )
    queue.append(item)

    decided = queue.approve("draft-1", reason="looks good", decided_by="tester")

    assert decided.status == ReviewItemStatus.approved
    assert decided.decision is not None
    assert decided.decision.reason == "looks good"
    assert page_path.read_text(encoding="utf-8") == "draft body"


def test_reject_requires_reason(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    queue.append(
        make_review_item(
            item_id="warn-1",
            kind=ReviewItemKind.warning,
            title="Warning",
            page_path="claims/warn.md",
            summary="Citation warning.",
        )
    )

    with pytest.raises(ValueError, match="reason cannot be empty"):
        queue.reject("warn-1", reason="")


def test_reject_records_feedback(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    queue.append(
        make_review_item(
            item_id="warn-1",
            kind=ReviewItemKind.warning,
            title="Warning",
            page_path="claims/warn.md",
            summary="Citation warning.",
        )
    )

    decided = queue.reject("warn-1", reason="citation quote missing", decided_by="tester")

    assert decided.status == ReviewItemStatus.rejected
    assert decided.decision is not None
    assert decided.decision.reason == "citation quote missing"


def test_decided_item_cannot_be_decided_twice(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    queue.append(
        make_review_item(
            item_id="draft-1",
            kind=ReviewItemKind.draft,
            title="Draft 1",
            page_path="concepts/draft-1.md",
            summary="Needs review.",
        )
    )
    queue.approve("draft-1")

    with pytest.raises(ValueError, match="already decided"):
        queue.reject("draft-1", reason="too late")


def test_queue_jsonl_is_machine_readable(tmp_path: Path) -> None:
    queue_path = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_path)
    queue.append(
        make_review_item(
            item_id="manual-1",
            kind=ReviewItemKind.manual_edit,
            title="Manual Edit",
            page_path="concepts/manual.md",
            summary="Manual page changed.",
            metadata={"hash": "abc"},
        )
    )

    rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["item_id"] == "manual-1"
    assert rows[0]["kind"] == "manual_edit"
    assert rows[0]["metadata"] == {"hash": "abc"}
