from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import chunk_vector_store as cvs
from chunk_size_guard import inspect_text
from routers import resources_router as rr


@pytest.fixture
def tmp_chunk_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    output_dir = tmp_path / "output"
    chunk_root = output_dir / "chunk_store"
    chunk_root.mkdir(parents=True, exist_ok=True)

    def fake_resolve(_project_id: str) -> tuple[Path, Path]:
        return output_dir, chunk_root

    monkeypatch.setattr(rr, "_resolve_data_dir", fake_resolve)
    monkeypatch.setattr(rr, "_CHUNK_QUARANTINE_LOG_PATH", output_dir / "chunk_quarantine.jsonl")
    return output_dir, chunk_root


def _vector_batch(texts: list[str]) -> list[list[float]]:
    return [[0.5] * cvs.EMBEDDING_DIM for _ in texts]


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_build_rejects_char_oversize_chunk_before_embedding_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    called = False

    async def fake_batch(*args, **kwargs):
        nonlocal called
        called = True
        return _vector_batch(args[0])

    monkeypatch.setattr(cvs, "_batch_embed", fake_batch)

    with pytest.raises(cvs.EmbeddingAPIError, match="chunk hard limit"):
        asyncio.run(
            cvs.ChunkVectorStore.build(
                [{"chunk_id": "c1", "material_id": "m1", "content": "x" * 6001}],
            )
        )

    assert called is False


def test_build_rejects_token_oversize_chunk_even_when_chars_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.setenv("CHUNK_HARD_MAX_CHARS", "99999")
    called = False
    token_heavy = "word " * 1500
    assert inspect_text(token_heavy)["over_tokens"] is True

    async def fake_batch(*args, **kwargs):
        nonlocal called
        called = True
        return _vector_batch(args[0])

    monkeypatch.setattr(cvs, "_batch_embed", fake_batch)

    with pytest.raises(cvs.EmbeddingAPIError, match="chunk hard limit"):
        asyncio.run(
            cvs.ChunkVectorStore.build(
                [{"chunk_id": "c1", "material_id": "m1", "content": token_heavy}],
            )
        )

    assert called is False


def test_build_allows_chunk_when_hard_limits_are_relaxed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.setenv("CHUNK_HARD_MAX_CHARS", "99999")
    monkeypatch.setenv("CHUNK_HARD_MAX_TOKENS", "99999")
    seen_texts: list[str] = []

    async def fake_batch(texts, *args, **kwargs):
        seen_texts.extend(texts)
        return _vector_batch(texts)

    monkeypatch.setattr(cvs, "_batch_embed", fake_batch)
    chunk = {"chunk_id": "c1", "material_id": "m1", "content": "x" * 6001}

    store = asyncio.run(cvs.ChunkVectorStore.build([chunk]))

    assert store.has_embeddings is True
    assert seen_texts == [chunk["content"]]


def test_save_chunk_store_quarantines_oversize_chunks_and_logs_event(
    tmp_chunk_output: tuple[Path, Path],
) -> None:
    output_dir, chunk_root = tmp_chunk_output
    rr._save_chunk_store(
        "proj",
        {
            "mat-a": [
                {
                    "chunk_id": "ok",
                    "material_id": "mat-a",
                    "title": "Alpha.pdf",
                    "content": "normal chunk",
                    "raw_content": "normal chunk",
                },
                {
                    "chunk_id": "oversize",
                    "material_id": "mat-a",
                    "title": "Alpha.pdf",
                    "content": "x" * 6001,
                    "raw_content": "x" * 6001,
                },
            ]
        },
    )

    loaded = rr._load_chunk_store("proj")
    assert [chunk["chunk_id"] for chunk in loaded["mat-a"]] == ["ok"]

    quarantine_dir = chunk_root / "proj" / "_quarantine"
    quarantine_files = list(quarantine_dir.glob("*.jsonl"))
    assert len(quarantine_files) == 1
    assert [chunk["chunk_id"] for chunk in _read_jsonl(quarantine_files[0])] == ["oversize"]

    records = _read_jsonl(output_dir / "chunk_quarantine.jsonl")
    assert len(records) == 1
    assert records[0]["project_id"] == "proj"
    assert records[0]["material_id"] == "mat-a"
    assert records[0]["quarantined_chunk_count"] == 1


def test_quarantine_does_not_remove_other_safe_materials(
    tmp_chunk_output: tuple[Path, Path],
) -> None:
    rr._save_chunk_store(
        "proj",
        {
            "mat-a": [
                {
                    "chunk_id": "oversize",
                    "material_id": "mat-a",
                    "title": "Alpha.pdf",
                    "content": "x" * 6001,
                    "raw_content": "x" * 6001,
                }
            ],
            "mat-b": [
                {
                    "chunk_id": "safe",
                    "material_id": "mat-b",
                    "title": "Beta.pdf",
                    "content": "beta chunk",
                    "raw_content": "beta chunk",
                }
            ],
        },
    )

    loaded = rr._load_chunk_store("proj")

    assert set(loaded.keys()) == {"mat-b"}
    assert [chunk["chunk_id"] for chunk in loaded["mat-b"]] == ["safe"]
