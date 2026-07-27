# -*- coding: utf-8 -*-
"""Persistence regression tests for the writing resource store."""

from __future__ import annotations

from pathlib import Path

import pytest

from writing_resources import ProjectRevisionConflictError, WritingResourceStore


def test_store_persists_drafts_and_citation_anchors_across_instances(tmp_path: Path) -> None:
    """Autosaved snapshots should survive store recreation."""
    snapshot_path = tmp_path / "writing_resources_state.json"
    anchor_payload = [
        {
            "id": "cite:mat-1:anchor1",
            "materialId": "mat-1",
            "token": "[^cite:mat-1:anchor1]",
            "startOffset": 13,
            "endOffset": 34,
            "ordinal": 1,
        }
    ]

    first_store = WritingResourceStore(persistence_path=snapshot_path, autosave=True)
    project = first_store.create_project(title="Persistent Project")
    section = first_store.create_section(project.project_id, "Introduction", order=1)
    material = first_store.create_material(
        project.project_id,
        title="量子纠缠协议 2024",
        title_en="Quantum Entanglement Protocols 2024",
        summary="分析了当前量子同步的主要瓶颈。",
        summary_en="Analyzes major bottlenecks in quantum synchronization.",
        material_type="PAPER",
        focus_points=["同步效率", "误码率"],
        focus_points_en=["Sync Efficiency", "Bit Error Rate"],
    )
    draft = first_store.create_draft(
        project.project_id,
        section_id=section.section_id,
        title="Intro Draft",
        content="Sentence one [^cite:mat-1:anchor1].",
        citation_anchors=anchor_payload,
    )
    first_store.save_draft(
        draft.draft_id,
        "Sentence one [^cite:mat-1:anchor1].\nSentence two.",
        edited_by="qa-user",
        citation_anchors=anchor_payload,
    )

    second_store = WritingResourceStore(persistence_path=snapshot_path, autosave=True)
    reloaded_draft = second_store.get_draft(draft.draft_id)
    assert reloaded_draft is not None
    assert reloaded_draft.content.endswith("Sentence two.")
    assert reloaded_draft.to_dict()["citation_anchors"] == anchor_payload

    revisions = second_store.list_revisions(draft.draft_id)
    assert len(revisions) == 1
    assert revisions[0].to_dict()["citation_anchors"] == anchor_payload
    assert second_store.get_project(project.project_id) is not None
    assert second_store.get_section(section.section_id) is not None
    reloaded_material = second_store.get_material(material.material_id)
    assert reloaded_material is not None
    assert reloaded_material.focus_points_en == ["Sync Efficiency", "Bit Error Rate"]


def test_deleting_section_persists_draft_with_null_section_reference(tmp_path: Path) -> None:
    """Deleting a section should preserve drafts without orphaning section_id."""
    snapshot_path = tmp_path / "writing_resources_state.json"
    database_path = tmp_path / "writing_resources_state.sqlite3"
    first_store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    project = first_store.create_project(title="Section Delete Project")
    section = first_store.create_section(project.project_id, "Methods", order=1)
    draft = first_store.create_draft(
        project.project_id,
        section_id=section.section_id,
        title="Methods Draft",
        content="Draft attached to a section.",
    )

    assert first_store.delete_section(section.section_id) is True

    repaired_draft = first_store.get_draft(draft.draft_id)
    assert repaired_draft is not None
    assert repaired_draft.section_id is None

    second_store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    reloaded_draft = second_store.get_draft(draft.draft_id)
    assert reloaded_draft is not None
    assert reloaded_draft.section_id is None


def test_persistence_normalizes_orphan_revisions_and_links(tmp_path: Path) -> None:
    """Full-state replacement should drop revision/link rows that lost parents."""
    snapshot_path = tmp_path / "writing_resources_state.json"
    database_path = tmp_path / "writing_resources_state.sqlite3"
    first_store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    project = first_store.create_project(title="Draft Delete Project")
    draft = first_store.create_draft(project.project_id, title="Draft", content="v1")
    first_store.save_draft(draft.draft_id, "v2", create_revision=True)

    state = first_store.export_state()
    revision_ids = list(state["revisions"].keys())
    assert revision_ids

    state["drafts"].pop(draft.draft_id)
    state["draft_revisions"][draft.draft_id] = revision_ids
    first_store.import_state(state)

    persisted_path = first_store.persist_to_database()
    assert persisted_path == database_path

    second_store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    assert second_store.get_project(project.project_id) is not None
    assert second_store.get_draft(draft.draft_id) is None
    assert second_store.export_state()["revisions"] == {}
    assert draft.draft_id not in second_store.export_state()["draft_revisions"]


def test_primary_autosave_failure_restores_last_durable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed primary write should not leave a partially successful memory state."""
    snapshot_path = tmp_path / "writing_resources_state.json"
    database_path = tmp_path / "writing_resources_state.sqlite3"
    store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    durable_project = store.create_project(title="Durable Project")
    assert [project.title for project in store.list_projects()] == ["Durable Project"]
    assert store._repository is not None

    def fail_replace_state(_state: object) -> None:
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(store._repository, "replace_state", fail_replace_state)

    with pytest.raises(RuntimeError, match="in-memory state was restored"):
        store.create_project(title="Dirty Project")

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].project_id == durable_project.project_id
    assert projects[0].title == "Durable Project"


def test_project_archive_restore_persists_tombstone_and_preserves_children(tmp_path: Path) -> None:
    """Ordinary project deletion archives across JSON/SQLite store recreation."""
    snapshot_path = tmp_path / "writing_resources_state.json"
    database_path = tmp_path / "writing_resources_state.sqlite3"
    first_store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    project = first_store.create_project(title="Retention Project")
    section = first_store.create_section(project.project_id, "Intro", order=1)
    draft = first_store.create_draft(project.project_id, section_id=section.section_id, title="Draft", content="body")

    archived = first_store.archive_project(
        project.project_id,
        expected_updated_at=project.updated_at,
        archived_by="tester",
    )
    assert archived is not None
    assert first_store.get_project(project.project_id) is None
    assert first_store.get_project(project.project_id, include_archived=True) is not None
    assert first_store.get_section(section.section_id) is not None
    assert first_store.get_draft(draft.draft_id) is not None
    retention = first_store.get_project_retention(project.project_id)
    assert retention is not None
    receipt_id = retention["archive_receipt"]["receipt_id"]

    second_store = WritingResourceStore(
        persistence_path=snapshot_path,
        database_path=database_path,
        autosave=True,
    )
    assert second_store.list_projects() == []
    archived_reload = second_store.get_project(project.project_id, include_archived=True)
    assert archived_reload is not None
    reloaded_retention = second_store.get_project_retention(project.project_id)
    assert reloaded_retention is not None
    restored = second_store.restore_project(
        project.project_id,
        expected_archive_receipt_id=receipt_id,
        expected_updated_at=archived_reload.updated_at,
        restored_by="tester",
    )
    assert restored is not None
    assert second_store.get_project(project.project_id) is not None
    assert second_store.get_draft(draft.draft_id) is not None
    assert second_store.get_project_retention(project.project_id)["restore_receipt"]["operation"] == "restore"


def test_project_archive_restore_rejects_stale_cas(tmp_path: Path) -> None:
    """Archive and restore reject stale revision/receipt preconditions without mutation."""
    store = WritingResourceStore(persistence_path=tmp_path / "state.json", autosave=True)
    project = store.create_project(title="CAS Project")
    with pytest.raises(ProjectRevisionConflictError):
        store.archive_project(project.project_id, expected_updated_at="stale")
    assert store.get_project(project.project_id) is not None

    archived = store.archive_project(project.project_id, expected_updated_at=project.updated_at)
    assert archived is not None
    retention = store.get_project_retention(project.project_id)
    assert retention is not None
    with pytest.raises(ProjectRevisionConflictError):
        store.restore_project(
            project.project_id,
            expected_archive_receipt_id=retention["archive_receipt"]["receipt_id"],
            expected_updated_at="stale",
        )
    assert store.get_project(project.project_id) is None
