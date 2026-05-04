from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from literature_assistant.core.wiki.export import export_graph_json, write_graph_json_export
from literature_assistant.core.wiki.graph import (
    WikiGraphEdgeType,
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


def test_extract_wikilinks_ignores_code_regions() -> None:
    body = """
Visible [[concepts/real]].

```python
hidden = "[[concepts/code]]"
```

Inline `[[concepts/inline]]` remains ignored.
Alias [[concepts/alias|Alias Label]].
"""

    links = extract_wikilinks(body)

    assert [link.target for link in links] == ["concepts/real", "concepts/alias"]
    assert links[1].display == "Alias Label"


def test_build_graph_extracts_wikilink_and_backlinks(page_store: WikiPageStore) -> None:
    write_page(
        page_store,
        "concepts/alpha.md",
        title="Alpha",
        body="Alpha references [[beta]] and [[claims/claim-a]].",
    )
    write_page(page_store, "concepts/beta.md", title="Beta", body="Beta body.")
    write_page(page_store, "claims/claim-a.md", title="Claim A", kind="claim", body="Claim body.")

    snapshot = build_wiki_graph(page_store)
    store = WikiGraphStore(page_store.wiki_root / "graph.json", page_store.wiki_root / "graph.db")
    backlinks = store.backlinks("concepts/beta", snapshot)

    assert {node.node_id for node in snapshot.nodes} == {
        "claims/claim-a",
        "concepts/alpha",
        "concepts/beta",
    }
    assert len(backlinks.inbound) == 1
    assert backlinks.inbound[0].source_id == "concepts/alpha"
    assert backlinks.inbound[0].edge_type == WikiGraphEdgeType.wikilink


def test_frontmatter_relation_edges_are_typed(page_store: WikiPageStore) -> None:
    write_page(
        page_store,
        "claims/claim-a.md",
        title="Claim A",
        kind="claim",
        extra_frontmatter={
            "supports": [
                {
                    "target": "papers/paper-a",
                    "confidence": "high",
                    "evidence": "explicit claim support",
                }
            ],
            "contradicts": ["claims/claim-b"],
        },
    )
    write_page(page_store, "papers/paper-a.md", title="Paper A", kind="paper")
    write_page(page_store, "claims/claim-b.md", title="Claim B", kind="claim")

    snapshot = build_wiki_graph(page_store)
    typed = {(edge.target_id, edge.edge_type.value, edge.confidence) for edge in snapshot.edges}

    assert ("papers/paper-a", "supports", "high") in typed
    assert ("claims/claim-b", "contradicts", "medium") in typed


def test_graph_store_persists_json_and_sqlite(page_store: WikiPageStore, tmp_path: Path) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    json_path = tmp_path / "runtime" / "graph.json"
    sqlite_path = tmp_path / "runtime" / "graph.db"
    store = WikiGraphStore(json_path, sqlite_path)

    snapshot = store.rebuild_from_page_store(page_store)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["node_count"] == 2
    assert payload["edge_count"] == 1
    with sqlite3.connect(str(sqlite_path)) as conn:
        node_count = conn.execute("SELECT COUNT(*) FROM wiki_graph_nodes").fetchone()[0]
        edge_count = conn.execute("SELECT COUNT(*) FROM wiki_graph_edges").fetchone()[0]
    assert node_count == len(snapshot.nodes)
    assert edge_count == len(snapshot.edges)


def test_graph_store_default_uses_canonical_paths() -> None:
    store = WikiGraphStore.default()
    assert store.json_path.name == "graph.json"
    assert store.sqlite_path.name == "graph.db"


def test_blast_radius_uses_weighted_bfs(page_store: WikiPageStore) -> None:
    write_page(
        page_store,
        "claims/root.md",
        title="Root",
        kind="claim",
        extra_frontmatter={"supports": [{"target": "claims/child", "confidence": "high"}]},
    )
    write_page(
        page_store,
        "claims/child.md",
        title="Child",
        kind="claim",
        body="Child links [[concepts/grandchild]].",
    )
    write_page(page_store, "concepts/grandchild.md", title="Grandchild")
    snapshot = build_wiki_graph(page_store)

    results = compute_blast_radius(snapshot, "claims/root", max_depth=2, min_relevance=0.2, direction="out")

    assert [item.node_id for item in results] == ["claims/child", "concepts/grandchild"]
    assert results[0].relevance == 0.9
    assert results[1].relevance == 0.45
    assert results[1].edge_types == ("supports", "wikilink")


def test_graph_export_is_deterministic(page_store: WikiPageStore, tmp_path: Path) -> None:
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    snapshot = build_wiki_graph(page_store)
    output_path = tmp_path / "graph-export.json"

    exported = export_graph_json(snapshot)
    write_graph_json_export(snapshot, output_path)

    reloaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert exported["node_count"] == 2
    assert exported["edge_count"] == 1
    assert reloaded == exported
