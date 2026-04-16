# -*- coding: utf-8 -*-
"""Persistence regression tests for the writing resource store."""

from __future__ import annotations

from pathlib import Path

from writing_resources import WritingResourceStore


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
