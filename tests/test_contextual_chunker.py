from __future__ import annotations

import asyncio
import json
from hashlib import sha256


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _sampling_hash(payload: dict[str, object]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


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


def test_batch_contextualize_short_circuits_in_aggressive_cost_mode(monkeypatch) -> None:
    from contextual_chunker import batch_contextualize

    monkeypatch.setenv("LITERATURE_AI_COST_PROFILE", "aggressive")
    monkeypatch.setenv("ARK_API_KEY", "dummy")

    chunks = [{"content": "chunk", "material_id": "m1", "chunk_id": "c1"}]
    result = batch_contextualize(chunks)

    assert result == chunks


def test_summarize_document_async_routes_remote_calls_through_gateway(monkeypatch, tmp_path) -> None:
    import contextual_chunker as chunker_mod

    seen: list[dict[str, object]] = []
    summary_text = "本文总结海洋碳循环与关键观测对象。"
    cache_path = tmp_path / "doc_summaries.json"
    chunks = [
        {"material_id": "m1", "content": "第一段内容"},
        {"material_id": "m1", "content": "第二段内容"},
    ]
    prompt = (
        "请阅读以下文档片段，生成2-3句中文摘要，突出主题与研究对象。"
        "仅输出摘要正文，不要编号。\n\n"
        "文档片段：第一段内容 第二段内容"
    )

    class _StubResponse:
        def __init__(self, text: str):
            self.status_code = 200
            self.text = text
            self._text = text

        def json(self):
            return {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": self._text},
                        ]
                    }
                ]
            }

    class _StubAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json_body=None):
            _ = (url, headers, json_body)
            return _StubResponse(summary_text)

    def fake_gated_call(**kwargs):
        seen.append(kwargs)
        return summary_text

    monkeypatch.setattr(chunker_mod.httpx, "AsyncClient", _StubAsyncClient)
    monkeypatch.setattr(chunker_mod, "gated_call", fake_gated_call, raising=False)

    summary = asyncio.run(
        chunker_mod.summarize_document_async(
            chunks,
            api_key="k",
            cache_path=cache_path,
        )
    )

    assert summary == summary_text
    assert len(seen) == 1
    assert seen[0]["kind"] == "llm"
    assert seen[0]["cache_key_parts"] == {
        "model": chunker_mod.DEFAULT_ARK_MODEL,
        "prompt_hash": _prompt_hash(prompt),
        "sampling_params_hash": _sampling_hash({}),
        "task": "contextual_summary",
    }
    assert json.loads(cache_path.read_text(encoding="utf-8")) == {"m1": summary_text}


def test_summarize_document_json_async_accepts_fenced_json(monkeypatch) -> None:
    import contextual_chunker as chunker_mod

    fenced_json = """```json
{
  "topic": "激光扩散渗氮处理Ti-6Al-4V合金",
  "objective": "提升表面硬度和耐磨性",
  "material_system": "Ti-6Al-4V钛合金",
  "process_method": "激光扩散渗氮",
  "key_metrics": "硬度约11.3 GPa",
  "main_conclusion": "可在不熔化表面的前提下显著提升性能",
  "keywords": ["激光扩散渗氮", "Ti-6Al-4V", "耐磨性"]
}
```"""
    seen: list[dict[str, object]] = []

    def fake_gated_call(**kwargs):
        seen.append(kwargs)
        return fenced_json

    monkeypatch.setattr(chunker_mod, "gated_call", fake_gated_call, raising=False)

    summary = asyncio.run(
        chunker_mod.summarize_document_json_async(
            [{"material_id": "m1", "content": "第一段内容"}],
            api_key="k",
        )
    )

    assert summary == {
        "topic": "激光扩散渗氮处理Ti-6Al-4V合金",
        "objective": "提升表面硬度和耐磨性",
        "material_system": "Ti-6Al-4V钛合金",
        "process_method": "激光扩散渗氮",
        "key_metrics": "硬度约11.3 GPa",
        "main_conclusion": "可在不熔化表面的前提下显著提升性能",
        "keywords": ["激光扩散渗氮", "Ti-6Al-4V", "耐磨性"],
    }
    assert len(seen) == 1
    assert seen[0]["kind"] == "llm"
