from __future__ import annotations


def test_contextual_prefix_added() -> None:
    from contextual_chunker import add_context_prefix

    chunk = {"content": "方法：采用 ABC 技术", "material_id": "m1"}
    doc_summary = "本文研究海洋碳循环"
    result = add_context_prefix(chunk, doc_summary)
    assert result["content"].startswith("[")
    assert "海洋碳循环" in result["content"]
    assert "ABC 技术" in result["content"]


def test_contextual_preserves_original() -> None:
    from contextual_chunker import add_context_prefix

    chunk = {"content": "原始内容", "material_id": "m1", "chunk_id": "c1"}
    result = add_context_prefix(chunk, "摘要")
    assert result["raw_content"] == "原始内容"
    assert result["chunk_id"] == "c1"


def test_batch_contextualize(monkeypatch) -> None:
    from contextual_chunker import batch_contextualize

    monkeypatch.delenv("VOLCANO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    chunks = [{"content": f"chunk {i}", "material_id": "m1"} for i in range(5)]
    result = batch_contextualize(chunks, api_key=None)
    assert len(result) == 5
    assert all(item["content"] == f"chunk {i}" for i, item in enumerate(result))
