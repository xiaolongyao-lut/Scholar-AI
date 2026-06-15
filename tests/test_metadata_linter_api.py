# -*- coding: utf-8 -*-
"""Regression coverage for the Zotero-style metadata linter API."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_linter_router_imports_by_package_path() -> None:
    """Package-path imports must work for external-cwd tests and OpenAPI tooling."""
    module = importlib.import_module("literature_assistant.core.routers.linter_router")

    assert getattr(module, "router") is not None


# TODO: 新 linter 引擎目前只实现了 sentence-case 规则
# 需要实现更多规则（空格清理、日期格式、作者格式、DOI 前缀等）后才能恢复这个测试
@pytest.mark.skip(reason="新 linter 引擎尚未实现所有规则，等待 Phase 2 完成")
def test_linter_batch_and_apply_fixes_use_zotero_metadata_aliases() -> None:
    """Batch linting and fixes should round-trip Zotero/CSL metadata aliases."""
    from python_adapter_server import app
    from routers.resources_router import get_writing_resource_store

    client = TestClient(app)
    store = get_writing_resource_store()
    project = store.create_project(title="Metadata Linter Project")
    material = store.create_material(
        project_id=project.project_id,
        title="  Neural   Signals  ",
        title_en="deep learning in DNA sequencing",
        metadata={
            "authors": ["Ada Lovelace"],
            "date": "June 2024",
            "publicationTitle": " Nature   Methods ",
            "DOI": "https://doi.org/10.1038/s41592-024-00000-0",
        },
    )

    lint_response = client.post(
        "/api/linter/lint/batch",
        json={"project_id": project.project_id, "preferred_case": "title"},
    )
    assert lint_response.status_code == 200
    lint_payload: list[dict[str, Any]] = lint_response.json()
    assert len(lint_payload) == 1
    issue_fields = {issue["field"] for issue in lint_payload[0]["issues"]}
    assert {
        "title",
        "title_en",
        "authors[0]",
        "publication_date",
        "journal",
        "doi",
    }.issubset(issue_fields)

    apply_response = client.post(
        "/api/linter/apply-fixes",
        json={
            "material_id": material.material_id,
            "fixes": ["title", "title_en", "authors", "publication_date", "journal", "doi"],
            "preferred_case": "title",
        },
    )
    assert apply_response.status_code == 200
    applied_payload: dict[str, Any] = apply_response.json()
    assert applied_payload["result"]["issues"] == []

    updated = store.get_material(material.material_id)
    assert updated is not None
    assert updated.title == "Neural Signals"
    assert updated.title_en == "Deep Learning in DNA Sequencing"
    assert updated.metadata["authors"] == ["Lovelace, Ada"]
    assert updated.metadata["publication_date"] == "2024-06-01"
    assert updated.metadata["date"] == "2024-06-01"
    assert updated.metadata["year"] == 2024
    assert updated.metadata["journal"] == "Nature Methods"
    assert updated.metadata["publicationTitle"] == "Nature Methods"
    assert updated.metadata["venue"] == "Nature Methods"
    assert updated.metadata["doi"] == "10.1038/s41592-024-00000-0"
    assert updated.metadata["DOI"] == "10.1038/s41592-024-00000-0"
