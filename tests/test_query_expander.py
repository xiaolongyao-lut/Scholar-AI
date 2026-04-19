from __future__ import annotations

import asyncio


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


def test_translate_query_async_uses_http_response(monkeypatch) -> None:
    import query_expander as expander_mod

    class _StubResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class _StubAsyncClient:
        def __init__(self, *_args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
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

    monkeypatch.setattr(expander_mod.httpx, "AsyncClient", _StubAsyncClient)
    out = asyncio.run(expander_mod.translate_query_async("海洋碳循环", api_key="k"))
    assert "ocean carbon cycling" in out.lower()


def test_translate_query_async_fallbacks_on_ark_content_type_error(monkeypatch) -> None:
    import query_expander as expander_mod

    class _StubResponse:
        def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    class _StubAsyncClient:
        def __init__(self, *_args, **_kwargs):
            self.calls: list[dict] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
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

    monkeypatch.setattr(expander_mod.httpx, "AsyncClient", _StubAsyncClient)
    out = asyncio.run(expander_mod.translate_query_async("海洋碳循环", api_key="k"))
    assert "ocean carbon cycle" in out.lower()
