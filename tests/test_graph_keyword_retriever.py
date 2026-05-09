from __future__ import annotations

from graph_keyword_retriever import build_keyword_graph, graph_keyword_search


def test_graph_keyword_retriever_can_recall_related_chunk() -> None:
    chunks = [
        {
            "chunk_id": "mat_a_chunk_0",
            "material_id": "mat_a",
            "content": "激光焊接 熔池 keyhole dynamics and stability",
            "title": "laser_welding.pdf",
        },
        {
            "chunk_id": "mat_b_chunk_0",
            "material_id": "mat_b",
            "content": "Ti-6Al-4V diffusion nitriding hardness wear resistance",
            "title": "man2011.pdf",
        },
    ]

    graph = build_keyword_graph(chunks)
    hits = graph_keyword_search(graph, chunks, query="熔池动力学分析", top_k=3)

    assert hits
    assert hits[0]["material_id"] == "mat_a"
    assert hits[0]["chunk_id"] == "mat_a_chunk_0"
    assert hits[0]["source_labels"] == ["graph"]
    assert hits[0]["source_hint"] == "graph"


def test_graph_keyword_retriever_returns_empty_for_empty_query() -> None:
    chunks = [
        {"chunk_id": "mat_a_chunk_0", "material_id": "mat_a", "content": "激光焊接 熔池"}
    ]
    graph = build_keyword_graph(chunks)

    assert graph_keyword_search(graph, chunks, query="", top_k=5) == []


def test_graph_keyword_retriever_matches_partial_chinese_query_via_bigrams() -> None:
    chunks = [
        {
            "chunk_id": "mat_c_chunk_0",
            "material_id": "mat_c",
            "content": "焊缝组织演变过程与热影响区性能",
            "title": "microstructure_evolution.pdf",
        },
        {
            "chunk_id": "mat_d_chunk_0",
            "material_id": "mat_d",
            "content": "表面粗糙度与残余应力分析",
            "title": "surface_state.pdf",
        },
    ]

    graph = build_keyword_graph(chunks)
    hits = graph_keyword_search(graph, chunks, query="组织演变规律", top_k=3)

    assert hits
    assert hits[0]["material_id"] == "mat_c"
    assert hits[0]["chunk_id"] == "mat_c_chunk_0"
