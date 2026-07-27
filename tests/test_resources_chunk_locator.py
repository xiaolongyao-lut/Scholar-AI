# -*- coding: utf-8 -*-
"""Tests for the read-only chunk locator endpoint (Track A L1).

Plan: docs/plans/active/2026-05-15-chunk-page-locator-mini-plan.md
Roadmap: docs/plans/active/2026-05-15-mid-soak-execution-roadmap.md Track A
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import project_paths
from routers import resources_router as rr
from routers.resources_router import endpoints_search_upload as search_upload
from routers.evidence_router import router as evidence_router
from routers.resources_router.endpoints_search_upload import (
    enrich_chunk_locator_with_pdf,
    find_chunk_locator,
    _resolve_material_source_path,
    serve_document_file_base64,
)
from routers.resources_router.endpoints_materials_drafts import delete_material
from routers.resources_router._document_extraction import ExtractedDocumentPayload
from services.unified_batch_upload_service import UnifiedBatchUploadService


def _has_pymupdf() -> bool:
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(name="project_id")
def _project_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    doc_dir = tmp_path / "doc_store"
    chunk_dir = tmp_path / "chunk_store"
    doc_dir.mkdir()
    chunk_dir.mkdir()
    monkeypatch.setattr(rr, "_DOC_STORE_DIR", doc_dir)
    monkeypatch.setattr(rr, "_CHUNK_STORE_DIR", chunk_dir)
    return "proj-locator-1"


@pytest.fixture(name="client")
def _client_fixture() -> TestClient:
    app = FastAPI()
    app.include_router(rr.router)
    app.include_router(evidence_router)
    return TestClient(app)


def _save(project_id: str, store: dict[str, list[dict[str, object]]]) -> None:
    rr._save_chunk_store(project_id, store)  # type: ignore[attr-defined]


def test_figure_asset_api_persists_explicit_bbox_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Figure assets must retain their declared coordinate unit after reload."""

    from routers import writing_router
    from writing_resources import WritingResourceStore

    database_path = tmp_path / "writing-resources.db"
    store = WritingResourceStore(database_path=database_path, autosave=True)
    project = store.create_project(title="Figure bbox contract")
    material = store.create_material(project_id=project.project_id, title="Microscope study")
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    app = FastAPI()
    app.include_router(writing_router.router)
    response = TestClient(app).post(
        "/api/writing/figures",
        json={
            "project_id": project.project_id,
            "kind": "figure",
            "caption": "Microscope field",
            "numbering": "Figure 1",
            "material_id": material.material_id,
            "source_page": 2,
            "bbox": [0.2, 0.25, 0.5, 0.3],
            "bbox_unit": "pdf_points",
            "asset_path": "figure_assets/field.png",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["bbox"] == [0.2, 0.25, 0.5, 0.3]
    assert payload["bbox_unit"] == "pdf_points"

    reloaded = WritingResourceStore(database_path=database_path, autosave=True)
    persisted = reloaded.get_figure_asset(payload["asset_id"])
    assert persisted is not None
    assert persisted.bbox == [0.2, 0.25, 0.5, 0.3]
    assert persisted.bbox_unit == "pdf_points"


def test_figure_asset_api_updates_bbox_and_unit_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Figure metadata updates must replace bbox provenance as one pair."""

    from routers import writing_router
    from writing_resources import WritingResourceStore

    store = WritingResourceStore(database_path=tmp_path / "writing-resources.db", autosave=True)
    project = store.create_project(title="Figure bbox update contract")
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    app = FastAPI()
    app.include_router(writing_router.router)
    client = TestClient(app)
    created = client.post(
        "/api/writing/figures",
        json={
            "project_id": project.project_id,
            "kind": "figure",
            "caption": "Initial field",
            "numbering": "Figure 1",
            "source_page": 2,
            "bbox": [1, 2, 30, 40],
            "bbox_unit": "pdf_points",
            "asset_path": "figure_assets/field.png",
        },
    )
    assert created.status_code == 200, created.text

    updated = client.put(
        f"/api/writing/figures/{created.json()['asset_id']}",
        json={
            "bbox": [12, 24, 120, 80],
            "bbox_unit": "css_pixels",
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["bbox"] == [12.0, 24.0, 120.0, 80.0]
    assert updated.json()["bbox_unit"] == "css_pixels"


@pytest.mark.parametrize(
    "update_payload",
    (
        {"bbox": None, "bbox_unit": None},
        {"bbox": [0.1, 0.2, 0.3, 0.1]},
    ),
)
def test_figure_asset_api_clears_bbox_when_update_has_no_usable_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    update_payload: dict[str, object],
) -> None:
    """An explicit unsafe or empty anchor update must not retain stale precision."""

    from routers import writing_router
    from writing_resources import WritingResourceStore

    store = WritingResourceStore(database_path=tmp_path / "writing-resources.db", autosave=True)
    project = store.create_project(title="Figure bbox clear contract")
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    app = FastAPI()
    app.include_router(writing_router.router)
    client = TestClient(app)
    created = client.post(
        "/api/writing/figures",
        json={
            "project_id": project.project_id,
            "kind": "figure",
            "caption": "Initial field",
            "numbering": "Figure 1",
            "bbox": [1, 2, 30, 40],
            "bbox_unit": "pdf_points",
            "asset_path": "figure_assets/field.png",
        },
    )
    assert created.status_code == 200, created.text

    updated = client.put(
        f"/api/writing/figures/{created.json()['asset_id']}",
        json=update_payload,
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["bbox"] is None
    assert updated.json()["bbox_unit"] is None
    persisted = store.get_figure_asset(created.json()["asset_id"])
    assert persisted is not None
    assert persisted.bbox is None
    assert persisted.bbox_unit is None


def test_figure_asset_repository_preserves_legacy_bbox_until_explicit_clear(
    tmp_path: Path,
) -> None:
    """Unrelated autosaves retain opaque legacy bbox data until explicit clear."""

    from writing_resources import WritingResourceStore

    database_path = tmp_path / "legacy-writing-resources.db"
    initial = WritingResourceStore(database_path=database_path, autosave=True)
    project = initial.create_project(title="Legacy figure database")

    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE figure_assets")
        conn.execute(
            """
            CREATE TABLE figure_assets (
                asset_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                caption TEXT NOT NULL,
                numbering TEXT NOT NULL,
                material_id TEXT,
                source_page INTEGER,
                bbox TEXT,
                asset_path TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                format TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO figure_assets (
                asset_id, project_id, kind, caption, numbering, source_page,
                bbox, asset_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "figure-legacy",
                project.project_id,
                "figure",
                "Legacy field",
                "Figure 1",
                3,
                "[0.1, 0.2, 0.3, 0.4]",
                "figure_assets/legacy.png",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    reloaded = WritingResourceStore(database_path=database_path, autosave=True)
    with sqlite3.connect(database_path) as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(figure_assets)")}
        row = conn.execute(
            "SELECT bbox, bbox_unit FROM figure_assets WHERE asset_id = ?",
            ("figure-legacy",),
        ).fetchone()

    assert "bbox_unit" in columns
    assert row == ("[0.1, 0.2, 0.3, 0.4]", None)
    legacy_asset = reloaded.get_figure_asset("figure-legacy")
    assert legacy_asset is not None
    assert legacy_asset.source_page == 3
    assert legacy_asset.bbox is None
    assert legacy_asset.bbox_unit is None

    reloaded.create_material(
        project_id=project.project_id,
        title="Unrelated autosave trigger",
    )
    with sqlite3.connect(database_path) as conn:
        preserved_row = conn.execute(
            "SELECT bbox, bbox_unit FROM figure_assets WHERE asset_id = ?",
            ("figure-legacy",),
        ).fetchone()

    assert preserved_row is not None
    assert json.loads(str(preserved_row[0])) == [0.1, 0.2, 0.3, 0.4]
    assert preserved_row[1] is None

    updated = reloaded.update_figure_asset(
        "figure-legacy",
        bbox=None,
        bbox_unit=None,
        replace_bbox_anchor=True,
    )
    assert updated is not None
    with sqlite3.connect(database_path) as conn:
        cleared_row = conn.execute(
            "SELECT bbox, bbox_unit FROM figure_assets WHERE asset_id = ?",
            ("figure-legacy",),
        ).fetchone()

    assert cleared_row == (None, None)


def test_candidate_asset_mapping_preserves_bbox_unit() -> None:
    """Generated assets must inherit the candidate's declared coordinate unit."""

    from models import FigureTableCandidatePayload, GenerateFigureAssetsRequest
    from routers.writing_router import _candidate_to_create_asset_payload

    candidate = FigureTableCandidatePayload(
        id="candidate-pdf-points",
        kind="figure",
        label="Figure 1",
        caption="Microscope field",
        material_id="material-1",
        material_title="Microscope study",
        chunk_id="chunk-1",
        page=2,
        bbox=[12, 24, 120, 80],
        bbox_unit="pdf_points",
        asset_path="figure_assets/field.png",
    )
    payload = _candidate_to_create_asset_payload(
        GenerateFigureAssetsRequest(project_id="project-1"),
        candidate,
    )

    assert payload["bbox"] == [12.0, 24.0, 120.0, 80.0]
    assert payload["bbox_unit"] == "pdf_points"


def test_figure_asset_export_preserves_non_ratio_bbox_without_url_inference() -> None:
    """Non-ratio asset coordinates remain provenance, not reader URL coordinates."""

    from routers.resources_router._export_helpers import _build_project_figure_assets_export

    rows = _build_project_figure_assets_export(
        "project-1",
        [
            {
                "asset_id": "figure-1",
                "project_id": "project-1",
                "kind": "figure",
                "caption": "Microscope field",
                "numbering": "Figure 1",
                "material_id": "material-1",
                "source_page": 2,
                "bbox": [0.2, 0.25, 0.5, 0.3],
                "bbox_unit": "pdf_points",
                "asset_path": "figure_assets/field.png",
            }
        ],
    )

    assert rows[0]["bbox"] == [0.2, 0.25, 0.5, 0.3]
    assert rows[0]["bbox_unit"] == "pdf_points"
    assert rows[0]["source_anchor"]["bbox_unit"] == "pdf_points"
    assert "bbox=" not in rows[0]["source_anchor"]["open_url"]


def test_chunk_export_preserves_declared_non_ratio_bbox_unit() -> None:
    """Chunk anchors keep explicit provenance while reader URLs stay ratio-only."""

    from routers.resources_router._export_helpers import _first_material_source_anchor

    anchor = _first_material_source_anchor(
        None,
        "material-1",
        {
            "material-1": [
                {
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "page": 2,
                    "bbox": [12, 24, 120, 80],
                    "bbox_unit": "pdf_points",
                    "content": "Microscope field",
                }
            ]
        },
    )

    assert anchor is not None
    assert anchor["bbox"] == [12.0, 24.0, 120.0, 80.0]
    assert anchor["bbox_unit"] == "pdf_points"
    assert "bbox=" not in anchor["open_url"]


def test_figure_asset_export_drops_bbox_without_explicit_unit() -> None:
    """Legacy unitless asset boxes must degrade to page-only provenance."""

    from routers.resources_router._export_helpers import _build_project_figure_assets_export

    rows = _build_project_figure_assets_export(
        "project-1",
        [
            {
                "asset_id": "figure-legacy",
                "project_id": "project-1",
                "kind": "figure",
                "caption": "Legacy field",
                "numbering": "Figure 2",
                "material_id": "material-1",
                "source_page": 3,
                "bbox": [0.1, 0.2, 0.3, 0.4],
                "asset_path": "figure_assets/legacy.png",
            }
        ],
    )

    assert rows[0]["bbox"] is None
    assert rows[0]["bbox_unit"] is None
    assert rows[0]["source_anchor"]["bbox"] is None
    assert "bbox=" not in rows[0]["source_anchor"]["open_url"]


class _UploadProject:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id


class _UploadMaterial:
    def __init__(self, material_id: str, project_id: str, title: str) -> None:
        self.material_id = material_id
        self.project_id = project_id
        self.title = title


class _UploadStore:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.created: list[_UploadMaterial] = []
        self.deleted: list[str] = []

    def get_project(self, project_id: str) -> _UploadProject | None:
        return _UploadProject(project_id) if project_id == self.project_id else None

    def create_material(
        self,
        *,
        project_id: str,
        title: str,
        title_en: str,
        summary: str,
        summary_en: str,
        material_type: str,
    ) -> _UploadMaterial:
        material = _UploadMaterial(f"mat-upload-{len(self.created) + 1}", project_id, title)
        self.created.append(material)
        return material

    def delete_material(self, material_id: str) -> bool:
        self.deleted.append(material_id)
        return True


class _FirstReadBarrier:
    """Release upload readers only after every participant reached first read."""

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._released = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._released.set()
        await self._released.wait()


class _MemoryUpload:
    """Small UploadFile-compatible stream for direct ingestion tests."""

    content_type = "application/pdf"

    def __init__(self, filename: str, raw: bytes) -> None:
        self.filename = filename
        self._raw = raw
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._raw):
            return b""
        end = len(self._raw) if size < 0 else min(len(self._raw), self._offset + size)
        chunk = self._raw[self._offset:end]
        self._offset = end
        return chunk


class _SynchronizedMemoryUpload(_MemoryUpload):
    """Hold the first payload return until all concurrent uploads are ready."""

    def __init__(self, filename: str, raw: bytes, barrier: _FirstReadBarrier) -> None:
        super().__init__(filename, raw)
        self._barrier = barrier
        self._first_read = True

    async def read(self, size: int = -1) -> bytes:
        chunk = await super().read(size)
        if self._first_read:
            self._first_read = False
            await self._barrier.wait()
        return chunk


class _FileMaterial:
    def __init__(self, material_id: str, project_id: str, title: str = "paper.pdf") -> None:
        self.material_id = material_id
        self.project_id = project_id
        self.title = title
        self.title_en = ""
        self.metadata: dict[str, object] = {}


class _FileStore:
    def __init__(self, material_id: str, project_id: str, title: str = "paper.pdf") -> None:
        self.material = _FileMaterial(material_id, project_id, title)
        self.deleted: list[str] = []

    def get_material(self, material_id: str) -> _FileMaterial | None:
        return self.material if material_id == self.material.material_id else None

    def delete_material(self, material_id: str) -> None:
        self.deleted.append(material_id)


def test_unified_batch_upload_accepts_legacy_save_doc_store() -> None:
    """The legacy save callback is adapted to one read-update-save operation."""

    loaded = {"mat-a": {"title": "A.pdf"}}
    load_calls: list[str] = []
    saved: list[tuple[str, dict[str, dict[str, object]]]] = []

    def _load(project_id: str) -> dict[str, dict[str, object]]:
        load_calls.append(project_id)
        return {material_id: dict(record) for material_id, record in loaded.items()}

    def _save(project_id: str, doc_store: dict[str, dict[str, object]]) -> None:
        saved.append((project_id, doc_store))

    service = UnifiedBatchUploadService(
        persist_upload=lambda *_args: None,
        load_doc_store=_load,
        save_doc_store=_save,
        extract_payload=lambda *_args, **_kwargs: ExtractedDocumentPayload(content="unused"),
        truncate_content=lambda text: text,
        ensure_extracted_text=lambda _filename, text: text,
        write_material_document_content=lambda *_args, **_kwargs: {},
        safe_upload_filename=lambda name: name,
    )

    updated = service.update_doc_store(
        "project-legacy-save",
        lambda doc_store: {
            **doc_store,
            "mat-b": {"title": "B.pdf"},
        },
    )

    assert load_calls == ["project-legacy-save"]
    assert updated == {
        "mat-a": {"title": "A.pdf"},
        "mat-b": {"title": "B.pdf"},
    }
    assert saved == [("project-legacy-save", updated)]


@pytest.mark.parametrize(
    "persistence_callbacks",
    [
        {},
        {
            "update_doc_store": lambda _project_id, updater: updater({}),
            "save_doc_store": lambda _project_id, _doc_store: None,
        },
    ],
    ids=["neither", "both"],
)
def test_unified_batch_upload_requires_exactly_one_store_writer(
    persistence_callbacks: dict[str, object],
) -> None:
    """Ambiguous or absent store mutation callbacks fail during construction."""

    with pytest.raises(
        ValueError,
        match="exactly one of update_doc_store or save_doc_store is required",
    ):
        UnifiedBatchUploadService(
            persist_upload=lambda *_args: None,
            load_doc_store=lambda _project_id: {},
            extract_payload=lambda *_args, **_kwargs: ExtractedDocumentPayload(content="unused"),
            truncate_content=lambda text: text,
            ensure_extracted_text=lambda _filename, text: text,
            write_material_document_content=lambda *_args, **_kwargs: {},
            safe_upload_filename=lambda name: name,
            **persistence_callbacks,
        )


def test_upload_batch_context_rejects_duck_typed_values() -> None:
    """Batch correlation helpers accept only the validated private context type."""

    class _DuckContext:
        def to_result_fields(self) -> dict[str, object]:
            return {"batch_id": "batch_ducktyped", "batch_index": 1, "batch_total": 1}

        def to_job_metadata(self) -> dict[str, object]:
            return {
                "batch_id": "batch_ducktyped",
                "batch_index": 1,
                "batch_total": 1,
                "submitted_at": "2026-07-23T12:00:00+00:00",
            }

    with pytest.raises(TypeError, match="batch_context must be _UploadBatchContext"):
        rr._with_upload_batch_context({}, _DuckContext())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upload_batch_context_entrypoints_reject_duck_typed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ingestion and job entrypoints validate context before touching side effects."""

    import writing_runtime

    class _DuckContext:
        def to_result_fields(self) -> dict[str, object]:
            return {"batch_id": "batch_ducktyped", "batch_index": 1, "batch_total": 1}

        def to_job_metadata(self) -> dict[str, object]:
            return {
                "batch_id": "batch_ducktyped",
                "batch_index": 1,
                "batch_total": 1,
                "submitted_at": "2026-07-23T12:00:00+00:00",
            }

    monkeypatch.setattr(
        writing_runtime,
        "get_writing_runtime",
        lambda: pytest.fail("runtime must not be accessed for invalid batch context"),
    )
    with pytest.raises(TypeError, match="batch_context must be _UploadBatchContext"):
        await rr._ingest_uploaded_document(
            "project-context-guard",
            _MemoryUpload("paper-mono.pdf", b"%PDF-1.4\n%%EOF"),  # type: ignore[arg-type]
            store=object(),
            batch_context=_DuckContext(),  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="batch_context must be _UploadBatchContext"):
        await rr._start_uploaded_document_extraction_job(
            "project-context-guard",
            "material-context-guard",
            "paper.pdf",
            Path("missing.pdf"),
            source_fingerprint="sha256:" + "a" * 64,
            source_size=1,
            batch_context=_DuckContext(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_unified_batch_upload_deduplicates_request_local_fingerprints(
    project_id: str,
    tmp_path: Path,
) -> None:
    """A repeated fingerprint is rejected before extraction or material creation."""

    first_path = tmp_path / "persisted-a.txt"
    second_path = tmp_path / "persisted-b.txt"
    first_path.write_text("same content", encoding="utf-8")
    second_path.write_text("same content", encoding="utf-8")
    fingerprint = "sha256:" + hashlib.sha256(b"same content").hexdigest()
    persisted = {
        "display-a.txt": SimpleNamespace(
            path=first_path,
            fingerprint=fingerprint,
            size=first_path.stat().st_size,
        ),
        "display-b.txt": SimpleNamespace(
            path=second_path,
            fingerprint=fingerprint,
            size=second_path.stat().st_size,
        ),
    }
    extract_calls: list[Path] = []
    written_relative_paths: list[str] = []
    store = _UploadStore(project_id)

    async def _persist_upload(_project_id: str, filename: str, _upload: object) -> object:
        return persisted[filename]

    def _extract_payload(_filename: str, source_path: Path) -> ExtractedDocumentPayload:
        extract_calls.append(source_path)
        return ExtractedDocumentPayload(content="same content")

    def _write_material(*_args: object, **kwargs: object) -> dict[str, object]:
        written_relative_paths.append(str(kwargs["source_relative_path"]))
        return {
            "material_id": "mat-upload-1",
            "title": "display-a.txt",
            "chunks": 1,
            "status": "ok",
        }

    service = UnifiedBatchUploadService(
        persist_upload=_persist_upload,
        load_doc_store=lambda _project_id: {},
        update_doc_store=lambda _project_id, updater: updater({}),
        extract_payload=_extract_payload,
        truncate_content=lambda text: text,
        ensure_extracted_text=lambda _filename, text: text,
        write_material_document_content=_write_material,
        safe_upload_filename=lambda name: name,
    )

    result = await service.process_uploads(
        project_id,
        [
            _MemoryUpload("display-a.txt", b"same content"),
            _MemoryUpload("display-b.txt", b"same content"),
        ],  # type: ignore[list-item]
        store=store,
        enable_filter=False,
    )

    assert len(extract_calls) == 1
    assert len(store.created) == 1
    assert result.duplicate_files == 1
    duplicate = next(item for item in result.results if item["status"] == "duplicate")
    assert duplicate["title"] == "display-b.txt"
    assert written_relative_paths == ["persisted-a.txt"]


@pytest.mark.asyncio
async def test_unified_batch_upload_cleans_source_when_dedupe_check_fails_and_retries(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed authoritative dedupe check must not leak or poison a retry."""

    raw = b"retry after dedupe failure"
    fingerprint = "sha256:" + hashlib.sha256(raw).hexdigest()
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_bytes(raw)
    second_path.write_bytes(raw)
    sources = {
        "first.txt": SimpleNamespace(
            path=first_path,
            fingerprint=fingerprint,
            size=len(raw),
            created=True,
        ),
        "second.txt": SimpleNamespace(
            path=second_path,
            fingerprint=fingerprint,
            size=len(raw),
            created=True,
        ),
    }
    cleaned: list[Path] = []
    extracted: list[Path] = []

    async def _persist(_project_id: str, filename: str, _upload: object) -> object:
        return sources[filename]

    def _cleanup(_project_id: str, source: object) -> bool:
        path = getattr(source, "path")
        cleaned.append(path)
        path.unlink(missing_ok=True)
        return True

    def _extract(_filename: str, source_path: Path, **_kwargs: object) -> ExtractedDocumentPayload:
        extracted.append(source_path)
        return ExtractedDocumentPayload(content=raw.decode("utf-8"))

    def _write(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "ok", "chunks": 1, "content_length": len(raw)}

    store = _UploadStore(project_id)
    service = UnifiedBatchUploadService(
        persist_upload=_persist,
        load_doc_store=lambda _project_id: {},
        update_doc_store=lambda _project_id, updater: updater({}),
        cleanup_uploaded_source=_cleanup,
        extract_payload=_extract,
        truncate_content=lambda text: text,
        ensure_extracted_text=lambda _filename, text: text,
        write_material_document_content=_write,
        safe_upload_filename=lambda name: name,
    )
    dedupe_calls = 0

    def _dedupe(_project_id: str, _filename: str, _source: object) -> None:
        nonlocal dedupe_calls
        dedupe_calls += 1
        if dedupe_calls == 1:
            raise RuntimeError("temporary doc-store read failure")
        return None

    monkeypatch.setattr(service, "_deduplicate_uploaded_source", _dedupe)
    result = await service.process_uploads(
        project_id,
        [
            _MemoryUpload("first.txt", raw),
            _MemoryUpload("second.txt", raw),
        ],  # type: ignore[list-item]
        store=store,
        enable_filter=False,
    )

    assert result.failed_files == 1
    assert result.successful_files == 1
    assert [item["status"] for item in result.results] == ["error", "ok"]
    assert cleaned == [first_path]
    assert not first_path.exists()
    assert second_path.exists()
    assert extracted == [second_path]


@pytest.mark.asyncio
async def test_upload_batch_rejects_more_than_context_limit(
    project_id: str,
) -> None:
    """The route returns a client error before constructing an invalid context."""

    with pytest.raises(HTTPException) as exc_info:
        await search_upload.upload_documents_batch(
            project_id,
            [object()] * (search_upload._MAX_UPLOAD_BATCH_FILES + 1),  # type: ignore[list-item]
        )
    assert exc_info.value.status_code == 400
    assert "最多导入" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_unified_batch_builder_cleans_request_local_duplicate_source(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production cleanup removes only the second unreferenced batch source."""

    source_root = tmp_path / "project_data" / project_id / "source_files"
    source_root.mkdir(parents=True)
    first_path = source_root / "persisted-first.txt"
    second_path = source_root / "persisted-second.txt"
    raw = b"same request-local content"
    first_path.write_bytes(raw)
    second_path.write_bytes(raw)
    fingerprint = "sha256:" + hashlib.sha256(raw).hexdigest()
    persisted = {
        "display-first.txt": rr._UploadedSourceFile(
            path=first_path,
            fingerprint=fingerprint,
            size=len(raw),
            created=True,
        ),
        "display-second.txt": rr._UploadedSourceFile(
            path=second_path,
            fingerprint=fingerprint,
            size=len(raw),
            created=True,
        ),
    }
    extract_calls: list[Path] = []
    store = _UploadStore(project_id)

    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )

    async def _persist(_project_id: str, filename: str, _upload: object) -> object:
        return persisted[filename]

    def _extract(_filename: str, source_path: Path, **_kwargs: object) -> ExtractedDocumentPayload:
        extract_calls.append(source_path)
        return ExtractedDocumentPayload(content="same request-local content")

    def _write(
        current_project_id: str,
        material_id: str,
        filename: str,
        content: str,
        **kwargs: object,
    ) -> dict[str, object]:
        rr._save_doc_store(
            current_project_id,
            {
                material_id: {
                    "title": filename,
                    "content": content,
                    "source_relative_path": str(kwargs["source_relative_path"]),
                    "source_fingerprint": fingerprint,
                }
            },
        )
        return {
            "material_id": material_id,
            "title": filename,
            "chunks": 1,
            "status": "ok",
        }

    monkeypatch.setattr(rr, "_persist_upload_to_source_file", _persist)
    monkeypatch.setattr(rr, "_extract_document_payload_from_path", _extract)
    monkeypatch.setattr(rr, "_write_material_document_content", _write)
    service = rr._build_unified_batch_upload_service()

    result = await service.process_uploads(
        project_id,
        [
            _MemoryUpload("display-first.txt", raw),
            _MemoryUpload("display-second.txt", raw),
        ],  # type: ignore[list-item]
        store=store,
        enable_filter=False,
    )

    assert result.duplicate_files == 1
    assert extract_calls == [first_path]
    assert first_path.is_file()
    assert not second_path.exists()
    assert next(iter(rr._load_doc_store(project_id).values()))["source_relative_path"] == first_path.name


@pytest.mark.asyncio
async def test_unified_batch_builder_cleans_existing_store_duplicate_source(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing-store duplicate removes only its newly-created source."""

    source_root = tmp_path / "project_data" / project_id / "source_files"
    source_root.mkdir(parents=True)
    first_path = source_root / "already-referenced.txt"
    second_path = source_root / "new-duplicate.txt"
    raw = b"already indexed content"
    first_path.write_bytes(raw)
    second_path.write_bytes(raw)
    fingerprint = "sha256:" + hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    rr._save_doc_store(
        project_id,
        {
            "mat-existing": {
                "title": "already-referenced.txt",
                "content": raw.decode("utf-8"),
                "source_relative_path": first_path.name,
                "source_fingerprint": fingerprint,
            }
        },
    )
    persisted = rr._UploadedSourceFile(
        path=second_path,
        fingerprint=fingerprint,
        size=len(raw),
        created=True,
    )
    store = _UploadStore(project_id)

    async def _persist(_project_id: str, _filename: str, _upload: object) -> object:
        return persisted

    def _unexpected_extract(*_args: object, **_kwargs: object) -> ExtractedDocumentPayload:
        raise AssertionError("existing-store duplicate must not extract")

    monkeypatch.setattr(rr, "_persist_upload_to_source_file", _persist)
    monkeypatch.setattr(rr, "_extract_document_payload_from_path", _unexpected_extract)
    service = rr._build_unified_batch_upload_service()

    result = await service.process_uploads(
        project_id,
        [_MemoryUpload("renamed-display.txt", raw)],  # type: ignore[list-item]
        store=store,
        enable_filter=False,
    )

    assert result.duplicate_files == 1
    assert store.created == []
    assert first_path.is_file()
    assert not second_path.exists()


def test_pdf_upload_returns_material_shell_before_extraction(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF upload creates a readable material and queues extraction as a sidecar."""
    store = _UploadStore(project_id)
    batch_contexts: list[object | None] = []
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )

    async def _fake_start_job(
        project_id: str,
        material_id: str,
        filename: str,
        source_path: Path,
        *,
        source_fingerprint: str,
        source_size: int,
        source_relative_path: str | None = None,
        batch_context: object | None = None,
    ) -> tuple[str, str]:
        assert source_path.exists()
        assert source_fingerprint.startswith("sha256:")
        assert source_size > 0
        assert source_relative_path == source_path.name
        batch_contexts.append(batch_context)
        return "session-upload", "job-upload"

    monkeypatch.setattr(rr, "_start_uploaded_document_extraction_job", _fake_start_job)

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[("files", ("paper.pdf", b"%PDF-1.4\nsidecar\n%%EOF", "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"].startswith("batch_")
    submitted_at = datetime.fromisoformat(payload["submitted_at"])
    assert submitted_at.utcoffset() is not None
    assert submitted_at.utcoffset().total_seconds() == 0
    assert payload["total_files"] == 1
    assert payload["accepted_files"] == 1
    assert payload["completed_files"] == 0
    assert payload["successful_files"] == 0
    assert payload["queued_files"] == 1
    assert payload["total_chunks"] == 0
    result = payload["results"][0]
    assert result["status"] == "queued"
    assert result["material_id"] == "mat-upload-1"
    assert result["job_id"] == "job-upload"
    assert result["open_url"] == "/workbench/paper/mat-upload-1"
    assert result["batch_id"] == payload["batch_id"]
    assert result["batch_index"] == 1
    assert result["batch_total"] == 1
    assert len(batch_contexts) == 1
    batch_context = batch_contexts[0]
    assert batch_context is not None
    assert getattr(batch_context, "batch_id") == payload["batch_id"]
    assert getattr(batch_context, "batch_index") == 1
    assert getattr(batch_context, "batch_total") == 1
    assert getattr(batch_context, "submitted_at") == payload["submitted_at"]

    doc_store = rr._load_doc_store(project_id)  # type: ignore[attr-defined]
    chunk_store = rr._load_chunk_store(project_id)  # type: ignore[attr-defined]
    assert doc_store["mat-upload-1"]["extraction_status"] == "queued"
    assert doc_store["mat-upload-1"]["source_relative_path"] == "paper.pdf"
    assert chunk_store["mat-upload-1"] == []


def test_batch_upload_counts_outcomes_and_correlates_every_result(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch counters distinguish accepted work from completed ingestion."""

    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: _UploadStore(project_id))

    async def _fake_ingest(
        _project_id: str,
        upload: object,
        *,
        store: object,
        batch_context: object,
    ) -> dict[str, object]:
        assert store is not None
        assert batch_context is not None
        filename = str(getattr(upload, "filename", ""))
        if filename == "01-queued.pdf":
            return {"title": filename, "status": "queued", "chunks": 0}
        if filename == "02-ok.txt":
            return {"title": filename, "status": "ok", "chunks": 3}
        if filename == "03-duplicate.txt":
            return {"title": filename, "status": "duplicate", "chunks": 0}
        if filename == "04-skipped.txt":
            return {"title": filename, "status": "skipped", "chunks": 0}
        raise ValueError("controlled failure")

    monkeypatch.setattr(rr, "_ingest_uploaded_document", _fake_ingest)
    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[
            ("files", ("01-queued.pdf", b"queued", "application/pdf")),
            ("files", ("02-ok.txt", b"ok", "text/plain")),
            ("files", ("03-duplicate.txt", b"duplicate", "text/plain")),
            ("files", ("04-skipped.txt", b"skipped", "text/plain")),
            ("files", ("05-error.txt", b"error", "text/plain")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 5
    assert payload["accepted_files"] == 2
    assert payload["completed_files"] == 1
    assert payload["successful_files"] == 1
    assert payload["queued_files"] == 1
    assert payload["duplicate_files"] == 1
    assert payload["skipped_files"] == 1
    assert payload["failed_files"] == 1
    assert payload["total_chunks"] == 3
    assert [item["batch_index"] for item in payload["results"]] == [1, 2, 3, 4, 5]
    assert {item["batch_id"] for item in payload["results"]} == {payload["batch_id"]}
    assert {item["batch_total"] for item in payload["results"]} == {5}


def test_batch_upload_mixed_outcomes_uses_real_ingestion_path(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route preserves counters and correlation through real per-file ingestion."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    source_root.mkdir(parents=True)
    duplicate_raw = b"already indexed text"
    existing_source = source_root / "already-indexed.txt"
    existing_source.write_bytes(duplicate_raw)
    duplicate_fingerprint = f"sha256:{hashlib.sha256(duplicate_raw).hexdigest()}"
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    rr._save_doc_store(
        project_id,
        {
            "mat-existing": {
                "title": "03-duplicate.txt",
                "content": duplicate_raw.decode("utf-8"),
                "source_relative_path": existing_source.name,
                "source_fingerprint": duplicate_fingerprint,
                "source_size": len(duplicate_raw),
            }
        },
    )
    extracted_filenames: list[str] = []
    queued_contexts: list[object | None] = []

    def _extract(
        filename: str,
        _source_path: Path,
        **_kwargs: object,
    ) -> ExtractedDocumentPayload:
        extracted_filenames.append(filename)
        return ExtractedDocumentPayload(content="indexed text from ok upload")

    def _write(
        current_project_id: str,
        material_id: str,
        filename: str,
        content: str,
        **kwargs: object,
    ) -> dict[str, object]:
        def _publish(
            doc_store: dict[str, dict[str, object]],
        ) -> dict[str, dict[str, object]]:
            doc_store[material_id] = {
                "title": filename,
                "content": content,
                "source_relative_path": str(kwargs["source_relative_path"]),
                "source_fingerprint": str(kwargs["source_fingerprint"]),
                "source_size": int(kwargs["source_size"]),
            }
            return doc_store

        rr._update_doc_store_atomic(current_project_id, _publish)
        return {
            "material_id": material_id,
            "title": filename,
            "content_length": len(content),
            "chunks": 3,
            "status": "ok",
        }

    async def _start_job(
        _project_id: str,
        _material_id: str,
        _filename: str,
        source_path: Path,
        *,
        source_fingerprint: str,
        source_size: int,
        source_relative_path: str | None = None,
        batch_context: object | None = None,
    ) -> tuple[str, str]:
        assert source_path.is_file()
        assert source_fingerprint.startswith("sha256:")
        assert source_size > 0
        assert source_relative_path == source_path.name
        queued_contexts.append(batch_context)
        return "session-mixed-batch", "job-mixed-batch"

    monkeypatch.setattr(rr, "_extract_document_payload_from_path", _extract)
    monkeypatch.setattr(rr, "_write_material_document_content", _write)
    monkeypatch.setattr(rr, "_start_uploaded_document_extraction_job", _start_job)

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[
            ("files", ("01-queued.pdf", b"%PDF-1.4\nqueued\n%%EOF", "application/pdf")),
            ("files", ("02-ok.txt", b"new text", "text/plain")),
            ("files", ("03-duplicate.txt", duplicate_raw, "text/plain")),
            (
                "files",
                (
                    "04-translated.zh-CN.mono.pdf",
                    b"%PDF-1.4\ntranslated\n%%EOF",
                    "application/pdf",
                ),
            ),
            ("files", ("05-error.exe", b"unsupported", "application/octet-stream")),
        ],
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_files"] == 5
    assert payload["accepted_files"] == 2
    assert payload["completed_files"] == 1
    assert payload["successful_files"] == 1
    assert payload["queued_files"] == 1
    assert payload["duplicate_files"] == 1
    assert payload["skipped_files"] == 1
    assert payload["failed_files"] == 1
    assert payload["total_chunks"] == 3

    results_by_status = {item["status"]: item for item in payload["results"]}
    assert set(results_by_status) == {"queued", "ok", "duplicate", "skipped", "error"}
    assert results_by_status["queued"]["job_id"] == "job-mixed-batch"
    assert results_by_status["ok"]["title"] == "02-ok.txt"
    assert results_by_status["duplicate"]["material_id"] == "mat-existing"
    assert results_by_status["skipped"]["title"] == "04-translated.zh-CN.mono.pdf"
    assert results_by_status["error"]["title"] == "05-error.exe"
    assert sorted(item["batch_index"] for item in payload["results"]) == [1, 2, 3, 4, 5]
    assert {item["batch_id"] for item in payload["results"]} == {payload["batch_id"]}
    assert {item["batch_total"] for item in payload["results"]} == {5}
    assert extracted_filenames == ["02-ok.txt"]
    assert len(queued_contexts) == 1
    assert isinstance(queued_contexts[0], rr._UploadBatchContext)
    assert getattr(queued_contexts[0], "batch_id") == payload["batch_id"]
    assert existing_source.read_bytes() == duplicate_raw
    assert not (source_root / "03-duplicate.txt").exists()


def test_duplicate_pdf_upload_repairs_missing_source_path(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate detection should not preserve a broken reader sidecar."""
    store = _UploadStore(project_id)
    raw = b"%PDF-1.4\nduplicate\n%%EOF"
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat-existing": {
                "title": "paper.pdf",
                "content": "",
                "source_fingerprint": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                "source_size": 0,
            }
        },
    )

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[("files", ("paper.pdf", raw, "application/pdf"))],
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"][0]["status"] == "duplicate"
    doc_store = rr._load_doc_store(project_id)  # type: ignore[attr-defined]
    assert doc_store["mat-existing"]["source_relative_path"] == "paper.pdf"
    assert (tmp_path / "project_data" / project_id / "source_files" / "paper.pdf").read_bytes() == raw


def test_duplicate_pdf_upload_preserves_source_for_equivalent_relative_reference(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equivalent project-relative metadata keeps the restored source file."""

    store = _UploadStore(project_id)
    raw = b"%PDF-1.4\nduplicate restored source\n%%EOF"
    source_path = tmp_path / "project_data" / project_id / "source_files" / "paper.pdf"
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat-existing": {
                "title": "paper.pdf",
                "content": "",
                "source_relative_path": "./paper.pdf",
                "source_fingerprint": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                "source_size": len(raw),
            }
        },
    )
    assert not source_path.exists()

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[("files", ("paper.pdf", raw, "application/pdf"))],
    )

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "duplicate"
    assert source_path.read_bytes() == raw


@pytest.mark.parametrize("reference_variant", ["absolute", "windows-case-variant"])
def test_duplicate_pdf_upload_preserves_source_for_equivalent_absolute_reference(
    reference_variant: str,
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-internal absolute metadata follows platform path semantics."""

    if reference_variant == "windows-case-variant" and os.name != "nt":
        pytest.skip("case-insensitive path equivalence is Windows-specific")
    store = _UploadStore(project_id)
    raw = b"%PDF-1.4\nabsolute duplicate source\n%%EOF"
    source_path = tmp_path / "project_data" / project_id / "source_files" / "paper.pdf"
    source_reference = str(source_path)
    if reference_variant == "windows-case-variant":
        source_reference = source_reference.swapcase()
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat-existing": {
                "title": "paper.pdf",
                "content": "",
                "source_relative_path": source_reference,
                "source_fingerprint": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                "source_size": len(raw),
            }
        },
    )
    assert not source_path.exists()

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[("files", ("paper.pdf", raw, "application/pdf"))],
    )

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "duplicate"
    assert source_path.read_bytes() == raw


def test_duplicate_pdf_upload_does_not_accept_escaped_source_reference(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An escaped same-basename reference does not retain the new source."""

    store = _UploadStore(project_id)
    raw = b"%PDF-1.4\nduplicate source with escaped metadata\n%%EOF"
    source_root = tmp_path / "project_data" / project_id / "source_files"
    source_path = source_root / "paper.pdf"
    escaped_path = source_root.parent / "paper.pdf"
    escaped_path.parent.mkdir(parents=True)
    escaped_bytes = b"outside project source root"
    escaped_path.write_bytes(escaped_bytes)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat-existing": {
                "title": "paper.pdf",
                "content": "",
                "source_relative_path": "../paper.pdf",
                "source_fingerprint": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                "source_size": len(raw),
            }
        },
    )

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project_id},
        files=[("files", ("paper.pdf", raw, "application/pdf"))],
    )

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "duplicate"
    assert not source_path.exists()
    assert escaped_path.read_bytes() == escaped_bytes


@pytest.mark.asyncio
async def test_concurrent_same_pdf_creates_one_material_and_one_job(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent identical PDF requests reserve one material fingerprint."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    started_jobs: list[tuple[str, str, Path]] = []

    async def _fake_start_job(
        current_project_id: str,
        material_id: str,
        filename: str,
        source_path: Path,
        *,
        source_fingerprint: str,
        source_size: int,
        source_relative_path: str | None = None,
    ) -> tuple[str, str]:
        assert current_project_id == project_id
        assert filename == "paper.pdf"
        assert source_fingerprint.startswith("sha256:")
        assert source_size > 0
        assert source_relative_path in {None, source_path.name}
        started_jobs.append((material_id, filename, source_path))
        return "session-upload", f"job-upload-{len(started_jobs)}"

    monkeypatch.setattr(rr, "_start_uploaded_document_extraction_job", _fake_start_job)
    raw = b"%PDF-1.4\nconcurrent duplicate\n%%EOF"
    barrier = _FirstReadBarrier(2)
    first = _SynchronizedMemoryUpload("paper.pdf", raw, barrier)
    second = _SynchronizedMemoryUpload("paper.pdf", raw, barrier)

    results = await asyncio.gather(
        rr._ingest_uploaded_document(project_id, first, store=store),  # type: ignore[arg-type]
        rr._ingest_uploaded_document(project_id, second, store=store),  # type: ignore[arg-type]
    )

    assert sorted(result["status"] for result in results) == ["duplicate", "queued"]
    assert len(store.created) == 1
    assert len(started_jobs) == 1
    doc_store = rr._load_doc_store(project_id)  # type: ignore[attr-defined]
    chunk_store = rr._load_chunk_store(project_id)  # type: ignore[attr-defined]
    assert len(doc_store) == 1
    assert len(chunk_store) == 1
    assert set(chunk_store) == set(doc_store)
    source_path = source_root / next(iter(doc_store.values()))["source_relative_path"]
    assert source_path.read_bytes() == raw
    assert list(source_root.glob("*.part")) == []


@pytest.mark.asyncio
async def test_same_filename_different_content_preserves_both_sources(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same display filename must not overwrite a different PDF fingerprint."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    started_paths: list[Path] = []

    async def _fake_start_job(
        _project_id: str,
        _material_id: str,
        _filename: str,
        source_path: Path,
        *,
        source_fingerprint: str,
        source_size: int,
        source_relative_path: str | None = None,
    ) -> tuple[str, str]:
        assert source_fingerprint.startswith("sha256:")
        assert source_size > 0
        assert source_relative_path in {None, source_path.name}
        started_paths.append(source_path)
        return "session-upload", f"job-upload-{len(started_paths)}"

    monkeypatch.setattr(rr, "_start_uploaded_document_extraction_job", _fake_start_job)
    first_raw = b"%PDF-1.4\nfirst distinct payload\n%%EOF"
    second_raw = b"%PDF-1.4\nsecond distinct payload\n%%EOF"

    first = await rr._ingest_uploaded_document(
        project_id,
        _MemoryUpload("paper.pdf", first_raw),  # type: ignore[arg-type]
        store=store,
    )
    second = await rr._ingest_uploaded_document(
        project_id,
        _MemoryUpload("paper.pdf", second_raw),  # type: ignore[arg-type]
        store=store,
    )

    assert [first["status"], second["status"]] == ["queued", "queued"]
    assert len(store.created) == 2
    assert len(started_paths) == 2
    doc_store = rr._load_doc_store(project_id)  # type: ignore[attr-defined]
    relative_paths = [str(record["source_relative_path"]) for record in doc_store.values()]
    assert len(relative_paths) == 2
    assert len(set(relative_paths)) == 2
    assert {path.read_bytes() for path in (source_root / name for name in relative_paths)} == {
        first_raw,
        second_raw,
    }
    assert {path.name for path in started_paths} == set(relative_paths)
    assert list(source_root.glob("*.part")) == []


@pytest.mark.asyncio
async def test_same_content_different_filename_leaves_no_orphan_source(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate request removes only its newly-created unreferenced source."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    started_jobs: list[str] = []

    async def _fake_start_job(
        _project_id: str,
        material_id: str,
        _filename: str,
        _source_path: Path,
        *,
        source_fingerprint: str,
        source_size: int,
        source_relative_path: str | None = None,
    ) -> tuple[str, str]:
        assert source_fingerprint.startswith("sha256:")
        assert source_size > 0
        assert source_relative_path in {None, "original.pdf"}
        started_jobs.append(material_id)
        return "session-upload", "job-upload"

    monkeypatch.setattr(rr, "_start_uploaded_document_extraction_job", _fake_start_job)
    raw = b"%PDF-1.4\nsame bytes under two names\n%%EOF"

    first = await rr._ingest_uploaded_document(
        project_id,
        _MemoryUpload("original.pdf", raw),  # type: ignore[arg-type]
        store=store,
    )
    second = await rr._ingest_uploaded_document(
        project_id,
        _MemoryUpload("renamed.pdf", raw),  # type: ignore[arg-type]
        store=store,
    )

    assert [first["status"], second["status"]] == ["queued", "duplicate"]
    assert len(store.created) == 1
    assert len(started_jobs) == 1
    doc_store = rr._load_doc_store(project_id)  # type: ignore[attr-defined]
    assert len(doc_store) == 1
    referenced_name = str(next(iter(doc_store.values()))["source_relative_path"])
    assert (source_root / referenced_name).read_bytes() == raw
    assert {path.name for path in source_root.iterdir() if path.is_file()} == {referenced_name}
    assert list(source_root.glob("*.part")) == []


@pytest.mark.asyncio
async def test_pdf_pending_publication_failure_removes_new_material_and_source(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed pending publication must compensate both durable side effects."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    publication_error = OSError("synthetic pending publication failure")
    original_update = rr._update_project_stores_atomic
    publication_failed = False

    def _fail_publication(current_project_id: str, updater: object) -> None:
        nonlocal publication_failed
        assert current_project_id == project_id
        assert callable(updater)
        if getattr(updater, "__name__", "") != "_queue_material":
            original_update(current_project_id, updater)
            return
        assert publication_failed is False
        publication_failed = True
        updater({}, {})
        raise publication_error

    monkeypatch.setattr(rr, "_update_project_stores_atomic", _fail_publication)
    monkeypatch.setattr(rr, "_load_doc_store", lambda _project_id: {})

    with pytest.raises(OSError, match="synthetic pending publication failure") as raised:
        await rr._ingest_uploaded_document(
            project_id,
            _MemoryUpload("failed.pdf", b"%PDF-1.4\nfailed publication\n%%EOF"),  # type: ignore[arg-type]
            store=store,
        )

    assert raised.value is publication_error
    assert store.deleted == ["mat-upload-1"]
    assert not list(source_root.glob("*.pdf"))


@pytest.mark.asyncio
async def test_pdf_pending_material_cleanup_failure_preserves_publication_error(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed material compensation must not replace the publication error."""

    store = _UploadStore(project_id)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    publication_error = OSError("primary publication failure")
    delete_calls: list[str] = []
    original_update = rr._update_project_stores_atomic
    publication_failed = False

    def _fail_publication(current_project_id: str, updater: object) -> None:
        nonlocal publication_failed
        assert callable(updater)
        if getattr(updater, "__name__", "") != "_queue_material":
            original_update(current_project_id, updater)
            return
        assert publication_failed is False
        publication_failed = True
        updater({}, {})
        raise publication_error

    def _fail_delete(material_id: str) -> bool:
        delete_calls.append(material_id)
        raise RuntimeError("synthetic material cleanup failure")

    monkeypatch.setattr(rr, "_update_project_stores_atomic", _fail_publication)
    monkeypatch.setattr(rr, "_load_doc_store", lambda _project_id: {})
    monkeypatch.setattr(store, "delete_material", _fail_delete)

    with caplog.at_level(logging.ERROR, logger=rr.logger.name):
        with pytest.raises(OSError, match="primary publication failure") as raised:
            await rr._ingest_uploaded_document(
                project_id,
                _MemoryUpload("cleanup-fails.pdf", b"%PDF-1.4\ncleanup failure\n%%EOF"),  # type: ignore[arg-type]
                store=store,
            )

    assert raised.value is publication_error
    assert delete_calls == ["mat-upload-1"]
    cleanup_records = [
        record
        for record in caplog.records
        if "pending_material_compensation_failed" in record.getMessage()
    ]
    assert len(cleanup_records) == 1
    assert cleanup_records[0].exc_info is not None


@pytest.mark.asyncio
async def test_pdf_pending_publication_cancellation_is_cleaned_and_re_raised(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation keeps task semantics while compensating owned side effects."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    cancellation = asyncio.CancelledError("synthetic publication cancellation")
    original_update = rr._update_project_stores_atomic
    publication_failed = False

    def _cancel_publication(current_project_id: str, updater: object) -> None:
        nonlocal publication_failed
        assert callable(updater)
        if getattr(updater, "__name__", "") != "_queue_material":
            original_update(current_project_id, updater)
            return
        assert publication_failed is False
        publication_failed = True
        updater({}, {})
        raise cancellation

    monkeypatch.setattr(rr, "_update_project_stores_atomic", _cancel_publication)
    monkeypatch.setattr(rr, "_load_doc_store", lambda _project_id: {})

    with pytest.raises(asyncio.CancelledError) as raised:
        await rr._ingest_uploaded_document(
            project_id,
            _MemoryUpload("cancelled.pdf", b"%PDF-1.4\ncancelled publication\n%%EOF"),  # type: ignore[arg-type]
            store=store,
        )

    assert raised.value is cancellation
    assert store.deleted == ["mat-upload-1"]
    assert not list(source_root.glob("*.pdf"))


@pytest.mark.asyncio
async def test_pdf_pending_source_cleanup_failure_preserves_publication_error(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Source cleanup is best-effort and cannot mask publication failure."""

    store = _UploadStore(project_id)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )
    publication_error = OSError("primary source publication failure")
    original_update = rr._update_project_stores_atomic
    publication_failed = False

    def _fail_publication(current_project_id: str, updater: object) -> None:
        nonlocal publication_failed
        assert callable(updater)
        if getattr(updater, "__name__", "") != "_queue_material":
            original_update(current_project_id, updater)
            return
        assert publication_failed is False
        publication_failed = True
        updater({}, {})
        raise publication_error

    def _fail_source_cleanup(_project_id: str, _uploaded: object) -> bool:
        raise RuntimeError("synthetic source cleanup failure")

    monkeypatch.setattr(rr, "_update_project_stores_atomic", _fail_publication)
    monkeypatch.setattr(rr, "_load_doc_store", lambda _project_id: {})
    monkeypatch.setattr(rr, "_remove_unreferenced_uploaded_source", _fail_source_cleanup)

    with caplog.at_level(logging.ERROR, logger=rr.logger.name):
        with pytest.raises(OSError, match="primary source publication failure") as raised:
            await rr._ingest_uploaded_document(
                project_id,
                _MemoryUpload("source-cleanup-fails.pdf", b"%PDF-1.4\nsource cleanup\n%%EOF"),  # type: ignore[arg-type]
                store=store,
            )

    assert raised.value is publication_error
    assert store.deleted == ["mat-upload-1"]
    cleanup_records = [
        record
        for record in caplog.records
        if "pending_source_compensation_failed" in record.getMessage()
    ]
    assert len(cleanup_records) == 1
    assert cleanup_records[0].exc_info is not None


def test_pdf_duplicate_publication_failure_never_deletes_existing_material(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compensation ownership excludes a duplicate material from an earlier call."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    source_root.mkdir(parents=True)
    source_path = source_root / "duplicate.pdf"
    source_bytes = b"%PDF-1.4\nexisting publication\n%%EOF"
    source_path.write_bytes(source_bytes)
    fingerprint = f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
    existing_material_id = "mat-existing"
    existing_docs = {
        existing_material_id: {
            "title": "existing.pdf",
            "content": "existing",
            "source_relative_path": "duplicate.pdf",
            "source_fingerprint": fingerprint,
            "source_size": len(source_bytes),
        }
    }

    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )

    def _fail_duplicate_publication(_project_id: str, updater: object) -> None:
        assert callable(updater)
        updater(existing_docs, {existing_material_id: []})
        raise OSError("synthetic duplicate publication failure")

    monkeypatch.setattr(
        rr,
        "_update_project_stores_atomic",
        _fail_duplicate_publication,
    )

    with pytest.raises(OSError, match="synthetic duplicate publication failure"):
        rr._create_pending_uploaded_document(
            project_id,
            "duplicate.pdf",
            store=store,
            source_relative_path="duplicate.pdf",
            source_fingerprint=fingerprint,
            source_size=len(source_bytes),
        )

    assert store.created == []
    assert store.deleted == []


def test_pdf_pending_post_commit_reload_failure_preserves_published_material(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ambiguous post-commit error must not create a document dangling reference."""

    store = _UploadStore(project_id)
    source_root = tmp_path / "project_data" / project_id / "source_files"
    source_root.mkdir(parents=True)
    source_path = source_root / "published.pdf"
    source_bytes = b"%PDF-1.4\npublished before reload failure\n%%EOF"
    source_path.write_bytes(source_bytes)
    fingerprint = f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )

    def _commit_then_fail(current_project_id: str, updater: object) -> None:
        assert callable(updater)
        docs, _chunks = updater({}, {})
        rr._save_doc_store(current_project_id, docs)  # type: ignore[attr-defined]
        raise OSError("synthetic post-commit reload failure")

    monkeypatch.setattr(rr, "_update_project_stores_atomic", _commit_then_fail)

    with pytest.raises(OSError, match="synthetic post-commit reload failure"):
        rr._create_pending_uploaded_document(
            project_id,
            "published.pdf",
            store=store,
            source_relative_path="published.pdf",
            source_fingerprint=fingerprint,
            source_size=len(source_bytes),
        )

    assert len(store.created) == 1
    assert store.deleted == []
    assert store.created[0].material_id in rr._load_doc_store(project_id)  # type: ignore[attr-defined]


def test_upload_rejects_file_over_configured_limit_before_material_creation(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oversized uploads fail before material creation or source persistence."""
    store = _UploadStore(project_id)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setenv("LITASSIST_MAX_UPLOAD_BYTES", "8")

    response = client.post(
        "/resources/upload",
        data={"project_id": project_id},
        files={"file": ("oversized.txt", b"0123456789", "text/plain")},
    )

    assert response.status_code == 422
    assert "超过大小上限" in response.text
    assert store.created == []


def test_upload_rejects_unsupported_extension(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Executable-like upload names are rejected at the router boundary."""
    store = _UploadStore(project_id)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    response = client.post(
        "/resources/upload",
        data={"project_id": project_id},
        files={"file": ("payload.exe", b"MZ\x00\x00", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "不支持的上传文件类型" in response.text
    assert store.created == []


def test_upload_rejects_content_type_mismatch(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MIME metadata cannot claim a PDF filename is an HTML document."""
    store = _UploadStore(project_id)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    response = client.post(
        "/resources/upload",
        data={"project_id": project_id},
        files={"file": ("paper.pdf", b"%PDF-1.4\n%%EOF", "text/html")},
    )

    assert response.status_code == 422
    assert "Content-Type" in response.text
    assert store.created == []


def test_upload_rejects_pdf_magic_mismatch(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF uploads must have a PDF signature after cheap leading whitespace."""
    store = _UploadStore(project_id)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    response = client.post(
        "/resources/upload",
        data={"project_id": project_id},
        files={"file": ("paper.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 422
    assert "不是有效的 PDF 文件" in response.text
    assert store.created == []


def test_text_upload_still_ingests_with_guardrails(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allowed small text files still reach extraction, hashing, and source storage."""
    store = _UploadStore(project_id)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(
        rr,
        "project_data_path",
        lambda pid, *parts: tmp_path / "project_data" / pid / Path(*parts),
    )

    response = client.post(
        "/resources/upload",
        data={"project_id": project_id},
        files={"file": ("notes.txt", "激光功率提升后熔池稳定。".encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["chunks"] >= 1
    assert store.created[0].title == "notes.txt"
    assert (tmp_path / "project_data" / project_id / "source_files" / "notes.txt").exists()


def test_resolve_material_source_path_allows_nested_source_folder_file(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "pdfs"
    nested_dir = source_dir / "nested"
    nested_dir.mkdir(parents=True)
    pdf_path = nested_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nallowed\n%%EOF")

    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    monkeypatch.setattr(
        rr,
        "_load_doc_store",
        lambda _project_id: {
            "mat_pdf": {
                "title": "paper.pdf",
                "source_relative_path": "nested/paper.pdf",
            }
        },
    )

    assert _resolve_material_source_path(project_id, "mat_pdf") == pdf_path.resolve()


def test_resolve_material_source_path_allows_uploaded_project_source_file(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project_data" / project_id
    source_dir = project_root / "source_files"
    source_dir.mkdir(parents=True)
    pdf_path = source_dir / "uploaded.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nuploaded\n%%EOF")

    def _project_data_path(pid: str, *parts: str) -> Path:
        return tmp_path / "project_data" / pid / Path(*parts)

    monkeypatch.setattr(project_paths, "project_data_path", _project_data_path)
    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: "")
    monkeypatch.setattr(
        rr,
        "_load_doc_store",
        lambda _project_id: {
            "mat_pdf": {
                "title": "uploaded.pdf",
                "source_relative_path": "uploaded.pdf",
            }
        },
    )

    assert _resolve_material_source_path(project_id, "mat_pdf") == pdf_path.resolve()


def test_document_file_base64_repairs_missing_source_path_from_material_title(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4\nrecovered reader bytes\n%%EOF"
    source_dir = tmp_path / "project_data" / project_id / "source_files"
    source_dir.mkdir(parents=True)
    (source_dir / "recovered.pdf").write_bytes(raw)

    def _project_data_path(pid: str, *parts: str) -> Path:
        return tmp_path / "project_data" / pid / Path(*parts)

    monkeypatch.setattr(project_paths, "project_data_path", _project_data_path)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: _FileStore("mat_pdf", project_id, "recovered.pdf"))
    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: "")
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pdf": {
                "title": "recovered.pdf",
                "content": "",
            }
        },
    )

    response = client.get("/resources/document/mat_pdf/file_b64")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mime"] == "application/pdf"
    assert payload["name"] == "recovered.pdf"
    assert base64.b64decode(payload["data"]) == raw
    doc_store = rr._load_doc_store(project_id)  # type: ignore[attr-defined]
    assert doc_store["mat_pdf"]["source_relative_path"] == "recovered.pdf"


def test_resolve_material_source_path_rejects_traversal_source_reference(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "pdfs"
    source_dir.mkdir()
    outside_pdf = tmp_path / "secret.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\noutside\n%%EOF")

    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    monkeypatch.setattr(
        rr,
        "_load_doc_store",
        lambda _project_id: {
            "mat_pdf": {
                "title": "secret.pdf",
                "source_relative_path": "../secret.pdf",
            }
        },
    )

    assert _resolve_material_source_path(project_id, "mat_pdf") is None


def test_resolve_material_source_path_rejects_absolute_path_outside_allowed_roots(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "pdfs"
    source_dir.mkdir()
    outside_pdf = tmp_path / "absolute-secret.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\noutside\n%%EOF")

    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    monkeypatch.setattr(
        rr,
        "_load_doc_store",
        lambda _project_id: {
            "mat_pdf": {
                "title": "absolute-secret.pdf",
                "source_relative_path": str(outside_pdf),
            }
        },
    )

    assert _resolve_material_source_path(project_id, "mat_pdf") is None


@pytest.mark.asyncio
async def test_file_b64_rejects_large_files_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Material:
        project_id = "proj-b64"

    class _Store:
        def get_material(self, material_id: str):
            return _Material() if material_id == "mat-large" else None

    target = tmp_path / "large.pdf"
    target.write_bytes(b"%PDF" + (b"0" * (8 * 1024 * 1024 + 1)))
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: _Store())
    monkeypatch.setattr(rr, "_load_doc_store", lambda project_id: {"mat-large": {"source_relative_path": "large.pdf"}})
    monkeypatch.setattr(
        "routers.resources_router.endpoints_search_upload._resolve_material_source_path",
        lambda project_id, material_id: target,
    )

    with pytest.raises(HTTPException) as exc_info:
        await serve_document_file_base64("mat-large")

    assert getattr(exc_info.value, "status_code", None) == 413


def test_document_file_base64_serves_nested_source_folder_file(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "pdfs"
    nested_dir = source_dir / "nested"
    nested_dir.mkdir(parents=True)
    raw = b"%PDF-1.4\nallowed reader bytes\n%%EOF"
    (nested_dir / "paper.pdf").write_bytes(raw)

    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: _FileStore("mat_pdf", project_id))
    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pdf": {
                "title": "paper.pdf",
                "source_relative_path": "nested/paper.pdf",
            }
        },
    )

    response = client.get("/resources/document/mat_pdf/file_b64")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mime"] == "application/pdf"
    assert payload["name"] == "paper.pdf"
    assert base64.b64decode(payload["data"]) == raw


def test_document_file_base64_rejects_source_path_traversal(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "pdfs"
    source_dir.mkdir()
    outside_pdf = tmp_path / "secret.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\nsecret reader bytes\n%%EOF")

    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: _FileStore("mat_pdf", project_id))
    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pdf": {
                "title": "secret.pdf",
                "source_relative_path": "../secret.pdf",
            }
        },
    )

    response = client.get("/resources/document/mat_pdf/file_b64")

    assert response.status_code == 404
    assert "secret reader bytes" not in response.text


@pytest.mark.asyncio
async def test_delete_material_does_not_unlink_source_path_traversal(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Material deletion must not trust stored source_relative_path blindly."""

    project_root = tmp_path / "project_data" / project_id
    source_files = project_root / "source_files"
    source_files.mkdir(parents=True)
    outside = project_root / "secret.pdf"
    outside.write_bytes(b"%PDF-1.4\noutside\n%%EOF")
    store = _FileStore("mat_pdf", project_id)

    def _project_data_path(pid: str, *parts: str) -> Path:
        return tmp_path / "project_data" / pid / Path(*parts)

    monkeypatch.setattr(project_paths, "project_data_path", _project_data_path)
    monkeypatch.setattr(rr, "project_data_path", _project_data_path)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {"mat_pdf": {"title": "secret.pdf", "source_relative_path": "../secret.pdf"}},
    )
    rr._save_chunk_store(project_id, {"mat_pdf": []})  # type: ignore[attr-defined]

    result = await delete_material("mat_pdf")

    assert result == {"status": "deleted", "material_id": "mat_pdf"}
    assert outside.exists()
    assert store.deleted == ["mat_pdf"]


# ---------------------------------------------------------------------------
# serve_document_file: ?as=bin / ?as=raw1 / default MIME selection
# 0.1.8.4 PDF-fetch-hardening regression (PdfViewer 204 No Content bug).
# ---------------------------------------------------------------------------

def _setup_serve_file_fixture(
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw: bytes = b"%PDF-1.4\nserve-file body\n%%EOF",
) -> None:
    source_dir = tmp_path / "pdfs"
    source_dir.mkdir()
    (source_dir / "paper.pdf").write_bytes(raw)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: _FileStore("mat_pdf", project_id))
    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {"mat_pdf": {"title": "paper.pdf", "source_relative_path": "paper.pdf"}},
    )


def test_serve_document_file_default_returns_native_pdf_mime(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4\ndefault\n%%EOF"
    _setup_serve_file_fixture(project_id, tmp_path, monkeypatch, raw=raw)

    response = client.get("/resources/document/mat_pdf/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    # Default (no ?as flag) does NOT need the no-store / nosniff disguise —
    # right-click "open in new tab" still works.
    assert "x-content-type-options" not in {k.lower() for k in response.headers}
    assert response.content == raw


def test_serve_document_file_as_bin_returns_octet_stream_legacy(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4\nbin legacy\n%%EOF"
    _setup_serve_file_fixture(project_id, tmp_path, monkeypatch, raw=raw)

    response = client.get("/resources/document/mat_pdf/file?as=bin")

    assert response.status_code == 200
    # 0.1.8.1 legacy disguise still recognized for back-compat.
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("cache-control") == "no-store"
    assert response.content == raw


def test_serve_document_file_as_raw1_returns_vendor_mime_hardened(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4\nvendor hardened\n%%EOF"
    _setup_serve_file_fixture(project_id, tmp_path, monkeypatch, raw=raw)

    response = client.get("/resources/document/mat_pdf/file?as=raw1")

    assert response.status_code == 200
    # 0.1.8.4 hardening: fully private vendor MIME defeats download-manager
    # extensions that still sniff application/octet-stream + PDF magic.
    assert response.headers["content-type"] == "application/vnd.litassist.encoded"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("cache-control") == "no-store"
    # Body must still be the raw PDF — pdf.js parses the bytes directly.
    assert response.content == raw


def test_serve_document_file_unknown_flag_falls_back_to_native(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4\nfallback path\n%%EOF"
    _setup_serve_file_fixture(project_id, tmp_path, monkeypatch, raw=raw)

    # Any unrecognised ?as=... value must behave like the default — never
    # silently apply the vendor MIME or break right-click "open in new tab".
    response = client.get("/resources/document/mat_pdf/file?as=future_flag")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == raw


# ---------------------------------------------------------------------------
# find_chunk_locator (pure helper)
# ---------------------------------------------------------------------------

def test_find_chunk_locator_returns_none_for_empty_store() -> None:
    assert find_chunk_locator({}, "any-id") is None


def test_find_chunk_locator_returns_none_when_chunk_id_unknown() -> None:
    store = {"mat_a": [{"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1}]}
    assert find_chunk_locator(store, "missing") is None


def test_find_chunk_locator_returns_none_for_blank_chunk_id() -> None:
    store = {"mat_a": [{"chunk_id": "mat_a_chunk_0"}]}
    assert find_chunk_locator(store, "") is None


def test_find_chunk_locator_returns_locator_with_page_and_index() -> None:
    store = {
        "mat_a": [
            {"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1},
            {"chunk_id": "mat_a_chunk_3", "chunk_index": 3, "page": 7},
        ],
    }
    result = find_chunk_locator(store, "mat_a_chunk_3")
    assert result == {
        "material_id": "mat_a",
        "chunk_id": "mat_a_chunk_3",
        "page": 7,
        "chunk_index": 3,
    }


def test_find_chunk_locator_omits_bbox_without_explicit_unit() -> None:
    store = {
        "mat_bbox": [
            {
                "chunk_id": "mat_bbox_chunk_0",
                "chunk_index": 0,
                "page": 2,
                "bbox": [0.1, 0.2, 0.3, 0.4],
            }
        ],
    }
    result = find_chunk_locator(store, "mat_bbox_chunk_0")
    assert result is not None
    assert "bbox" not in result
    assert "bbox_unit" not in result


def test_find_chunk_locator_returns_bbox_with_explicit_unit() -> None:
    store = {
        "mat_bbox": [
            {
                "chunk_id": "mat_bbox_chunk_0",
                "chunk_index": 0,
                "page": 2,
                "bbox": [0.1, 0.2, 0.3, 0.4],
                "bbox_unit": "normalized_ratio",
            }
        ],
    }
    result = find_chunk_locator(store, "mat_bbox_chunk_0")
    assert result is not None
    assert result["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert result["bbox_unit"] == "normalized_ratio"


def test_find_chunk_locator_omits_invalid_bbox() -> None:
    store = {
        "mat_bbox": [
            {
                "chunk_id": "mat_bbox_chunk_0",
                "chunk_index": 0,
                "page": 2,
                "bbox": [0.1, "bad", 0.3, 0.4],
            }
        ],
    }
    result = find_chunk_locator(store, "mat_bbox_chunk_0")
    assert result is not None
    assert "bbox" not in result
    assert "bbox_unit" not in result


def test_find_chunk_locator_omits_out_of_range_normalized_bbox() -> None:
    store = {
        "mat_bbox": [
            {
                "chunk_id": "mat_bbox_chunk_0",
                "chunk_index": 0,
                "page": 2,
                "bbox": [10, 20, 130, 220],
            }
        ],
    }
    result = find_chunk_locator(store, "mat_bbox_chunk_0")
    assert result is not None
    assert "bbox" not in result
    assert "bbox_unit" not in result


def test_find_chunk_locator_returns_null_page_when_chunk_lacks_page() -> None:
    # Most current chunks do not record page; locator must keep that shape stable.
    store = {"mat_b": [{"chunk_id": "mat_b_chunk_2", "chunk_index": 2}]}
    result = find_chunk_locator(store, "mat_b_chunk_2")
    assert result is not None
    assert result["page"] is None
    assert result["chunk_index"] == 2


def test_find_chunk_locator_returns_null_chunk_index_when_missing() -> None:
    store = {"mat_c": [{"chunk_id": "mat_c_chunk_5", "page": 4}]}
    result = find_chunk_locator(store, "mat_c_chunk_5")
    assert result is not None
    assert result["chunk_index"] is None
    assert result["page"] == 4


def test_find_chunk_locator_skips_non_dict_chunks_safely() -> None:
    store = {
        "mat_d": [
            "not-a-dict",  # type: ignore[list-item]
            {"chunk_id": "mat_d_chunk_0", "chunk_index": 0, "page": 1},
        ],
    }
    result = find_chunk_locator(store, "mat_d_chunk_0")
    assert result is not None
    assert result["material_id"] == "mat_d"


def test_find_chunk_locator_searches_across_materials() -> None:
    store = {
        "mat_a": [{"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1}],
        "mat_b": [
            {"chunk_id": "mat_b_chunk_0", "chunk_index": 0, "page": 1},
            {"chunk_id": "mat_b_chunk_4", "chunk_index": 4, "page": 9},
        ],
    }
    result = find_chunk_locator(store, "mat_b_chunk_4")
    assert result is not None
    assert result["material_id"] == "mat_b"
    assert result["page"] == 9


def test_find_chunk_locator_rejects_negative_page_as_null() -> None:
    store = {"mat_e": [{"chunk_id": "mat_e_chunk_0", "page": -1, "chunk_index": 0}]}
    result = find_chunk_locator(store, "mat_e_chunk_0")
    assert result is not None
    assert result["page"] is None  # invalid page falls back to null


def test_enrich_chunk_locator_with_pdf_resolves_missing_page_and_bbox(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _has_pymupdf():
        pytest.skip("PyMuPDF is not installed in this environment")

    import pymupdf

    source_dir = tmp_path / "source_files"
    source_dir.mkdir()
    pdf_path = source_dir / "locator.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=240)
    target_text = (
        "Laser welding of aluminum alloy joints was performed with a controlled "
        "travel speed and shielding gas flow to compare fusion-zone porosity."
    )
    page.insert_textbox(pymupdf.Rect(42, 64, 260, 125), target_text, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    monkeypatch.setattr(
        rr,
        "_load_doc_store",
        lambda _project_id: {
            "mat_pdf": {
                "title": "locator.pdf",
                "content": target_text,
                "source_relative_path": "locator.pdf",
            }
        },
    )

    chunk_store = {
        "mat_pdf": [
            {
                "chunk_id": "mat_pdf_chunk_0",
                "chunk_index": 0,
                "raw_content": target_text,
            }
        ]
    }
    base = find_chunk_locator(chunk_store, "mat_pdf_chunk_0")
    assert base is not None
    assert base["page"] is None

    result = enrich_chunk_locator_with_pdf(project_id, chunk_store, base)

    assert result["page"] == 1
    assert result["text_preview"].startswith("Laser welding")
    bbox = result["bbox"]
    assert isinstance(bbox, list)
    assert len(bbox) == 4
    assert all(isinstance(item, float) for item in bbox)
    assert 0.0 <= bbox[0] <= 1.0
    assert 0.0 <= bbox[1] <= 1.0
    assert 0.0 < bbox[2] <= 1.0
    assert 0.0 < bbox[3] <= 1.0
    assert result["bbox_unit"] == "normalized_ratio"


def test_enrich_chunk_locator_with_pdf_drops_bbox_without_explicit_unit(
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_doc_spy = MagicMock(return_value={})
    monkeypatch.setattr(rr, "_load_doc_store", load_doc_spy)
    locator = {
        "material_id": "mat_pdf",
        "chunk_id": "mat_pdf_chunk_0",
        "page": 3,
        "chunk_index": 0,
        "bbox": [0.1, 0.2, 0.3, 0.4],
    }

    result = enrich_chunk_locator_with_pdf(project_id, {"mat_pdf": []}, locator)

    assert result is not locator
    assert result["page"] == 3
    assert "bbox" not in result
    assert "bbox_unit" not in result
    load_doc_spy.assert_not_called()


def test_enrich_chunk_locator_keeps_inferred_bbox_with_its_matched_page(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "relocated-anchor.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")
    target_text = (
        "A sufficiently long citation sentence is repeated here so the "
        "locator can resolve a precise PDF anchor."
    )
    locate_pdf = MagicMock(
        return_value={
            "page": 7,
            "bbox": [0.12, 0.24, 0.5, 0.08],
            "bbox_unit": "normalized_ratio",
            "text_preview": target_text,
        }
    )
    monkeypatch.setattr(
        search_upload,
        "_resolve_material_source_path",
        lambda _project_id, _material_id: source_path,
    )
    monkeypatch.setattr(search_upload, "_locate_chunk_text_in_pdf", locate_pdf)
    search_upload._pdf_locator_cache.clear()
    locator = {
        "material_id": "mat_pdf",
        "chunk_id": "mat_pdf_chunk_relocated",
        "page": 3,
        "chunk_index": 4,
    }
    chunk_store = {
        "mat_pdf": [
            {
                "chunk_id": "mat_pdf_chunk_relocated",
                "chunk_index": 4,
                "page": 3,
                "raw_content": target_text,
            }
        ]
    }

    result = enrich_chunk_locator_with_pdf(project_id, chunk_store, locator)

    assert result["page"] == 7
    assert result["bbox"] == [0.12, 0.24, 0.5, 0.08]
    assert result["bbox_unit"] == "normalized_ratio"
    locate_pdf.assert_called_once_with(source_path, target_text, preferred_page=3)


def test_enrich_chunk_locator_drops_cached_bbox_without_explicit_unit(
    tmp_path: Path,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "legacy-cache-anchor.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")
    target_text = (
        "A sufficiently long legacy locator sentence keeps its page while "
        "an undeclared cached coordinate system is discarded."
    )
    locate_pdf = MagicMock(
        return_value={
            "page": 6,
            "bbox": [0.12, 0.24, 0.5, 0.08],
            "text_preview": target_text,
        }
    )
    monkeypatch.setattr(
        search_upload,
        "_resolve_material_source_path",
        lambda _project_id, _material_id: source_path,
    )
    monkeypatch.setattr(search_upload, "_locate_chunk_text_in_pdf", locate_pdf)
    search_upload._pdf_locator_cache.clear()
    locator = {
        "material_id": "mat_pdf",
        "chunk_id": "mat_pdf_chunk_legacy_cache",
        "page": 3,
        "chunk_index": 4,
    }
    chunk_store = {
        "mat_pdf": [
            {
                "chunk_id": "mat_pdf_chunk_legacy_cache",
                "chunk_index": 4,
                "page": 3,
                "raw_content": target_text,
            }
        ]
    }

    result = enrich_chunk_locator_with_pdf(project_id, chunk_store, locator)

    assert result["page"] == 3
    assert "bbox" not in result
    assert "bbox_unit" not in result
    assert result["text_preview"] == target_text
    locate_pdf.assert_called_once_with(source_path, target_text, preferred_page=3)


# ---------------------------------------------------------------------------
# GET /resources/chunks/{chunk_id}/locator
# ---------------------------------------------------------------------------

def test_locator_endpoint_happy_path_with_page(
    project_id: str, client: TestClient,
) -> None:
    _save(
        project_id,
        {
            "mat_a": [
                {"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1, "content": "x"},
                {"chunk_id": "mat_a_chunk_2", "chunk_index": 2, "page": 5, "content": "y"},
            ],
        },
    )
    resp = client.get(
        "/resources/chunks/mat_a_chunk_2/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "material_id": "mat_a",
        "chunk_id": "mat_a_chunk_2",
        "page": 5,
        "chunk_index": 2,
    }


def test_locator_endpoint_returns_null_page_when_chunk_lacks_page(
    project_id: str, client: TestClient,
) -> None:
    _save(
        project_id,
        {"mat_b": [{"chunk_id": "mat_b_chunk_0", "chunk_index": 0, "content": "z"}]},
    )
    resp = client.get(
        "/resources/chunks/mat_b_chunk_0/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] is None
    assert body["chunk_index"] == 0
    assert body["material_id"] == "mat_b"


def test_locator_endpoint_pdf_fallback_returns_page_bbox_and_preview(
    project_id: str,
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _has_pymupdf():
        pytest.skip("PyMuPDF is not installed in this environment")

    import pymupdf

    source_dir = tmp_path / "pdfs"
    source_dir.mkdir()
    pdf_path = source_dir / "mechanics.pdf"
    target_text = (
        "Dynamic loading tests were conducted on notched steel specimens to "
        "measure crack initiation under cyclic stress amplitudes."
    )
    doc = pymupdf.open()
    page_one = doc.new_page(width=300, height=240)
    page_one.insert_textbox(pymupdf.Rect(40, 50, 260, 110), "Unrelated overview text.", fontsize=10)
    page_two = doc.new_page(width=300, height=240)
    page_two.insert_textbox(pymupdf.Rect(44, 72, 268, 140), target_text, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    monkeypatch.setattr(rr, "_get_project_source_folder", lambda _project_id: str(source_dir))
    rr._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_mech": {
                "title": "mechanics.pdf",
                "content": target_text,
                "source_relative_path": "mechanics.pdf",
            }
        },
    )
    _save(
        project_id,
        {
            "mat_mech": [
                {
                    "chunk_id": "mat_mech_chunk_0",
                    "chunk_index": 0,
                    "content": f"[文献: mechanics.pdf][章节: Results][类型: narrative]\n{target_text}",
                    "raw_content": target_text,
                }
            ]
        },
    )

    resp = client.get(
        "/resources/chunks/mat_mech_chunk_0/locator",
        params={"project_id": project_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["material_id"] == "mat_mech"
    assert body["chunk_id"] == "mat_mech_chunk_0"
    assert body["page"] == 2
    assert body["chunk_index"] == 0
    assert body["text_preview"].startswith("Dynamic loading tests")
    assert len(body["bbox"]) == 4
    assert all(0.0 <= float(item) <= 1.0 for item in body["bbox"])
    assert body["bbox_unit"] == "normalized_ratio"


def test_locator_endpoint_404_for_unknown_chunk(
    project_id: str, client: TestClient,
) -> None:
    _save(
        project_id,
        {"mat_a": [{"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1}]},
    )
    resp = client.get(
        "/resources/chunks/no-such-chunk/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 404


def test_locator_endpoint_422_when_project_id_missing(client: TestClient) -> None:
    resp = client.get("/resources/chunks/any/locator")
    assert resp.status_code == 422


def test_locator_endpoint_422_when_project_id_blank(client: TestClient) -> None:
    resp = client.get(
        "/resources/chunks/any/locator",
        params={"project_id": ""},
    )
    assert resp.status_code == 422


def test_locator_endpoint_404_when_project_has_no_chunk_store(
    project_id: str, client: TestClient,
) -> None:
    # No _save call → empty / missing store; locator must 404, not 500.
    resp = client.get(
        "/resources/chunks/any/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 404


def test_locator_endpoint_resolves_across_materials(
    project_id: str, client: TestClient,
) -> None:
    _save(
        project_id,
        {
            "mat_a": [{"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1}],
            "mat_b": [
                {"chunk_id": "mat_b_chunk_0", "chunk_index": 0, "page": 1},
                {"chunk_id": "mat_b_chunk_3", "chunk_index": 3, "page": 6},
            ],
        },
    )
    resp = client.get(
        "/resources/chunks/mat_b_chunk_3/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["material_id"] == "mat_b"
    assert body["page"] == 6
    assert body["chunk_index"] == 3


def test_api_chunk_to_page_alias_returns_page_index_and_bbox(
    project_id: str, client: TestClient,
) -> None:
    _save(
        project_id,
        {
            "mat_a": [
                {
                    "chunk_id": "mat_a_chunk_bbox",
                    "chunk_index": 4,
                    "page": 8,
                    "bbox": [0.18, 0.22, 0.34, 0.12],
                    "bbox_unit": "normalized_ratio",
                }
            ],
        },
    )
    resp = client.get(
        "/api/chunk_to_page",
        params={"project_id": project_id, "chunk_id": "mat_a_chunk_bbox"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "chunk_id": "mat_a_chunk_bbox",
        "material_id": "mat_a",
        "page": 8,
        "chunk_index": 4,
        "bbox": [0.18, 0.22, 0.34, 0.12],
        "bbox_unit": "normalized_ratio",
        "text_preview": "",
    }


def test_api_chunk_to_page_alias_omits_bbox_without_explicit_unit(
    project_id: str, client: TestClient,
) -> None:
    _save(
        project_id,
        {
            "mat_a": [
                {
                    "chunk_id": "mat_a_chunk_legacy_bbox",
                    "chunk_index": 5,
                    "page": 9,
                    "bbox": [0.2, 0.3, 0.4, 0.1],
                }
            ],
        },
    )

    resp = client.get(
        "/api/chunk_to_page",
        params={"project_id": project_id, "chunk_id": "mat_a_chunk_legacy_bbox"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "chunk_id": "mat_a_chunk_legacy_bbox",
        "material_id": "mat_a",
        "page": 9,
        "chunk_index": 5,
        "bbox": None,
        "bbox_unit": None,
        "text_preview": "",
    }


def test_api_chunk_to_page_alias_404_for_unknown_chunk(
    project_id: str, client: TestClient,
) -> None:
    _save(project_id, {"mat_a": [{"chunk_id": "mat_a_chunk_0", "page": 1}]})
    resp = client.get(
        "/api/chunk_to_page",
        params={"project_id": project_id, "chunk_id": "missing"},
    )
    assert resp.status_code == 404


def test_api_chunk_to_page_alias_422_when_project_id_missing(client: TestClient) -> None:
    resp = client.get("/api/chunk_to_page", params={"chunk_id": "mat_a_chunk_0"})
    assert resp.status_code == 422


def test_locator_endpoint_does_not_call_save_chunk_store(
    project_id: str,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Track A red line: locator must be read-only.

    If the endpoint accidentally routes through _ensure_project_chunks
    (which can call _save_chunk_store), this test will fail.
    """
    _save(
        project_id,
        {"mat_a": [{"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1}]},
    )
    save_spy = MagicMock(side_effect=rr._save_chunk_store)  # type: ignore[attr-defined]
    monkeypatch.setattr(rr, "_save_chunk_store", save_spy)

    resp = client.get(
        "/resources/chunks/mat_a_chunk_0/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 200
    save_spy.assert_not_called()


def test_locator_endpoint_does_not_call_ensure_project_chunks(
    project_id: str,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Belt-and-suspenders: locator must not invoke the backfill helper either."""
    _save(
        project_id,
        {"mat_a": [{"chunk_id": "mat_a_chunk_0", "chunk_index": 0, "page": 1}]},
    )
    ensure_spy = MagicMock(side_effect=rr._ensure_project_chunks)  # type: ignore[attr-defined]
    monkeypatch.setattr(rr, "_ensure_project_chunks", ensure_spy)

    resp = client.get(
        "/resources/chunks/mat_a_chunk_0/locator",
        params={"project_id": project_id},
    )
    assert resp.status_code == 200
    ensure_spy.assert_not_called()
