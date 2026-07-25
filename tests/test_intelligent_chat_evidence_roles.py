from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from literature_assistant.core.local_citation_scope import (
    LocalCitationMatch,
    LocalCitationResolution,
    SelectionParagraphWindow,
)
from python_adapter_server import app
from routers import intelligent_chat_router as router


def _chunk(
    *,
    index: int,
    material_id: str,
    source: str,
    evidence_role: router.EvidenceRole = "project_context",
) -> router.ContextChunkPayload:
    return router.ContextChunkPayload(
        index=index,
        source=source,
        content=f"Evidence from {source}.",
        chunk_id=f"chunk-{material_id}-{index}",
        material_id=material_id,
        evidence_role=evidence_role,
        page=4,
        source_labels=["project_chunks"],
    )


def _citation_scope() -> LocalCitationResolution:
    return LocalCitationResolution(
        window=SelectionParagraphWindow(
            anchor_text="The selected method follows prior work [2].",
            adjacent_text="The adjacent paragraph describes the comparison setup.",
            anchor_chunk_id="chunk-current-anchor",
            page=4,
        ),
        matches=(
            LocalCitationMatch(
                material_id="mat-cited",
                material_title="Cited Paper",
                marker="[2]",
                reference_text="Reference entry for the cited paper.",
                match_reason="doi",
            ),
        ),
    )


def _request_payload(*, session_id: str) -> dict[str, object]:
    return {
        "query": "Explain the selected method and its cited basis",
        "tier": "balanced",
        "project_id": "project-roles",
        "material_id": "mat-current",
        "session_id": session_id,
        "answer_origin": "external_agent",
        "current_pdf_context": {
            "material_id": "mat-current",
            "page": 4,
            "selected_text": "The selected method follows prior work [2].",
            "bbox": [0.1, 0.2, 0.4, 0.15],
            "bbox_unit": "normalized_ratio",
            "context_kind": "selection",
        },
    }


def _sse_payloads(response_text: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for line in response_text.splitlines():
        if not line.startswith("data:"):
            continue
        raw_payload = line.removeprefix("data:").strip()
        if not raw_payload:
            continue
        decoded = json.loads(raw_payload)
        assert isinstance(decoded, dict)
        payloads.append(decoded)
    return payloads


def test_context_chunks_from_evidence_refs_preserves_evidence_role() -> None:
    refs = [
        router.EvidenceReferencePayload(
            chunk_id="chunk-cited-1",
            material_id="mat-cited",
            evidence_role="cited_project_material",
            source="Cited Paper",
            text="Original evidence from the cited project material.",
            quote="Original evidence from the cited project material.",
            source_labels=["local_citation_reference"],
        )
    ]

    chunks, truncated = router._context_chunks_from_evidence_refs(refs, "balanced")

    assert truncated is False
    assert len(chunks) == 1
    assert chunks[0].evidence_role == "cited_project_material"


def test_context_chunk_evidence_selector_fields_survive_round_trip() -> None:
    """SmartRead must retain exact selectors and persisted chunk identity."""

    ref = router.EvidenceReferencePayload(
        chunk_id="chunk-method-1",
        material_id="mat-method",
        evidence_role="project_context",
        source="Methods",
        text="Laser power was 2000 W.",
        quote="Laser power was 2000 W.",
        anchor_kind="text",
        content_hash="1" * 64,
        locator_hash="2" * 64,
        chunk_hash="3" * 64,
        embedding_input_hash="4" * 64,
        hash_version="scholar-ai-chunk-hash/v2",
        page=7,
        bbox=[0.1, 0.2, 0.3, 0.1],
        bbox_unit="normalized_ratio",
    )

    chunks, truncated = router._context_chunks_from_evidence_refs([ref], "balanced")
    assert truncated is False
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.quote == ref.quote
    assert chunk.anchor_kind == "text"
    assert chunk.content_hash == ref.content_hash
    assert chunk.locator_hash == ref.locator_hash
    assert chunk.chunk_hash == ref.chunk_hash
    assert chunk.embedding_input_hash == ref.embedding_input_hash
    assert chunk.hash_version == ref.hash_version

    rebuilt = router._build_evidence_refs_from_context_chunks(chunks)
    assert len(rebuilt) == 1
    rebuilt_ref = rebuilt[0]
    assert rebuilt_ref.quote == ref.quote
    assert rebuilt_ref.anchor_kind == ref.anchor_kind
    assert rebuilt_ref.content_hash == ref.content_hash
    assert rebuilt_ref.locator_hash == ref.locator_hash
    assert rebuilt_ref.chunk_hash == ref.chunk_hash
    assert rebuilt_ref.embedding_input_hash == ref.embedding_input_hash
    assert rebuilt_ref.hash_version == ref.hash_version


def test_visual_evidence_ref_marks_caption_as_non_text_anchor() -> None:
    """Caption text must not be reused as a sentence selector for visuals."""

    refs = router._build_visual_evidence_refs_from_chunks(
        [
            {
                "chunk_id": "figure-1",
                "material_id": "mat-visual",
                "content": "Figure 1. Surface morphology.",
                "figure_candidate": "figure:1",
                "image_paths": ["figures/figure-1.png"],
                "page": 3,
                "bbox": [0.1, 0.2, 0.5, 0.3],
                "bbox_unit": "normalized_ratio",
            }
        ]
    )

    assert len(refs) == 1
    assert refs[0].anchor_kind == "visual"
    assert refs[0].quote == ""


def test_project_text_chunk_builds_exact_quote_without_summary_fallback() -> None:
    quote = router._bounded_exact_chunk_quote(
        {
            "chunk_type": "body",
            "summary": "Paraphrased method summary that is not in the PDF.",
            "content": "[文献: Ping]\nThe oscillation amplitude was 1.0 mm at 150 Hz.",
        },
        anchor_kind="text",
        fallback_content="unused fallback",
        query="oscillation amplitude 1.0 mm 150 Hz",
    )

    assert quote == "The oscillation amplitude was 1.0 mm at 150 Hz."
    assert "Paraphrased" not in quote

    bounded = router._bounded_exact_chunk_quote(
        {"quote": "x" * 400},
        anchor_kind="text",
        fallback_content="unused fallback",
        query="x",
    )
    assert bounded == "x" * 320
    assert not bounded.endswith("…")


def test_current_pdf_text_selection_keeps_exact_quote_separate_from_prompt_preview() -> None:
    selected_text = "Exact  spacing\nand line breaks remain source text. " + ("x" * 1800)
    request = router.IntelligentChatRequest.model_validate(
        {
            "query": "Inspect the selected paragraph",
            "material_id": "mat-selection",
            "current_pdf_context": {
                "material_id": "mat-selection",
                "selection": {
                    "kind": "text",
                    "page": 3,
                    "text": selected_text,
                    "chunk_id": "selection-text-3",
                },
            },
        }
    )

    chunk = router._current_pdf_context_chunks(request)[0]
    assert chunk.quote == selected_text[:320].rstrip()
    assert chunk.quote in selected_text
    assert not chunk.quote.endswith("…")
    assert "\n" in chunk.quote
    assert "…" in chunk.content


def test_durable_resume_keeps_quote_and_summary_out_of_missing_text() -> None:
    refs = router._coerce_resume_evidence_refs(
        [
            {
                "chunk_id": "chunk-durable-quote",
                "material_id": "mat-durable",
                "source": "Durable evidence",
                "summary": "Paraphrased durable summary.",
                "quote": "Exact durable source sentence.",
            }
        ]
    )

    assert len(refs) == 1
    assert refs[0].text == ""
    assert refs[0].quote == "Exact durable source sentence."


def test_internal_pdf_context_cannot_reconstruct_missing_bbox_unit() -> None:
    """Internal model bypasses must still degrade an untyped bbox to page-only."""

    selection = router.PdfContentSelectionPayload.model_construct(
        kind="region",
        page=3,
        bbox=[0.1, 0.2, 0.4, 0.3],
        bbox_unit=None,
    )
    context = router.CurrentPdfContextPayload.model_construct(
        material_id="mat-internal",
        page=3,
        bbox=[0.1, 0.2, 0.4, 0.3],
        bbox_unit=None,
        selection=selection,
        selections=[selection],
    )

    rendered = router._render_current_pdf_context_content(context)
    assert "bbox_unit=" not in rendered

    request = router.IntelligentChatRequest.model_construct(
        query="Inspect the selected region",
        current_pdf_context=context,
    )
    payload = router._vision_aux_pdf_context(request, [])
    assert payload is not None
    assert payload["selections"] == [{"selection_kind": "region", "page": 3}]
    assert "bbox" not in payload
    assert "bbox_unit" not in payload


@pytest.mark.asyncio
async def test_empty_cited_material_retrieval_never_enables_project_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str | None, bool]] = []

    async def _empty_cited_context(
        _query: str,
        _project_id: str,
        _tier: router.ContextTier,
        *,
        boost_keywords: list[str] | None,
        material_id: str | None,
        visual_evidence_sink: list[router.EvidenceReferencePayload],
        allow_project_fallback: bool,
    ) -> tuple[list[router.ContextChunkPayload], bool]:
        assert boost_keywords == ["laser"]
        assert visual_evidence_sink == []
        calls.append((material_id, allow_project_fallback))
        return [], False

    monkeypatch.setattr(router, "_build_project_context_chunks", _empty_cited_context)
    base = [_chunk(index=1, material_id="mat-current", source="Current Paper")]

    chunks, truncated = await router._merge_local_citation_retrieval(
        query="Explain the selected method",
        project_id="project-roles",
        tier="balanced",
        boost_keywords=["laser"],
        base_chunks=base,
        base_truncated=False,
        citation_scope=_citation_scope(),
    )

    assert calls == [("mat-cited", False)]
    assert chunks is base
    assert truncated is False


@pytest.mark.parametrize(
    "endpoint",
    ["/api/chat", "/api/chat/stream"],
    ids=["post", "stream"],
)
def test_mismatched_current_pdf_material_fails_before_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    retrieval_calls: list[str] = []

    def _citation_retrieval(
        _req: router.IntelligentChatRequest,
        _project_id: str | None,
    ) -> LocalCitationResolution:
        retrieval_calls.append("citation_scope")
        return LocalCitationResolution(window=None)

    async def _project_retrieval(
        _query: str,
        _project_id: str,
        _tier: router.ContextTier,
        **_kwargs: object,
    ) -> tuple[list[router.ContextChunkPayload], bool]:
        retrieval_calls.append("project_context")
        return [], False

    monkeypatch.setattr(router, "_validate_project_id", lambda value: value)
    monkeypatch.setattr(router, "_ragworkflow_chat_enabled", lambda: False)
    monkeypatch.setattr(router, "_resolve_current_pdf_citation_scope", _citation_retrieval)
    monkeypatch.setattr(router, "_build_project_context_chunks", _project_retrieval)
    response = TestClient(app).post(
        endpoint,
        json={
            "query": "Explain the selected paragraph",
            "project_id": "project-roles",
            "material_id": "mat-request",
            "answer_origin": "external_agent",
            "current_pdf_context": {
                "material_id": "mat-context",
                "page": 2,
                "selected_text": "Selected paragraph.",
                "context_kind": "selection",
            },
        },
    )

    assert response.status_code == 422
    assert "current_pdf_context.material_id must match material_id" in response.text
    assert retrieval_calls == []


def test_post_stream_and_resume_preserve_the_same_evidence_roles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    retrieval_calls: list[tuple[str | None, bool]] = []
    capture_calls: list[tuple[str | None, str]] = []

    async def _project_context(
        _query: str,
        _project_id: str,
        _tier: router.ContextTier,
        *,
        boost_keywords: list[str] | None,
        material_id: str | None,
        visual_evidence_sink: list[router.EvidenceReferencePayload],
        allow_project_fallback: bool,
    ) -> tuple[list[router.ContextChunkPayload], bool]:
        del boost_keywords
        assert visual_evidence_sink == []
        retrieval_calls.append((material_id, allow_project_fallback))
        if material_id == "mat-current":
            return [_chunk(index=1, material_id="mat-current", source="Current Paper")], False
        if material_id == "mat-cited":
            return [_chunk(index=1, material_id="mat-cited", source="Cited Paper")], False
        raise AssertionError(f"unexpected material lookup: {material_id}")

    monkeypatch.setattr(router, "_SESSION_STORE_PATH", tmp_path / "sessions.json")
    monkeypatch.setattr(router, "_validate_project_id", lambda value: value)
    monkeypatch.setattr(router, "_ragworkflow_chat_enabled", lambda: False)
    monkeypatch.setattr(router, "_resolve_current_pdf_citation_scope", lambda *_args: _citation_scope())
    monkeypatch.setattr(
        router,
        "_schedule_local_citation_capture",
        lambda *, project_id, session_id, **_kwargs: capture_calls.append(
            (project_id, session_id)
        ),
    )
    monkeypatch.setattr(router, "_build_project_context_chunks", _project_context)
    monkeypatch.setattr(router, "_import_session_to_history_store", lambda _session: None)
    monkeypatch.setattr(
        router,
        "_supplement_visual_evidence_refs_for_answer",
        lambda *, existing_refs, **_kwargs: list(existing_refs),
    )

    client = TestClient(app)
    post_response = client.post(
        "/api/chat",
        json=_request_payload(session_id="session-role-post"),
    )
    assert post_response.status_code == 200
    post_roles = [ref["evidence_role"] for ref in post_response.json()["evidence_refs"]]

    stream_response = client.post(
        "/api/chat/stream",
        json=_request_payload(session_id="session-role-stream"),
    )
    assert stream_response.status_code == 200
    stream_metadata = next(
        payload
        for payload in _sse_payloads(stream_response.text)
        if payload.get("event") == "metadata"
    )
    stream_refs = stream_metadata["evidence_refs"]
    assert isinstance(stream_refs, list)
    stream_roles = [ref["evidence_role"] for ref in stream_refs]

    expected_roles = [
        "selected_content",
        "current_material",
        "cited_project_material",
    ]
    assert post_roles == expected_roles
    assert stream_roles == expected_roles
    assert retrieval_calls == [
        ("mat-current", False),
        ("mat-cited", False),
        ("mat-current", False),
        ("mat-cited", False),
    ]
    assert capture_calls == [
        ("project-roles", "session-role-post"),
        ("project-roles", "session-role-stream"),
    ]

    for session_id in ("session-role-post", "session-role-stream"):
        resumed = client.post(
            "/api/chat/resume",
            json={"session_id": session_id, "limit": 1},
        )
        assert resumed.status_code == 200
        resumed_roles = [
            ref["evidence_role"]
            for ref in resumed.json()["messages"][0]["evidence_refs"]
        ]
        assert resumed_roles == expected_roles
