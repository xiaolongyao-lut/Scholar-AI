"""Tests for evidence_pack (Slice B / DEC-003a/b / Hard Constraint #16)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence_pack import (
    DEFAULT_MAX_SNIPPET_CHARS,
    DEFAULT_TOP_K,
    EVIDENCE_PACK_VERSION,
    EvidencePack,
    EvidencePackError,
    EvidenceSnippet,
    build_evidence_pack,
    dump_evidence_pack,
)


def _chunk(
    *,
    chunk_id: str,
    content: str,
    score: float = 0.5,
    title: str = "Doc",
    material_id: str = "m1",
    section: str = "intro",
    labels: list[str] | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "content": content,
        "score": score,
        "title": title,
        "material_id": material_id,
        "section_path": section,
        "source_labels": labels or ["hybrid"],
    }


def _stub_retriever(chunks: list[dict]):
    captured = {"calls": 0, "args": None}

    def fn(project_id: str, query: str, top_k: int) -> list[dict]:
        captured["calls"] += 1
        captured["args"] = (project_id, query, top_k)
        return chunks

    return fn, captured


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("project_id", ["", "   ", None])
def test_rejects_empty_project_id(project_id) -> None:
    with pytest.raises(EvidencePackError, match="project_id"):
        build_evidence_pack(project_id, "q", retriever=lambda *a: [])


@pytest.mark.parametrize("query", ["", "   ", None])
def test_rejects_empty_query(query) -> None:
    with pytest.raises(EvidencePackError, match="query"):
        build_evidence_pack("p1", query, retriever=lambda *a: [])


@pytest.mark.parametrize("top_k", [0, -1, 201, "five"])
def test_rejects_bad_top_k(top_k) -> None:
    with pytest.raises(EvidencePackError, match="top_k"):
        build_evidence_pack("p1", "q", top_k=top_k, retriever=lambda *a: [])


def test_rejects_bad_max_snippet_chars() -> None:
    with pytest.raises(EvidencePackError, match="max_snippet_chars"):
        build_evidence_pack(
            "p1", "q", max_snippet_chars=10, retriever=lambda *a: []
        )


def test_rejects_non_list_retriever_output() -> None:
    with pytest.raises(EvidencePackError, match="retriever"):
        build_evidence_pack("p1", "q", retriever=lambda *a: "not a list")


# ---------------------------------------------------------------------------
# Empty / no-LLM / no-cache contract
# ---------------------------------------------------------------------------


def test_empty_project_returns_empty_pack() -> None:
    fn, captured = _stub_retriever([])
    pack = build_evidence_pack("p1", "  what  is  X  ", retriever=fn)
    assert pack.snippets == ()
    assert pack.truncated is False
    assert pack.query == "what is X"
    assert pack.project_id == "p1"
    assert pack.top_k_requested == DEFAULT_TOP_K
    assert pack.pack_version == EVIDENCE_PACK_VERSION
    assert pack.diagnostic["raw_chunk_count"] == 0
    assert captured["calls"] == 1
    # Default top_k passed through unchanged
    assert captured["args"][2] == DEFAULT_TOP_K


def test_no_persistent_reuse_cache_each_call_runs_retriever() -> None:
    """Hard Constraint #16: every call must re-run retrieval."""
    chunks = [_chunk(chunk_id="c1", content="hello")]
    fn, captured = _stub_retriever(chunks)
    build_evidence_pack("p1", "q", retriever=fn)
    build_evidence_pack("p1", "q", retriever=fn)
    build_evidence_pack("p1", "q", retriever=fn)
    assert captured["calls"] == 3, "no in-process reuse cache allowed"


# ---------------------------------------------------------------------------
# Shape / ordering / truncation
# ---------------------------------------------------------------------------


def test_snippets_sorted_by_score_descending() -> None:
    chunks = [
        _chunk(chunk_id="low", content="low", score=0.1),
        _chunk(chunk_id="high", content="high", score=0.9),
        _chunk(chunk_id="mid", content="mid", score=0.5),
    ]
    pack = build_evidence_pack("p1", "q", retriever=lambda *a: chunks)
    assert [s.chunk_id for s in pack.snippets] == ["high", "mid", "low"]


def test_tie_break_uses_chunk_id_ascending() -> None:
    chunks = [
        _chunk(chunk_id="b", content="b", score=0.5),
        _chunk(chunk_id="a", content="a", score=0.5),
        _chunk(chunk_id="c", content="c", score=0.5),
    ]
    pack = build_evidence_pack("p1", "q", retriever=lambda *a: chunks)
    assert [s.chunk_id for s in pack.snippets] == ["a", "b", "c"]


def test_top_k_caps_returned_snippets() -> None:
    chunks = [
        _chunk(chunk_id=f"c{i}", content=f"c{i}", score=1.0 - i * 0.01)
        for i in range(20)
    ]
    pack = build_evidence_pack("p1", "q", top_k=5, retriever=lambda *a: chunks)
    assert len(pack.snippets) == 5
    assert pack.truncated is True


def test_oversize_snippet_is_truncated_with_marker() -> None:
    big = "x" * 5000
    chunks = [_chunk(chunk_id="c1", content=big)]
    pack = build_evidence_pack(
        "p1", "q", max_snippet_chars=100, retriever=lambda *a: chunks
    )
    s = pack.snippets[0]
    assert s.content.endswith("…")
    assert len(s.content) <= 101  # 100 chars + ellipsis
    assert pack.truncated is True


def test_chunks_with_empty_content_are_dropped() -> None:
    chunks = [
        _chunk(chunk_id="c1", content="kept"),
        _chunk(chunk_id="c2", content="   "),
        _chunk(chunk_id="c3", content=""),
    ]
    pack = build_evidence_pack("p1", "q", retriever=lambda *a: chunks)
    assert [s.chunk_id for s in pack.snippets] == ["c1"]
    assert pack.diagnostic["kept_chunk_count"] == 1


def test_non_dict_chunks_are_skipped() -> None:
    chunks = [_chunk(chunk_id="c1", content="ok"), "not a dict", None, 42]
    pack = build_evidence_pack("p1", "q", retriever=lambda *a: chunks)
    assert [s.chunk_id for s in pack.snippets] == ["c1"]


def test_anonymous_chunk_id_is_stable_per_index() -> None:
    chunks = [
        {"content": "alpha", "score": 0.9},
        {"content": "beta", "score": 0.8},
    ]
    pack = build_evidence_pack("p1", "q", retriever=lambda *a: chunks)
    ids = sorted(s.chunk_id for s in pack.snippets)
    assert ids == ["anonymous_0", "anonymous_1"]


# ---------------------------------------------------------------------------
# Versioning + replay identity
# ---------------------------------------------------------------------------


def test_same_inputs_yield_same_pack_id() -> None:
    chunks = [
        _chunk(chunk_id="a", content="alpha", score=0.5),
        _chunk(chunk_id="b", content="beta", score=0.4),
    ]
    p1 = build_evidence_pack("proj", "x", retriever=lambda *a: chunks)
    p2 = build_evidence_pack("proj", "x", retriever=lambda *a: chunks)
    assert p1.pack_id == p2.pack_id
    assert p1.pack_version == EVIDENCE_PACK_VERSION


def test_different_query_produces_different_pack_id() -> None:
    chunks = [_chunk(chunk_id="a", content="alpha")]
    p1 = build_evidence_pack("proj", "x", retriever=lambda *a: chunks)
    p2 = build_evidence_pack("proj", "y", retriever=lambda *a: chunks)
    assert p1.pack_id != p2.pack_id


def test_different_content_produces_different_pack_id() -> None:
    p1 = build_evidence_pack(
        "proj", "x",
        retriever=lambda *a: [_chunk(chunk_id="a", content="alpha")],
    )
    p2 = build_evidence_pack(
        "proj", "x",
        retriever=lambda *a: [_chunk(chunk_id="a", content="bravo")],
    )
    assert p1.pack_id != p2.pack_id


def test_pack_id_length_is_16_hex() -> None:
    p = build_evidence_pack(
        "proj", "x",
        retriever=lambda *a: [_chunk(chunk_id="a", content="alpha")],
    )
    assert len(p.pack_id) == 16
    int(p.pack_id, 16)  # parses as hex


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_as_dict_contains_full_serializable_shape() -> None:
    chunks = [_chunk(chunk_id="a", content="alpha", labels=["hybrid", "rerank"])]
    pack = build_evidence_pack("proj", "x", retriever=lambda *a: chunks)
    d = pack.as_dict()
    json.dumps(d)  # must round-trip
    assert d["pack_version"] == EVIDENCE_PACK_VERSION
    assert d["snippets"][0]["source_labels"] == ["hybrid", "rerank"]
    assert d["diagnostic"]["raw_chunk_count"] == 1


def test_to_prompt_block_renders_numbered_evidence() -> None:
    chunks = [
        _chunk(chunk_id="a", content="alpha", score=0.9),
        _chunk(chunk_id="b", content="beta", score=0.5),
    ]
    pack = build_evidence_pack("proj", "x", retriever=lambda *a: chunks)
    block = pack.to_prompt_block()
    assert block.startswith("[1] ")
    assert "alpha" in block
    assert "[2] " in block
    assert "beta" in block


def test_to_prompt_block_handles_empty_pack() -> None:
    pack = build_evidence_pack("proj", "x", retriever=lambda *a: [])
    assert pack.to_prompt_block() == "(no project evidence)"


# ---------------------------------------------------------------------------
# Dump artifact (debug only — not a reuse cache)
# ---------------------------------------------------------------------------


def test_dump_writes_pack_to_path(tmp_path: Path) -> None:
    chunks = [_chunk(chunk_id="a", content="alpha")]
    pack = build_evidence_pack("proj", "x", retriever=lambda *a: chunks)
    dest = tmp_path / "out.json"
    written = dump_evidence_pack(pack, dest=dest)
    assert written == dest
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["pack_id"] == pack.pack_id
    assert loaded["snippets"][0]["content"] == "alpha"


def test_dump_does_not_make_build_pack_a_cache(tmp_path: Path) -> None:
    """Even after dumping, build_evidence_pack must not read from disk."""
    chunks = [_chunk(chunk_id="a", content="alpha")]
    fn, captured = _stub_retriever(chunks)
    p1 = build_evidence_pack("proj", "x", retriever=fn)
    dump_evidence_pack(p1, dest=tmp_path / "p1.json")
    p2 = build_evidence_pack("proj", "x", retriever=fn)
    assert captured["calls"] == 2  # both calls hit the retriever
    assert p1.pack_id == p2.pack_id  # but pack_id is still deterministic


# ---------------------------------------------------------------------------
# Default retriever wiring
# ---------------------------------------------------------------------------


def test_default_retriever_calls_resources_router(monkeypatch) -> None:
    """When no retriever passed, build_evidence_pack must use the project chunk
    retriever from resources_router."""
    captured = {}

    def fake_search(*, project_id: str, query: str, top_k: int) -> list[dict]:
        captured["project_id"] = project_id
        captured["query"] = query
        captured["top_k"] = top_k
        return [_chunk(chunk_id="from-default", content="hi")]

    monkeypatch.setattr(
        "routers.resources_router.search_project_chunks_for_query",
        fake_search,
    )
    pack = build_evidence_pack("p1", "what")
    assert pack.snippets[0].chunk_id == "from-default"
    assert captured == {"project_id": "p1", "query": "what", "top_k": DEFAULT_TOP_K}
