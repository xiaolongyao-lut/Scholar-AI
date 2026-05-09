from __future__ import annotations

import json
from pathlib import Path


SUMMARY_KEYS = (
    "topic",
    "objective",
    "material_system",
    "process_method",
    "key_metrics",
    "main_conclusion",
    "keywords",
)


def _write_chunk_store(project_dir: Path, materials: dict[str, list[dict[str, object]]]) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest_materials: dict[str, dict[str, object]] = {}
    for material_id, chunks in materials.items():
        relative_path = f"{material_id}.jsonl"
        with (project_dir / relative_path).open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        manifest_materials[material_id] = {
            "relative_path": relative_path,
            "sha256": material_id,
            "total_chunks": len(chunks),
        }
    (project_dir / "manifest.json").write_text(
        json.dumps({"version": 2, "materials": manifest_materials}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _summary_payload(material_id: str) -> dict[str, object]:
    return {
        "topic": f"topic-{material_id}",
        "objective": f"objective-{material_id}",
        "material_system": f"system-{material_id}",
        "process_method": f"method-{material_id}",
        "key_metrics": f"metric-{material_id}",
        "main_conclusion": f"conclusion-{material_id}",
        "keywords": [f"kw-{material_id}", "shared"],
    }


def test_precompute_contextual_summaries_writes_three_artifacts(monkeypatch, tmp_path) -> None:
    from scripts import precompute_contextual_summaries as script

    monkeypatch.chdir(tmp_path)
    project_id = "demo"
    _write_chunk_store(
        tmp_path / "output" / "chunk_store" / project_id,
        {
            "m1": [{"material_id": "m1", "content": "alpha"}],
            "m2": [{"material_id": "m2", "content": "beta"}],
            "m3": [{"material_id": "m3", "content": "gamma"}],
        },
    )

    calls: list[str] = []

    async def fake_summarize_document_json_async(chunks, **_kwargs):
        material_id = str(chunks[0]["material_id"])
        calls.append(material_id)
        return _summary_payload(material_id)

    monkeypatch.setattr(script, "summarize_document_json_async", fake_summarize_document_json_async)

    written = script.precompute_contextual_summaries(project_id)

    assert len(written) == 3
    assert calls == ["m1", "m2", "m3"]
    for material_id in ("m1", "m2", "m3"):
        payload = json.loads(
            (tmp_path / "output" / "contextual_summaries" / project_id / f"{material_id}.json").read_text(
                encoding="utf-8"
            )
        )
        assert tuple(payload.keys()) == SUMMARY_KEYS
        assert payload["main_conclusion"] == f"conclusion-{material_id}"


def test_precompute_contextual_summaries_skips_existing_artifacts_on_repeat_run(monkeypatch, tmp_path) -> None:
    from scripts import precompute_contextual_summaries as script

    monkeypatch.chdir(tmp_path)
    project_id = "demo"
    _write_chunk_store(
        tmp_path / "output" / "chunk_store" / project_id,
        {
            "m1": [{"material_id": "m1", "content": "alpha"}],
            "m2": [{"material_id": "m2", "content": "beta"}],
            "m3": [{"material_id": "m3", "content": "gamma"}],
        },
    )

    calls: list[str] = []

    async def fake_summarize_document_json_async(chunks, **_kwargs):
        material_id = str(chunks[0]["material_id"])
        calls.append(material_id)
        return _summary_payload(material_id)

    monkeypatch.setattr(script, "summarize_document_json_async", fake_summarize_document_json_async)

    script.precompute_contextual_summaries(project_id)
    assert calls == ["m1", "m2", "m3"]

    calls.clear()
    script.precompute_contextual_summaries(project_id)
    assert calls == []


def test_batch_contextualize_logs_miss_without_online_generation(monkeypatch, tmp_path) -> None:
    import contextual_chunker as chunker

    monkeypatch.chdir(tmp_path)
    calls = {"count": 0}

    async def fail_online_summary(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("online summary generation should not run on contextual artifact miss")

    monkeypatch.setattr(chunker, "summarize_document_json_async", fail_online_summary, raising=False)

    chunks = [{"content": "raw chunk", "material_id": "m1", "chunk_id": "c1"}]
    miss_log_path = tmp_path / "output" / "contextual_miss.jsonl"

    result = chunker.batch_contextualize(
        chunks,
        api_key="test-key",
        project_id="demo",
        summaries_root=tmp_path / "output" / "contextual_summaries",
        miss_log_path=miss_log_path,
    )

    assert result == chunks
    assert calls["count"] == 0
    rows = miss_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["project_id"] == "demo"
    assert payload["material_id"] == "m1"


def test_precompute_contextual_summaries_dry_run_respects_limit(monkeypatch, tmp_path, capsys) -> None:
    from scripts import precompute_contextual_summaries as script

    monkeypatch.chdir(tmp_path)
    project_id = "demo"
    _write_chunk_store(
        tmp_path / "output" / "chunk_store" / project_id,
        {
            "m1": [{"material_id": "m1", "content": "alpha"}],
            "m2": [{"material_id": "m2", "content": "beta"}],
            "m3": [{"material_id": "m3", "content": "gamma"}],
        },
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("dry-run should not call remote summary generation")

    monkeypatch.setattr(script, "summarize_document_json_async", fail_if_called)

    written = script.precompute_contextual_summaries(
        project_id,
        limit=2,
        dry_run=True,
        model="gpt-4o-mini",
    )

    out = capsys.readouterr().out
    assert written == []
    assert "[dry-run]" in out
    assert "pending=2" in out
    assert "est_usd=" in out
    assert not (tmp_path / "output" / "contextual_summaries" / project_id).exists()
