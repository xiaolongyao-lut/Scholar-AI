"""LMWR-475: graph edge case and lifecycle tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from literature_assistant.core.wiki.export import export_graph_json, write_graph_json_export
from literature_assistant.core.wiki.graph import (
    WikiGraphEdgeType,
    WikiGraphSnapshot,
    WikiGraphStore,
    build_wiki_graph,
    compute_blast_radius,
    extract_wikilinks,
    node_id_from_path,
)
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page


@pytest.fixture
def page_store(tmp_path: Path) -> WikiPageStore:
    return WikiPageStore(tmp_path / "wiki")


def write_page(
    page_store: WikiPageStore,
    relative_path: str,
    *,
    title: str,
    kind: str = "concept",
    body: str = "Body.",
    extra_frontmatter: dict[str, object] | None = None,
) -> None:
    frontmatter: dict[str, object] = {
        "id": node_id_from_path(relative_path),
        "kind": kind,
        "title": title,
        "status": "draft",
    }
    frontmatter.update(extra_frontmatter or {})
    page_store.write_rendered(render_page(Path(relative_path), frontmatter, body))


# --- Edge CRUD ---


def test_supports_edge_from_frontmatter(page_store: WikiPageStore) -> None:
    write_page(page_store, "claims/a.md", title="A", kind="claim",
               extra_frontmatter={"supports": [{"target": "claims/b", "confidence": "high"}]})
    write_page(page_store, "claims/b.md", title="B", kind="claim")
    snap = build_wiki_graph(page_store)
    supports = [e for e in snap.edges if e.edge_type == WikiGraphEdgeType.supports]
    assert len(supports) == 1
    assert supports[0].target_id == "claims/b"


def test_contradicts_edge_from_frontmatter(page_store: WikiPageStore) -> None:
    write_page(page_store, "claims/a.md", title="A", kind="claim",
               extra_frontmatter={"contradicts": ["claims/b"]})
    write_page(page_store, "claims/b.md", title="B", kind="claim")
    snap = build_wiki_graph(page_store)
    contradicts = [e for e in snap.edges if e.edge_type == WikiGraphEdgeType.contradicts]
    assert len(contradicts) == 1


def test_depends_on_edge_from_frontmatter(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A",
               extra_frontmatter={"depends_on": ["concepts/b"]})
    write_page(page_store, "concepts/b.md", title="B")
    snap = build_wiki_graph(page_store)
    deps = [e for e in snap.edges if e.edge_type == WikiGraphEdgeType.depends_on]
    assert len(deps) == 1


def test_derived_from_edge_from_source_ids(page_store: WikiPageStore) -> None:
    write_page(page_store, "synthesis/s.md", title="S", kind="synthesis",
               extra_frontmatter={"source_ids": ["sources/src-a"]})
    write_page(page_store, "sources/src-a.md", title="SrcA", kind="source")
    snap = build_wiki_graph(page_store)
    derived = [e for e in snap.edges if e.edge_type == WikiGraphEdgeType.derived_from]
    assert len(derived) >= 1


def test_extends_edge_from_frontmatter(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A",
               extra_frontmatter={"extends": ["concepts/b"]})
    write_page(page_store, "concepts/b.md", title="B")
    snap = build_wiki_graph(page_store)
    extends = [e for e in snap.edges if e.edge_type == WikiGraphEdgeType.extends]
    assert len(extends) == 1


def test_wikilink_creates_edge(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    snap = build_wiki_graph(page_store)
    wikilinks = [e for e in snap.edges if e.edge_type == WikiGraphEdgeType.wikilink]
    assert len(wikilinks) == 1
    assert wikilinks[0].source_id == "concepts/a"
    assert wikilinks[0].target_id == "concepts/b"


def test_multiple_edges_between_same_nodes(page_store: WikiPageStore) -> None:
    write_page(page_store, "claims/a.md", title="A", kind="claim",
               extra_frontmatter={"supports": [{"target": "claims/b", "confidence": "high"}]},
               body="Also [[claims/b]].")
    write_page(page_store, "claims/b.md", title="B", kind="claim")
    snap = build_wiki_graph(page_store)
    a_to_b = [e for e in snap.edges if e.source_id == "claims/a" and e.target_id == "claims/b"]
    assert len(a_to_b) == 2
    types = {e.edge_type for e in a_to_b}
    assert WikiGraphEdgeType.supports in types
    assert WikiGraphEdgeType.wikilink in types


def test_node_id_from_path() -> None:
    assert node_id_from_path("concepts/alpha.md") == "concepts/alpha"
    assert node_id_from_path("sources/paper-x.md") == "sources/paper-x"


def test_empty_page_store_produces_empty_graph(page_store: WikiPageStore) -> None:
    snap = build_wiki_graph(page_store)
    assert len(snap.nodes) == 0
    assert len(snap.edges) == 0


# --- Persistence ---


def test_json_save_load_roundtrip(page_store: WikiPageStore, tmp_path: Path) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    json_path = tmp_path / "graph.json"
    sqlite_path = tmp_path / "graph.db"
    store = WikiGraphStore(json_path, sqlite_path)
    snap1 = store.rebuild_from_page_store(page_store)

    store.save_json(snap1)
    snap2 = store.load_json()
    assert snap2 is not None
    assert len(snap2.nodes) == len(snap1.nodes)
    assert len(snap2.edges) == len(snap1.edges)


def test_sqlite_save_load_roundtrip(page_store: WikiPageStore, tmp_path: Path) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    json_path = tmp_path / "graph.json"
    sqlite_path = tmp_path / "graph.db"
    store = WikiGraphStore(json_path, sqlite_path)
    snap1 = store.rebuild_from_page_store(page_store)

    store.save_sqlite(snap1)
    snap2 = store.load_sqlite()
    assert snap2 is not None
    assert {n.node_id for n in snap2.nodes} == {n.node_id for n in snap1.nodes}


def test_empty_graph_persists(page_store: WikiPageStore, tmp_path: Path) -> None:
    json_path = tmp_path / "graph.json"
    sqlite_path = tmp_path / "graph.db"
    store = WikiGraphStore(json_path, sqlite_path)
    snap = build_wiki_graph(page_store)
    store.save_json(snap)
    store.save_sqlite(snap)
    loaded = store.load_json()
    assert loaded is not None
    assert len(loaded.nodes) == 0


def test_larger_graph_persistence(page_store: WikiPageStore, tmp_path: Path) -> None:
    for i in range(30):
        write_page(page_store, f"concepts/c{i:03d}.md", title=f"Concept {i}")
    for i in range(29):
        write_page(page_store, f"concepts/c{i:03d}.md", title=f"Concept {i}",
                   body=f"Next: [[concepts/c{i+1:03d}]]")
    json_path = tmp_path / "graph.json"
    sqlite_path = tmp_path / "graph.db"
    store = WikiGraphStore(json_path, sqlite_path)
    snap = store.rebuild_from_page_store(page_store)
    assert len(snap.nodes) == 30
    store.save_json(snap)
    store.save_sqlite(snap)
    loaded = store.load_json()
    assert loaded is not None
    assert len(loaded.nodes) == 30


# --- Backlinks ---


def test_outbound_backlinks(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]] and [[concepts/c]].")
    write_page(page_store, "concepts/b.md", title="B")
    write_page(page_store, "concepts/c.md", title="C")
    snap = build_wiki_graph(page_store)
    store = WikiGraphStore(page_store.wiki_root / "graph.json", page_store.wiki_root / "graph.db")
    bl = store.backlinks("concepts/a", snap)
    assert len(bl.outbound) == 2


def test_inbound_backlinks_multi_source(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/target]].")
    write_page(page_store, "concepts/b.md", title="B", body="Also [[concepts/target]].")
    write_page(page_store, "concepts/target.md", title="Target")
    snap = build_wiki_graph(page_store)
    store = WikiGraphStore(page_store.wiki_root / "graph.json", page_store.wiki_root / "graph.db")
    bl = store.backlinks("concepts/target", snap)
    assert len(bl.inbound) == 2


def test_deep_backlinks(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="[[concepts/b]]")
    write_page(page_store, "concepts/b.md", title="B", body="[[concepts/c]]")
    write_page(page_store, "concepts/c.md", title="C", body="[[concepts/d]]")
    write_page(page_store, "concepts/d.md", title="D")
    snap = build_wiki_graph(page_store)
    store = WikiGraphStore(page_store.wiki_root / "graph.json", page_store.wiki_root / "graph.db")
    bl = store.backlinks("concepts/a", snap)
    assert len(bl.outbound) == 1
    bl_d = store.backlinks("concepts/d", snap)
    assert len(bl_d.inbound) == 1


def test_typed_backlinks(page_store: WikiPageStore) -> None:
    write_page(page_store, "claims/a.md", title="A", kind="claim",
               extra_frontmatter={"supports": [{"target": "claims/b", "confidence": "high"}]})
    write_page(page_store, "claims/b.md", title="B", kind="claim")
    snap = build_wiki_graph(page_store)
    store = WikiGraphStore(page_store.wiki_root / "graph.json", page_store.wiki_root / "graph.db")
    bl = store.backlinks("claims/b", snap)
    assert len(bl.inbound) == 1
    assert bl.inbound[0].edge_type == WikiGraphEdgeType.supports


def test_no_self_referencing_wikilink(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="Self [[concepts/a]].")
    snap = build_wiki_graph(page_store)
    self_edges = [e for e in snap.edges if e.source_id == e.target_id]
    assert len(self_edges) == 0


# --- Blast radius ---


def test_blast_radius_depth_1(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/root.md", title="Root", body="[[concepts/child1]] [[concepts/child2]]")
    write_page(page_store, "concepts/child1.md", title="C1")
    write_page(page_store, "concepts/child2.md", title="C2")
    snap = build_wiki_graph(page_store)
    results = compute_blast_radius(snap, "concepts/root", max_depth=1, direction="out")
    assert len(results) == 2


def test_blast_radius_depth_2(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/root.md", title="Root", body="[[concepts/c1]]")
    write_page(page_store, "concepts/c1.md", title="C1", body="[[concepts/c2]]")
    write_page(page_store, "concepts/c2.md", title="C2")
    snap = build_wiki_graph(page_store)
    results = compute_blast_radius(snap, "concepts/root", max_depth=2, direction="out")
    assert len(results) == 2


def test_blast_radius_isolated_node(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/isolated.md", title="Isolated")
    snap = build_wiki_graph(page_store)
    results = compute_blast_radius(snap, "concepts/isolated", max_depth=3, direction="out")
    assert len(results) == 0


def test_blast_radius_threshold(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/root.md", title="Root", body="[[concepts/c1]]")
    write_page(page_store, "concepts/c1.md", title="C1", body="[[concepts/c2]]")
    write_page(page_store, "concepts/c2.md", title="C2", body="[[concepts/c3]]")
    write_page(page_store, "concepts/c3.md", title="C3")
    snap = build_wiki_graph(page_store)
    results_strict = compute_blast_radius(snap, "concepts/root", max_depth=3, min_relevance=0.4, direction="out")
    results_loose = compute_blast_radius(snap, "concepts/root", max_depth=3, min_relevance=0.1, direction="out")
    assert len(results_strict) <= len(results_loose)


def test_blast_radius_direction_in(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="[[concepts/target]]")
    write_page(page_store, "concepts/b.md", title="B", body="[[concepts/target]]")
    write_page(page_store, "concepts/target.md", title="Target")
    snap = build_wiki_graph(page_store)
    results = compute_blast_radius(snap, "concepts/target", max_depth=1, direction="in")
    assert len(results) == 2


# --- Wikilink parser ---


def test_wikilink_simple_target() -> None:
    links = extract_wikilinks("See [[concepts/alpha]].")
    assert len(links) == 1
    assert links[0].target == "concepts/alpha"
    assert links[0].display is None


def test_wikilink_with_alias() -> None:
    links = extract_wikilinks("See [[concepts/alpha|Alpha Concept]].")
    assert len(links) == 1
    assert links[0].target == "concepts/alpha"
    assert links[0].display == "Alpha Concept"


def test_wikilink_ignores_fenced_code() -> None:
    body = "Visible [[a]].\n```\nHidden [[b]].\n```\nVisible2 [[c]]."
    links = extract_wikilinks(body)
    targets = [l.target for l in links]
    assert "a" in targets
    assert "c" in targets
    assert "b" not in targets


def test_wikilink_ignores_inline_code() -> None:
    body = "Visible [[a]]. Inline `[[b]]` ignored."
    links = extract_wikilinks(body)
    assert len(links) == 1
    assert links[0].target == "a"


def test_wikilink_multiple_links() -> None:
    body = "See [[a]] and [[b|B Label]] then [[c]]."
    links = extract_wikilinks(body)
    assert len(links) == 3


def test_wikilink_no_links() -> None:
    links = extract_wikilinks("No wikilinks here.")
    assert len(links) == 0


# --- Export ---


def test_export_empty_graph(page_store: WikiPageStore) -> None:
    snap = build_wiki_graph(page_store)
    exported = export_graph_json(snap)
    assert exported["node_count"] == 0
    assert exported["edge_count"] == 0


def test_export_does_not_modify_graph(page_store: WikiPageStore) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    snap = build_wiki_graph(page_store)
    node_count_before = len(snap.nodes)
    export_graph_json(snap)
    assert len(snap.nodes) == node_count_before


def test_export_file_roundtrip(page_store: WikiPageStore, tmp_path: Path) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    snap = build_wiki_graph(page_store)
    output_path = tmp_path / "export.json"
    write_graph_json_export(snap, output_path)
    reloaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert reloaded["node_count"] == 2
    assert reloaded["edge_count"] == 1
