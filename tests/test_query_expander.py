from __future__ import annotations

import asyncio
import json
from hashlib import sha256

import pytest


@pytest.fixture(autouse=True)
def disable_local_dotenv(monkeypatch) -> None:
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _sampling_hash(payload: dict[str, object]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


def test_translate_query_returns_original_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("VOLCANO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    from query_expander import translate_query

    query = "海洋碳循环的主要驱动因素"
    assert translate_query(query, api_key=None) == query


def test_multi_query_returns_variants_with_original_preserved(monkeypatch) -> None:
    monkeypatch.delenv("VOLCANO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    from query_expander import expand_multi_query

    query = "碳循环机制"
    variants = expand_multi_query(query, api_key=None)
    assert isinstance(variants, list)
    assert len(variants) >= 1
    assert query in variants


def test_hyde_returns_non_empty_text_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("VOLCANO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    from query_expander import generate_hyde

    doc = generate_hyde("什么是生物泵", api_key=None)
    assert isinstance(doc, str)
    assert len(doc.strip()) > 0


def test_expand_multi_query_short_circuits_in_aggressive_cost_mode(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_AI_COST_PROFILE", "aggressive")
    monkeypatch.setenv("ARK_API_KEY", "dummy")
    from query_expander import expand_multi_query

    q = "碳循环机制"
    out = expand_multi_query(q)
    assert out == [q]


def test_generate_hyde_short_circuits_in_aggressive_cost_mode(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_AI_COST_PROFILE", "aggressive")
    monkeypatch.setenv("ARK_API_KEY", "dummy")
    from query_expander import generate_hyde

    q = "什么是生物泵"
    out = generate_hyde(q)
    assert out == q


def test_translate_query_async_uses_http_response(monkeypatch) -> None:
    import model_call_gateway as gateway_mod
    import query_expander as expander_mod

    gateway_mod._LLM_CACHE.clear()

    class _StubResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"unexpected status {self.status_code}")

    class _StubClient:
        def __init__(self, *_args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            assert "responses" in url
            assert isinstance(json, dict)
            _ = headers
            return _StubResponse(
                200,
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "Main drivers of ocean carbon cycling"}
                            ]
                        }
                    ]
                },
            )

    monkeypatch.setattr(expander_mod.httpx, "Client", _StubClient)
    out = asyncio.run(expander_mod.translate_query_async("海洋碳循环", api_key="k"))
    assert "ocean carbon cycling" in out.lower()


def test_translate_query_async_fallbacks_on_ark_content_type_error(monkeypatch) -> None:
    import model_call_gateway as gateway_mod
    import query_expander as expander_mod

    gateway_mod._LLM_CACHE.clear()

    class _StubResponse:
        def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"unexpected status {self.status_code}")

    class _StubClient:
        def __init__(self, *_args, **_kwargs):
            self.calls: list[dict] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            _ = headers
            assert "responses" in url
            self.calls.append(json)
            if len(self.calls) == 1:
                return _StubResponse(
                    400,
                    text='{"error":{"message":"unknown type: text"}}',
                )
            assert isinstance(json.get("input"), str)
            return _StubResponse(
                200,
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "Ocean carbon cycle drivers"}
                            ]
                        }
                    ]
                },
            )

    monkeypatch.setattr(expander_mod.httpx, "Client", _StubClient)
    out = asyncio.run(expander_mod.translate_query_async("海洋碳循环", api_key="k"))
    assert "ocean carbon cycle" in out.lower()


@pytest.mark.parametrize(
    ("runner", "expected_task", "expected_prompt", "gateway_result", "expected_output"),
    [
        (
            lambda mod: asyncio.run(mod.translate_query_async("海洋碳循环", api_key="k")),
            "query_translation",
            "你是科研文献检索翻译专家。将以下中文查询翻译为英文检索查询。\n"
            "要求：\n"
            "1. 保留所有专业术语、材料名称、工艺名称的标准英文表达\n"
            "2. 保留关键量化词（如：高、低、优化、提升）的检索友好译法\n"
            "3. 使用学术文献常见表述，避免口语化\n"
            "4. 仅输出英文翻译，不要解释或添加额外内容\n\n"
            "查询：海洋碳循环",
            "Ocean carbon cycle",
            "Ocean carbon cycle",
        ),
        (
            lambda mod: asyncio.run(mod.expand_multi_query_async("碳循环机制", api_key="k")),
            "query_expansion",
            "作为科研问题改写助手，将以下查询改写为 3 个语义等价但表达不同的检索查询。\n"
            "要求：\n"
            "1. 包含专业表述、口语表述和带约束条件的变体\n"
            "2. 每行一个，不要编号，不要解释\n"
            "查询：碳循环机制",
            "碳循环研究\n碳循环路径",
            ["碳循环机制", "碳循环研究", "碳循环路径"],
        ),
        (
            lambda mod: asyncio.run(mod.generate_hyde_async("什么是生物泵", api_key="k")),
            "generation",
            "你是一名科研检索助手。请针对以下问题生成一段“假设性答案草稿”（约 120-180 字）。\n"
            "要求：\n"
            "1. 包含问题中的关键实体、机制、条件与可能指标\n"
            "2. 使用“可能”、“倾向于”等不确定性表述，不要下最终结论\n"
            "3. 纯文本一段，不要标题或前导语\n\n"
            "问题：什么是生物泵",
            "生物泵是海洋将表层有机碳向深海输送并长期封存的重要过程。",
            "生物泵是海洋将表层有机碳向深海输送并长期封存的重要过程。",
        ),
    ],
)
def test_query_expander_routes_remote_calls_through_gateway(
    monkeypatch,
    runner,
    expected_task: str,
    expected_prompt: str,
    gateway_result,
    expected_output,
) -> None:
    import query_expander as expander_mod

    seen: list[dict[str, object]] = []

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

        async def post(self, url, headers=None, json=None):
            _ = (url, headers, json)
            if isinstance(gateway_result, list):
                text = "\n".join(gateway_result)
            else:
                text = str(gateway_result)
            return _StubResponse(text)

    def fake_gated_call(**kwargs):
        seen.append(kwargs)
        return gateway_result

    monkeypatch.setattr(expander_mod.httpx, "AsyncClient", _StubAsyncClient)
    monkeypatch.setattr(expander_mod, "gated_call", fake_gated_call, raising=False)

    result = runner(expander_mod)

    assert result == expected_output
    assert len(seen) == 1
    assert seen[0]["kind"] == "llm"
    assert seen[0]["cache_key_parts"] == {
        "model": expander_mod.DEFAULT_ARK_MODEL,
        "prompt_hash": _prompt_hash(expected_prompt),
        "sampling_params_hash": _sampling_hash({}),
        "task": expected_task,
    }


def test_decompose_query_async_parses_fenced_json(monkeypatch) -> None:
    import query_expander as expander_mod

    async def fake_call(*_args, **_kwargs):
        return """```json
[
  {"id": 1, "task": "工艺参数范围", "reason": "识别工艺条件"},
  {"id": 2, "task": "关键性能指标", "reason": "识别量化结果"}
]
```"""

    monkeypatch.setattr(expander_mod, "_call_ark_async", fake_call, raising=False)

    result = asyncio.run(expander_mod.decompose_query_async("测试问题", api_key="k"))

    assert result == [
        {"id": 1, "task": "工艺参数范围", "reason": "识别工艺条件"},
        {"id": 2, "task": "关键性能指标", "reason": "识别量化结果"},
    ]


def test_expand_multi_query_strips_numbered_markers(monkeypatch) -> None:
    import query_expander as expander_mod

    async def fake_call(*_args, **_kwargs):
        return "1. 碳循环研究\n2) 碳循环路径\n- 碳循环机制"

    monkeypatch.setattr(expander_mod, "_call_ark_async", fake_call, raising=False)

    result = asyncio.run(expander_mod.expand_multi_query_async("碳循环机制", api_key="k", n=4))

    assert result == ["碳循环机制", "碳循环研究", "碳循环路径"]


def test_translate_query_prompt_includes_domain_terminology_guidance(monkeypatch) -> None:
    import query_expander as expander_mod

    captured_prompt = None

    async def fake_call(prompt, *_args, **_kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return "laser welding process optimization"

    monkeypatch.setattr(expander_mod, "_call_ark_async", fake_call, raising=False)

    asyncio.run(expander_mod.translate_query_async("激光焊接工艺优化", api_key="k"))

    assert captured_prompt is not None
    assert "专业术语" in captured_prompt or "材料名称" in captured_prompt
    assert "学术文献" in captured_prompt or "检索友好" in captured_prompt

