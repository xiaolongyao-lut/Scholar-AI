from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONTRACT_VERSION = "v2.graph-aware"


@dataclass
class ChunkRecord:
    chunk_id: str
    page: int
    text: str
    section_title: str = ""
    section_id: str = ""


@dataclass
class FigureRecord:
    figure_id: str
    page: int
    caption: str = ""
    bbox: list[float] = field(default_factory=list)


@dataclass
class RelationEdge:
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str = "semantic_link"
    confidence: float = 0.5


@dataclass
class EvidenceCluster:
    cluster_id: str
    anchor_type: str
    anchor_id: str
    support_strength: float
    member_edges: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BoundEvidenceContract:
    schema_version: str
    chunks: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    references: list[dict[str, Any]]
    relation_edges: list[dict[str, Any]]
    evidence_clusters: list[dict[str, Any]]


def make_bound_contract(bound: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_VERSION,
        "chunks": bound.get("chunks", []),
        "figures": bound.get("figures", []),
        "tables": bound.get("tables", []),
        "references": bound.get("references", []),
        "parameter_cards": bound.get("parameter_cards", []),
        "result_cards": bound.get("result_cards", []),
        "relation_edges": bound.get("relation_edges", []),
        "evidence_clusters": bound.get("evidence_clusters", []),
    }


def is_bound_contract_ready(bound: dict[str, Any]) -> bool:
    required_keys = [
        "chunks",
        "figures",
        "tables",
        "references",
        "relation_edges",
        "evidence_clusters",
    ]

import re
from collections import defaultdict

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
STOPWORDS = {
    'the','and','for','with','that','this','from','were','was','are','into','under','than','when',
    'where','while','been','their','which','different','using','used','results', 'figure','fig','table'
}

def tokenize(text: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(text or '') if t.lower() not in STOPWORDS}

def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)

def add_edge(edges: list[dict[str, Any]], seen: set[tuple], source_type: str, source_id: str, target_type: str, target_id: str, relation_type: str, score: float) -> None:
    key = (source_type, source_id, target_type, target_id, relation_type)
    if key in seen: return
    seen.add(key)
    edges.append({
        'source_type': source_type, 'source_id': source_id,
        'target_type': target_type, 'target_id': target_id,
        'relation_type': relation_type, 'score': round(float(score), 4),
    })

def bind_evidence(extract: dict[str, Any]) -> dict[str, Any]:
    """
    模块化证据绑定逻辑：建立文本块与图表、表格、文献之间的关联边。
    """
    chunks = extract.get('chunks', [])
    figures = extract.get('figures', [])
    tables = extract.get('tables', [])
    
    chunk_by_id = {c['chunk_id']: c for c in chunks}
    chunks_by_page = defaultdict(list)
    for c in chunks: chunks_by_page[int(c.get('page', 0))].append(c)
    
    figure_by_num = {int(f['figure_number']): f for f in figures if 'figure_number' in f}

    edges = []
    seen = set()

    # 1. 显式提及 (Explicit Mention)
    for chunk in chunks:
        for fig_num in chunk.get('mentioned_figures', []):
            fig = figure_by_num.get(int(fig_num))
            if fig:
                add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'figure', fig['figure_id'], 'explicit_mention', 1.0)

    # 2. 窗口邻近 (Window Proximity)
    for fig in figures:
        for chunk_id in fig.get('nearby_chunk_ids', []):
            if chunk_id in chunk_by_id:
                add_edge(edges, seen, 'chunk', chunk_id, 'figure', fig['figure_id'], 'nearby_window', 0.85)

    # 3. 语义重合 (Semantic Overlap)
    fig_tokens = {f['figure_id']: tokenize(f.get('caption', '')) for f in figures}
    for fig in figures:
        target_page = int(fig['page'])
        for page in {target_page - 1, target_page, target_page + 1}:
            for chunk in chunks_by_page.get(page, []):
                score = jaccard(fig_tokens[fig['figure_id']], tokenize(chunk.get('text', '')))
                if score >= 0.15:
                    add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'figure', fig['figure_id'], 'semantic_support', 0.5 + score)

    out = make_bound_contract(extract)
    out.update({
        'relation_edges': edges,
        'status': 'binding_ready'
    })
    return out
