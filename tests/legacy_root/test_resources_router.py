# -*- coding: utf-8 -*-

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import resources_router as rr
from writing_resources import WritingResourceStore


def save_doc_store(project_id: str, store: dict[str, dict[str, str]]) -> None:
    getattr(rr, "_save_doc_store")(project_id, store)


def save_chunk_store(project_id: str, store: dict[str, list[dict[str, object]]]) -> None:
    getattr(rr, "_save_chunk_store")(project_id, store)


def ensure_project_chunks(project_id: str):
    return getattr(rr, "_ensure_project_chunks")(project_id)


def load_doc_store(project_id: str):
    return getattr(rr, "_load_doc_store")(project_id)


def load_chunk_store(project_id: str):
    return getattr(rr, "_load_chunk_store")(project_id)


@pytest.fixture(name="resource_project_id")
def _resource_project_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    doc_dir = tmp_path / "doc_store"
    chunk_dir = tmp_path / "chunk_store"
    doc_dir.mkdir()
    chunk_dir.mkdir()
    monkeypatch.setattr(rr, "_DOC_STORE_DIR", doc_dir)
    monkeypatch.setattr(rr, "_CHUNK_STORE_DIR", chunk_dir)
    return "project-1"


def test_ensure_project_chunks_backfills_and_prunes_stale_entries(resource_project_id: str) -> None:
    project_id = resource_project_id
    save_doc_store(
        project_id,
        {
            "mat-1": {
                "title": "paper-a.pdf",
                "content": "激光功率增加会提高沉积效率。" * 40,
            }
        },
    )
    save_chunk_store(
        project_id,
        {
            "stale-material": [
                {
                    "chunk_id": "stale-material_chunk_0",
                    "material_id": "stale-material",
                    "title": "old.pdf",
                    "chunk_index": 0,
                    "content": "过期内容",
                    "char_count": 4,
                }
            ]
        },
    )

    chunk_store = ensure_project_chunks(project_id)

    assert "mat-1" in chunk_store
    assert "stale-material" not in chunk_store
    assert chunk_store["mat-1"][0]["material_id"] == "mat-1"
    assert chunk_store["mat-1"][0]["title"] == "paper-a.pdf"


@pytest.mark.asyncio
async def test_search_chunks_uses_backfilled_documents(resource_project_id: str) -> None:
    project_id = resource_project_id
    save_doc_store(
        project_id,
        {
            "mat-2": {
                "title": "paper-b.pdf",
                "content": "本文表明激光功率增加会提高沉积效率，并改善熔池稳定性。",
            }
        },
    )

    result = await rr.search_chunks(project_id=project_id, query="激光功率", top_k=5)

    assert result["results"]
    assert result["results"][0]["material_id"] == "mat-2"
    assert "激光功率增加" in result["results"][0]["content"]


@pytest.mark.asyncio
async def test_search_chunks_prefers_distinct_materials_before_repeat_chunks(
    resource_project_id: str,
) -> None:
    project_id = resource_project_id
    save_doc_store(
        project_id,
        {
            "mat-a": {"title": "paper-a.pdf", "content": "实验数据对比分析显示激光功率影响熔池稳定性。"},
            "mat-b": {"title": "paper-b.pdf", "content": "实验数据对比分析指出扫描速度影响缺陷生成。"},
            "mat-c": {"title": "paper-c.pdf", "content": "实验数据对比分析比较了送粉量与热输入。"},
        },
    )
    save_chunk_store(
        project_id,
        {
            "mat-a": [
                {
                    "chunk_id": "mat-a_chunk_0",
                    "material_id": "mat-a",
                    "title": "paper-a.pdf",
                    "chunk_index": 0,
                    "content": "实验数据对比分析显示激光功率影响熔池稳定性。",
                    "char_count": 22,
                },
                {
                    "chunk_id": "mat-a_chunk_1",
                    "material_id": "mat-a",
                    "title": "paper-a.pdf",
                    "chunk_index": 1,
                    "content": "实验数据对比分析还显示晶粒尺寸变化明显。",
                    "char_count": 20,
                },
            ],
            "mat-b": [
                {
                    "chunk_id": "mat-b_chunk_0",
                    "material_id": "mat-b",
                    "title": "paper-b.pdf",
                    "chunk_index": 0,
                    "content": "实验数据对比分析指出扫描速度影响缺陷生成。",
                    "char_count": 21,
                }
            ],
            "mat-c": [
                {
                    "chunk_id": "mat-c_chunk_0",
                    "material_id": "mat-c",
                    "title": "paper-c.pdf",
                    "chunk_index": 0,
                    "content": "实验数据对比分析比较了送粉量与热输入。",
                    "char_count": 19,
                }
            ],
        },
    )

    result = await rr.search_chunks(project_id=project_id, query="实验数据对比分析", top_k=3)

    assert [item["title"] for item in result["results"]] == [
        "paper-a.pdf",
        "paper-b.pdf",
        "paper-c.pdf",
    ]


@pytest.mark.asyncio
async def test_search_chunks_deduplicates_identical_chunks_within_same_material(
    resource_project_id: str,
) -> None:
    project_id = resource_project_id
    duplicated_content = "激光功率提升后，熔池稳定性增强，孔隙率下降。"
    save_doc_store(
        project_id,
        {
            "mat-d": {"title": "paper-d.pdf", "content": duplicated_content},
            "mat-e": {"title": "paper-e.pdf", "content": "激光功率提升后，表面粗糙度也发生变化。"},
        },
    )
    save_chunk_store(
        project_id,
        {
            "mat-d": [
                {
                    "chunk_id": "mat-d_chunk_0",
                    "material_id": "mat-d",
                    "title": "paper-d.pdf",
                    "chunk_index": 0,
                    "content": duplicated_content,
                    "char_count": len(duplicated_content),
                },
                {
                    "chunk_id": "mat-d_chunk_1",
                    "material_id": "mat-d",
                    "title": "paper-d.pdf",
                    "chunk_index": 1,
                    "content": duplicated_content,
                    "char_count": len(duplicated_content),
                },
            ],
            "mat-e": [
                {
                    "chunk_id": "mat-e_chunk_0",
                    "material_id": "mat-e",
                    "title": "paper-e.pdf",
                    "chunk_index": 0,
                    "content": "激光功率提升后，表面粗糙度也发生变化。",
                    "char_count": 19,
                }
            ],
        },
    )

    result = await rr.search_chunks(project_id=project_id, query="激光功率提升", top_k=3)

    assert [item["title"] for item in result["results"]].count("paper-d.pdf") == 1


class _FakeMaterial:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id


class _FakeStore:
    def __init__(self, project_id: str) -> None:
        self._project_id = project_id
        self.deleted: list[str] = []

    def get_material(self, material_id: str):
        if material_id == "mat-3":
            return _FakeMaterial(self._project_id)
        return None

    def delete_material(self, material_id: str) -> None:
        self.deleted.append(material_id)


class _FakeUploadStore:
    def __init__(self, project_id: str, *, fail_titles: set[str] | None = None) -> None:
        self._project_id = project_id
        self._fail_titles = fail_titles or set()
        self.created: list[dict[str, str]] = []

    def get_project(self, project_id: str):
        if project_id == self._project_id:
            return SimpleNamespace(project_id=project_id)
        return None

    def create_material(self, **kwargs):
        title = str(kwargs.get("title") or "")
        if title in self._fail_titles:
            raise RuntimeError(f"mock create failure: {title}")
        material_id = f"mat-upload-{len(self.created) + 1}"
        self.created.append({"material_id": material_id, "title": title})
        return SimpleNamespace(material_id=material_id)


@pytest.mark.asyncio
async def test_delete_material_removes_doc_and_chunk_entries(
    resource_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = resource_project_id
    save_doc_store(
        project_id,
        {"mat-3": {"title": "paper-c.pdf", "content": "用于删除测试的内容"}},
    )
    save_chunk_store(
        project_id,
        {
            "mat-3": [
                {
                    "chunk_id": "mat-3_chunk_0",
                    "material_id": "mat-3",
                    "title": "paper-c.pdf",
                    "chunk_index": 0,
                    "content": "用于删除测试的内容",
                    "char_count": 9,
                }
            ]
        },
    )

    fake_store = _FakeStore(project_id)
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: fake_store)

    result = await rr.delete_material("mat-3")

    assert result == {"status": "deleted", "material_id": "mat-3"}
    assert fake_store.deleted == ["mat-3"]
    assert "mat-3" not in load_doc_store(project_id)
    assert "mat-3" not in load_chunk_store(project_id)


def test_batch_upload_endpoint_reports_success_and_failure(
    resource_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_store = _FakeUploadStore(resource_project_id, fail_titles={"bad.txt"})
    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: fake_store)

    app = FastAPI()
    app.include_router(rr.router)
    client = TestClient(app)

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": resource_project_id},
        files=[
            ("files", ("good.txt", "激光功率提升后熔池稳定。".encode("utf-8"), "text/plain")),
            ("files", ("bad.txt", b"this one fails", "text/plain")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 2
    assert payload["successful_files"] == 1
    assert payload["failed_files"] == 1
    assert payload["total_chunks"] >= 1
    assert payload["results"][0]["title"] == "good.txt"
    assert payload["results"][0]["status"] == "ok"
    assert payload["results"][1]["title"] == "bad.txt"
    assert payload["results"][1]["status"] == "error"

    doc_store = load_doc_store(resource_project_id)
    chunk_store = load_chunk_store(resource_project_id)
    assert len(doc_store) == 1
    assert len(chunk_store) == 1
    assert next(iter(doc_store.values()))["title"] == "good.txt"


def test_data_cleanup_preview_reports_duplicate_projects_and_empty_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WritingResourceStore()
    keep_project = store.create_project(title="My Project")
    duplicate_project = store.create_project(title="  my   project  ")
    extra_project = store.create_project(title="Independent Project")

    placeholder_material = store.create_material(
        project_id=keep_project.project_id,
        title="scan-only.pdf",
        summary="",
    )
    valid_material = store.create_material(
        project_id=extra_project.project_id,
        title="valid.txt",
        summary="",
    )

    save_doc_store(
        keep_project.project_id,
        {
            placeholder_material.material_id: {
                "title": "scan-only.pdf",
                "content": "[PDF 解析失败: encrypted]",
            }
        },
    )
    save_chunk_store(keep_project.project_id, {placeholder_material.material_id: []})

    save_doc_store(
        extra_project.project_id,
        {
            valid_material.material_id: {
                "title": "valid.txt",
                "content": "This is valid extractable content.",
            }
        },
    )
    save_chunk_store(
        extra_project.project_id,
        {
            valid_material.material_id: [
                {
                    "chunk_id": f"{valid_material.material_id}_chunk_0",
                    "material_id": valid_material.material_id,
                    "title": "valid.txt",
                    "chunk_index": 0,
                    "content": "This is valid extractable content.",
                    "char_count": 34,
                }
            ]
        },
    )

    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    app = FastAPI()
    app.include_router(rr.router)
    client = TestClient(app)

    response = client.post("/resources/maintenance/cleanup", json={"dry_run": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["preview"]["duplicate_project_count"] == 1
    assert payload["preview"]["empty_material_count"] == 1
    assert len(payload["preview"]["duplicate_projects"]) == 1
    assert len(payload["preview"]["empty_materials"]) == 1
    # preview must not mutate state
    assert len(store.list_projects()) == 3
    assert store.get_material(placeholder_material.material_id) is not None
    assert store.get_project(duplicate_project.project_id) is not None


def test_data_cleanup_execute_removes_duplicate_projects_and_empty_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WritingResourceStore()
    keep_project = store.create_project(title="Laser Control")
    duplicate_project = store.create_project(title=" laser   control ")

    bad_material = store.create_material(
        project_id=keep_project.project_id,
        title="no-text.pdf",
        summary="",
    )
    save_doc_store(
        keep_project.project_id,
        {
            bad_material.material_id: {
                "title": "no-text.pdf",
                "content": "[未知格式文件: no-text.pdf]",
            }
        },
    )
    save_chunk_store(keep_project.project_id, {bad_material.material_id: []})

    monkeypatch.setattr(rr, "get_writing_resource_store", lambda: store)

    app = FastAPI()
    app.include_router(rr.router)
    client = TestClient(app)

    response = client.post("/resources/maintenance/cleanup", json={"dry_run": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["deleted"]["duplicate_project_count"] == 1
    assert payload["deleted"]["empty_material_count"] == 1
    assert store.get_project(duplicate_project.project_id) is None
    assert store.get_material(bad_material.material_id) is None
    assert bad_material.material_id not in load_doc_store(keep_project.project_id)
    assert bad_material.material_id not in load_chunk_store(keep_project.project_id)
