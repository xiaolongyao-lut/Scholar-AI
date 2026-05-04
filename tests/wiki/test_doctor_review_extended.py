"""LMWR-476: doctor and review queue extended lifecycle tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from literature_assistant.core.wiki.doctor import (
    DoctorAction,
    DoctorCheck,
    DoctorReport,
    DoctorStatus,
    RepairResult,
    WikiDoctor,
)
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.review_queue import (
    ReviewItem,
    ReviewItemKind,
    ReviewItemStatus,
    ReviewQueue,
    make_review_item,
)
from literature_assistant.core.wiki.source_registry import WikiRegistry


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    root.mkdir()
    return root


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "wiki.db"


@pytest.fixture
def page_store(tmp_path: Path) -> WikiPageStore:
    return WikiPageStore(tmp_path / "wiki")


@pytest.fixture
def queue(tmp_path: Path) -> ReviewQueue:
    return ReviewQueue(tmp_path / "review.jsonl")


# --- Doctor checks ---


def test_doctor_empty_workspace(wiki_root: Path, db_path: Path) -> None:
    doctor = WikiDoctor(wiki_root, db_path)
    report = doctor.run()
    assert not report.ok
    workspace_check = [c for c in report.checks if c.id == "workspace"]
    assert len(workspace_check) == 1
    assert workspace_check[0].status == DoctorStatus.error


def test_doctor_workspace_exists(wiki_root: Path, db_path: Path) -> None:
    doctor = WikiDoctor(wiki_root, db_path)
    report = doctor.run()
    workspace_check = [c for c in report.checks if c.id == "workspace"]
    assert workspace_check[0].status == DoctorStatus.ok


def test_doctor_registry_missing(wiki_root: Path, db_path: Path) -> None:
    doctor = WikiDoctor(wiki_root, db_path)
    report = doctor.run()
    registry_check = [c for c in report.checks if c.id == "registry"]
    assert len(registry_check) >= 1


def test_doctor_registry_exists(wiki_root: Path, db_path: Path) -> None:
    registry = WikiRegistry(db_path)
    registry.list_sources()
    doctor = WikiDoctor(wiki_root, db_path)
    report = doctor.run()
    registry_check = [c for c in report.checks if c.id == "registry"]
    assert any(c.status == DoctorStatus.ok for c in registry_check)


def test_doctor_report_serialization(wiki_root: Path, db_path: Path) -> None:
    doctor = WikiDoctor(wiki_root, db_path)
    report = doctor.run()
    data = report.to_dict()
    assert "ok" in data
    assert "checks" in data
    assert "counts" in data
    assert isinstance(data["checks"], list)


def test_doctor_check_serialization() -> None:
    check = DoctorCheck(
        id="test",
        label="Test",
        status=DoctorStatus.warning,
        summary="Test summary",
        detail="Detail",
        actions=(DoctorAction("cmd", "desc", safe_auto_repair=True),),
    )
    data = check.to_dict()
    assert data["id"] == "test"
    assert data["status"] == "warning"
    assert len(data["actions"]) == 1


def test_doctor_action_serialization() -> None:
    action = DoctorAction("wiki init", "Create workspace", safe_auto_repair=True)
    data = action.to_dict()
    assert data["command"] == "wiki init"
    assert data["safe_auto_repair"] is True


# --- Doctor repair ---


def test_repair_creates_missing_dirs(wiki_root: Path, db_path: Path) -> None:
    empty_root = wiki_root.parent / "empty"
    doctor = WikiDoctor(empty_root, db_path)
    result = doctor.repair_safe_subset()
    assert len(result.repaired) > 0


def test_repair_idempotent(wiki_root: Path, db_path: Path) -> None:
    doctor = WikiDoctor(wiki_root, db_path)
    r1 = doctor.repair_safe_subset()
    r2 = doctor.repair_safe_subset()
    assert set(r2.repaired).issubset(set(r1.repaired))


def test_repair_does_not_modify_pages(wiki_root: Path, db_path: Path, page_store: WikiPageStore) -> None:
    page_store.write_rendered(render_page(Path("concepts/test.md"), {"id": "test", "kind": "concept", "title": "T", "status": "draft"}, "Body."))
    doctor = WikiDoctor(wiki_root, db_path)
    doctor.repair_safe_subset()
    page = page_store.read_page(Path("concepts/test.md"))
    assert page is not None
    assert "Body." in page.body


def test_repair_result_serialization() -> None:
    result = RepairResult(repaired=("workspace",), skipped=("pages",))
    assert "workspace" in result.repaired
    assert "pages" in result.skipped


# --- Review queue lifecycle ---


def test_append_draft_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r1", kind=ReviewItemKind.draft, title="Draft", page_path="draft/a.md", summary="New draft")
    queue.append(item)
    items = queue.list_items()
    assert len(items) == 1
    assert items[0].kind == ReviewItemKind.draft
    assert items[0].status == ReviewItemStatus.pending


def test_append_fail_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r2", kind=ReviewItemKind.fail, title="Failed", page_path="fail/a.md", summary="Failed validation")
    queue.append(item)
    items = queue.list_items()
    assert any(i.kind == ReviewItemKind.fail for i in items)


def test_append_warning_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r3", kind=ReviewItemKind.warning, title="Warning", page_path="warn/a.md", summary="Warning")
    queue.append(item)
    items = queue.list_items()
    assert any(i.kind == ReviewItemKind.warning for i in items)


def test_append_manual_edit_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r4", kind=ReviewItemKind.manual_edit, title="Edited", page_path="edit/a.md", summary="Manual edit")
    queue.append(item)
    items = queue.list_items()
    assert any(i.kind == ReviewItemKind.manual_edit for i in items)


def test_list_filter_by_status(queue: ReviewQueue) -> None:
    item1 = make_review_item(item_id="r5", kind=ReviewItemKind.draft, title="A", page_path="a.md", summary="")
    item2 = make_review_item(item_id="r6", kind=ReviewItemKind.draft, title="B", page_path="b.md", summary="")
    queue.append(item1)
    queue.append(item2)
    queue.approve("r5", reason="OK")
    pending = queue.list_items(status=ReviewItemStatus.pending)
    assert len(pending) == 1
    assert pending[0].item_id == "r6"


def test_list_filter_by_kind(queue: ReviewQueue) -> None:
    item1 = make_review_item(item_id="r7", kind=ReviewItemKind.draft, title="A", page_path="a.md", summary="")
    item2 = make_review_item(item_id="r8", kind=ReviewItemKind.warning, title="B", page_path="b.md", summary="")
    queue.append(item1)
    queue.append(item2)
    drafts = queue.list_items(kind=ReviewItemKind.draft)
    assert len(drafts) == 1


def test_get_existing_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r9", kind=ReviewItemKind.draft, title="X", page_path="x.md", summary="")
    queue.append(item)
    found = queue.get("r9")
    assert found is not None
    assert found.title == "X"


def test_get_nonexistent_item(queue: ReviewQueue) -> None:
    assert queue.get("nonexistent") is None


def test_approve_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r10", kind=ReviewItemKind.draft, title="Y", page_path="y.md", summary="")
    queue.append(item)
    decided = queue.approve("r10", reason="Looks good", decided_by="tester")
    assert decided.status == ReviewItemStatus.approved
    assert decided.decision is not None
    assert decided.decision.reason == "Looks good"


def test_approve_already_decided_raises(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r11", kind=ReviewItemKind.draft, title="Z", page_path="z.md", summary="")
    queue.append(item)
    queue.approve("r11", reason="First")
    with pytest.raises(ValueError, match="already decided"):
        queue.approve("r11", reason="Second")


def test_reject_item(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r12", kind=ReviewItemKind.draft, title="W", page_path="w.md", summary="")
    queue.append(item)
    decided = queue.reject("r12", reason="Bad quality", decided_by="tester")
    assert decided.status == ReviewItemStatus.rejected
    assert decided.decision is not None


def test_reject_empty_reason_raises(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="r13", kind=ReviewItemKind.draft, title="V", page_path="v.md", summary="")
    queue.append(item)
    with pytest.raises(ValueError, match="empty"):
        queue.reject("r13", reason="")


def test_duplicate_item_id_raises(queue: ReviewQueue) -> None:
    item = make_review_item(item_id="dup1", kind=ReviewItemKind.draft, title="D1", page_path="d1.md", summary="")
    queue.append(item)
    with pytest.raises(ValueError, match="already exists"):
        queue.append(make_review_item(item_id="dup1", kind=ReviewItemKind.draft, title="D2", page_path="d2.md", summary=""))


# --- Review queue persistence ---


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    q1 = ReviewQueue(path)
    q1.append(make_review_item(item_id="p1", kind=ReviewItemKind.draft, title="P1", page_path="p1.md", summary=""))
    q1.append(make_review_item(item_id="p2", kind=ReviewItemKind.warning, title="P2", page_path="p2.md", summary=""))
    q1.approve("p1", reason="OK")
    q2 = ReviewQueue(path)
    items = q2.list_items()
    assert len(items) == 2
    approved = [i for i in items if i.status == ReviewItemStatus.approved]
    assert len(approved) == 1


def test_empty_queue_persistence(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    q = ReviewQueue(path)
    items = q.list_items()
    assert len(items) == 0


def test_large_queue_persistence(tmp_path: Path) -> None:
    path = tmp_path / "large.jsonl"
    q = ReviewQueue(path)
    for i in range(100):
        q.append(make_review_item(item_id=f"item-{i:04d}", kind=ReviewItemKind.draft, title=f"Item {i}", page_path=f"item/{i}.md", summary=""))
    items = q.list_items()
    assert len(items) == 100


def test_malformed_jsonl_line_skipped(tmp_path: Path) -> None:
    path = tmp_path / "malformed.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    q = ReviewQueue(path)
    with pytest.raises(Exception):
        q.list_items()


def test_review_item_to_dict_roundtrip() -> None:
    item = make_review_item(item_id="rt1", kind=ReviewItemKind.draft, title="RT", page_path="rt.md", summary="test", metadata={"key": "val"})
    data = item.to_dict()
    assert data["item_id"] == "rt1"
    assert data["metadata"]["key"] == "val"


def test_review_decision_to_dict_roundtrip() -> None:
    from literature_assistant.core.wiki.review_queue import ReviewDecision
    decision = ReviewDecision(status=ReviewItemStatus.approved, reason="OK", decided_at="2026-01-01T00:00:00+00:00", decided_by="tester")
    data = decision.to_dict()
    assert data["status"] == "approved"
