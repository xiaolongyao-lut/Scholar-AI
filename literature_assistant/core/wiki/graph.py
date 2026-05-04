from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from literature_assistant.core.project_paths import wiki_graph_db_path, wiki_graph_path
from literature_assistant.core.wiki.page_store import WikiPageStore, atomic_write_text


_WIKILINK_RE = re.compile(r"\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]")
_FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


class WikiGraphEdgeType(str, Enum):
    """Conservative typed edge ontology for wiki graph operations."""

    wikilink = "wikilink"
    related_to = "related_to"
    derived_from = "derived_from"
    supports = "supports"
    contradicts = "contradicts"
    depends_on = "depends_on"
    extends = "extends"
    cites = "cites"
    introduces_concept = "introduces_concept"
    uses_concept = "uses_concept"
    extends_concept = "extends_concept"
    critiques_concept = "critiques_concept"
    same_problem_as = "same_problem_as"
    similar_method_to = "similar_method_to"
    complementary_to = "complementary_to"
    builds_on = "builds_on"
    compares_against = "compares_against"
    improves_on = "improves_on"
    challenges = "challenges"
    surveys = "surveys"


_EDGE_WEIGHTS: dict[WikiGraphEdgeType, float] = {
    WikiGraphEdgeType.supports: 0.9,
    WikiGraphEdgeType.contradicts: 0.9,
    WikiGraphEdgeType.improves_on: 0.85,
    WikiGraphEdgeType.challenges: 0.85,
    WikiGraphEdgeType.derived_from: 0.8,
    WikiGraphEdgeType.builds_on: 0.8,
    WikiGraphEdgeType.compares_against: 0.75,
    WikiGraphEdgeType.depends_on: 0.75,
    WikiGraphEdgeType.extends: 0.7,
    WikiGraphEdgeType.extends_concept: 0.7,
    WikiGraphEdgeType.introduces_concept: 0.65,
    WikiGraphEdgeType.uses_concept: 0.6,
    WikiGraphEdgeType.critiques_concept: 0.65,
    WikiGraphEdgeType.same_problem_as: 0.65,
    WikiGraphEdgeType.similar_method_to: 0.65,
    WikiGraphEdgeType.complementary_to: 0.6,
    WikiGraphEdgeType.surveys: 0.6,
    WikiGraphEdgeType.cites: 0.55,
    WikiGraphEdgeType.wikilink: 0.5,
    WikiGraphEdgeType.related_to: 0.5,
}

_FRONTMATTER_EDGE_FIELDS: dict[str, WikiGraphEdgeType] = {
    "related": WikiGraphEdgeType.related_to,
    "related_to": WikiGraphEdgeType.related_to,
    "related_pages": WikiGraphEdgeType.related_to,
    "links": WikiGraphEdgeType.related_to,
    "concepts": WikiGraphEdgeType.related_to,
    "claims": WikiGraphEdgeType.related_to,
    "sources": WikiGraphEdgeType.derived_from,
    "source_pages": WikiGraphEdgeType.derived_from,
    "source_ids": WikiGraphEdgeType.derived_from,
    "source_papers": WikiGraphEdgeType.derived_from,
    "key_papers": WikiGraphEdgeType.related_to,
    "derived_from": WikiGraphEdgeType.derived_from,
    "depends_on": WikiGraphEdgeType.depends_on,
    "supports": WikiGraphEdgeType.supports,
    "contradicts": WikiGraphEdgeType.contradicts,
    "extends": WikiGraphEdgeType.extends,
    "cites": WikiGraphEdgeType.cites,
}


@dataclass(frozen=True)
class WikiLink:
    """Parsed wiki link target from markdown body text."""

    target: str
    display: str | None
    start: int
    end: int


@dataclass(frozen=True)
class ParsedWikiPage:
    """Markdown page split into JSON frontmatter and body."""

    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class WikiGraphNode:
    """A wiki page node with stable path-based identity."""

    node_id: str
    page_path: str
    kind: str
    title: str
    status: str
    content_hash: str
    frontmatter_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "page_path": self.page_path,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "content_hash": self.content_hash,
            "frontmatter_id": self.frontmatter_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WikiGraphNode":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        return cls(
            node_id=_require_text(payload.get("node_id"), "node_id"),
            page_path=_require_text(payload.get("page_path"), "page_path"),
            kind=str(payload.get("kind") or "unknown"),
            title=str(payload.get("title") or "Untitled"),
            status=str(payload.get("status") or "draft"),
            content_hash=_require_text(payload.get("content_hash"), "content_hash"),
            frontmatter_id=str(payload["frontmatter_id"]) if payload.get("frontmatter_id") else None,
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WikiGraphEdge:
    """A typed directed relationship between wiki graph nodes."""

    edge_id: str
    source_id: str
    target_id: str
    edge_type: WikiGraphEdgeType
    weight: float
    confidence: str
    evidence: str
    source_path: str
    target_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "weight": self.weight,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WikiGraphEdge":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        edge_type = WikiGraphEdgeType(str(payload.get("edge_type") or WikiGraphEdgeType.related_to.value))
        return cls(
            edge_id=_require_text(payload.get("edge_id"), "edge_id"),
            source_id=_require_text(payload.get("source_id"), "source_id"),
            target_id=_require_text(payload.get("target_id"), "target_id"),
            edge_type=edge_type,
            weight=float(payload.get("weight") or _EDGE_WEIGHTS[edge_type]),
            confidence=str(payload.get("confidence") or "medium"),
            evidence=str(payload.get("evidence") or ""),
            source_path=_require_text(payload.get("source_path"), "source_path"),
            target_path=str(payload["target_path"]) if payload.get("target_path") else None,
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WikiBacklinks:
    """Inbound and outbound graph edges for a page."""

    node_id: str
    inbound: tuple[WikiGraphEdge, ...]
    outbound: tuple[WikiGraphEdge, ...]


@dataclass(frozen=True)
class BlastRadiusItem:
    """A node reached by graph blast-radius traversal."""

    node_id: str
    title: str
    relevance: float
    distance: int
    edge_types: tuple[str, ...]
    path: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "relevance": self.relevance,
            "distance": self.distance,
            "edge_types": list(self.edge_types),
            "path": list(self.path),
        }


@dataclass(frozen=True)
class WikiGraphSnapshot:
    """Deterministic JSON-serialisable wiki graph snapshot."""

    nodes: tuple[WikiGraphNode, ...]
    edges: tuple[WikiGraphEdge, ...]
    updated_at: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        nodes = sorted(self.nodes, key=lambda node: node.node_id)
        edges = sorted(self.edges, key=lambda edge: edge.edge_id)
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in edges],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WikiGraphSnapshot":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        raw_nodes = payload.get("nodes") or []
        raw_edges = payload.get("edges") or []
        if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
            raise ValueError("nodes must be a sequence")
        if not isinstance(raw_edges, Sequence) or isinstance(raw_edges, (str, bytes)):
            raise ValueError("edges must be a sequence")
        return cls(
            nodes=tuple(WikiGraphNode.from_dict(node) for node in raw_nodes),
            edges=tuple(WikiGraphEdge.from_dict(edge) for edge in raw_edges),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
            schema_version=int(payload.get("schema_version") or 1),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_wiki_page(content: str) -> ParsedWikiPage:
    """Parse JSON frontmatter without accepting YAML fallback."""

    if not isinstance(content, str):
        raise TypeError("content must be a string")
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---json":
        return ParsedWikiPage(frontmatter={}, body=content)
    frontmatter_lines: list[str] = []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            raw_frontmatter = "\n".join(frontmatter_lines).strip()
            if not raw_frontmatter:
                raise ValueError("frontmatter cannot be empty")
            payload = json.loads(raw_frontmatter)
            if not isinstance(payload, dict):
                raise ValueError("frontmatter must decode to an object")
            return ParsedWikiPage(frontmatter=payload, body="\n".join(lines[index + 1 :]))
        frontmatter_lines.append(line)
    raise ValueError("frontmatter terminator not found")


def strip_markdown_code(text: str) -> str:
    """Blank markdown code spans so link offsets remain stable."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    def blank(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    without_fences = _FENCED_CODE_RE.sub(blank, text)
    return _INLINE_CODE_RE.sub(blank, without_fences)


def extract_wikilinks(text: str) -> list[WikiLink]:
    """Extract wikilinks from markdown body while ignoring code regions."""

    cleaned = strip_markdown_code(text)
    links: list[WikiLink] = []
    for match in _WIKILINK_RE.finditer(cleaned):
        target = match.group(1).strip()
        if not target:
            continue
        display = match.group(2).strip() if match.group(2) else None
        links.append(WikiLink(target=target, display=display, start=match.start(), end=match.end()))
    return links


def node_id_from_path(relative_path: Path | str) -> str:
    """Return the path-based page id used by graph links."""

    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("relative_path must stay inside the wiki root")
    normalized = path.as_posix().strip("/")
    if not normalized:
        raise ValueError("relative_path cannot be empty")
    if normalized.lower().endswith(".md"):
        normalized = normalized[:-3]
    return normalized


def build_wiki_graph(page_store: WikiPageStore) -> WikiGraphSnapshot:
    """Build an in-memory graph snapshot from the current page store."""

    if not isinstance(page_store, WikiPageStore):
        raise TypeError("page_store must be a WikiPageStore")
    pages: dict[Path, ParsedWikiPage] = {}
    nodes: list[WikiGraphNode] = []
    for page_path in page_store.list_pages():
        content = page_store.read_page(page_path)
        if not content:
            continue
        parsed = parse_wiki_page(content)
        pages[page_path] = parsed
        node_id = node_id_from_path(page_path)
        nodes.append(_node_from_page(page_path, parsed, content))

    node_by_id = {node.node_id: node for node in nodes}
    node_by_basename = _unique_basename_index(node_by_id.keys())
    edges: dict[str, WikiGraphEdge] = {}
    for page_path, parsed in sorted(pages.items(), key=lambda item: item[0].as_posix()):
        source_id = node_id_from_path(page_path)
        for edge in _edges_from_body(page_path, parsed.body, source_id, node_by_id, node_by_basename):
            edges.setdefault(edge.edge_id, edge)
        for edge in _edges_from_frontmatter(page_path, parsed.frontmatter, source_id, node_by_id, node_by_basename):
            edges.setdefault(edge.edge_id, edge)

    return WikiGraphSnapshot(
        nodes=tuple(sorted(nodes, key=lambda node: node.node_id)),
        edges=tuple(sorted(edges.values(), key=lambda edge: edge.edge_id)),
        updated_at=utc_now_iso(),
    )


class WikiGraphStore:
    """Persist graph snapshots to JSON and SQLite for audit and querying."""

    def __init__(self, json_path: Path, sqlite_path: Path | None = None) -> None:
        self.json_path = Path(json_path)
        self.sqlite_path = Path(sqlite_path) if sqlite_path is not None else self.json_path.with_suffix(".db")

    @classmethod
    def default(cls) -> "WikiGraphStore":
        """Create a store using canonical workspace_artifacts runtime paths."""

        return cls(wiki_graph_path(), wiki_graph_db_path())

    def rebuild_from_page_store(self, page_store: WikiPageStore) -> WikiGraphSnapshot:
        snapshot = build_wiki_graph(page_store)
        self.save(snapshot)
        return snapshot

    def save(self, snapshot: WikiGraphSnapshot) -> None:
        if not isinstance(snapshot, WikiGraphSnapshot):
            raise TypeError("snapshot must be a WikiGraphSnapshot")
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        atomic_write_text(self.json_path, payload)
        self._write_sqlite(snapshot)

    def load(self) -> WikiGraphSnapshot:
        if not self.json_path.exists():
            raise FileNotFoundError(self.json_path)
        payload = json.loads(self.json_path.read_text(encoding="utf-8"))
        return WikiGraphSnapshot.from_dict(payload)

    def backlinks(self, node_id: str, snapshot: WikiGraphSnapshot | None = None) -> WikiBacklinks:
        normalized = _require_text(node_id, "node_id")
        graph = snapshot if snapshot is not None else self.load()
        inbound = tuple(edge for edge in graph.edges if edge.target_id == normalized)
        outbound = tuple(edge for edge in graph.edges if edge.source_id == normalized)
        return WikiBacklinks(
            node_id=normalized,
            inbound=tuple(sorted(inbound, key=lambda edge: edge.edge_id)),
            outbound=tuple(sorted(outbound, key=lambda edge: edge.edge_id)),
        )

    def blast_radius(
        self,
        seed_node_id: str,
        snapshot: WikiGraphSnapshot | None = None,
        *,
        max_depth: int = 2,
        min_relevance: float = 0.3,
        direction: str = "both",
    ) -> list[BlastRadiusItem]:
        graph = snapshot if snapshot is not None else self.load()
        return compute_blast_radius(
            graph,
            seed_node_id,
            max_depth=max_depth,
            min_relevance=min_relevance,
            direction=direction,
        )

    def _write_sqlite(self, snapshot: WikiGraphSnapshot) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.sqlite_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wiki_graph_nodes (
                    node_id TEXT PRIMARY KEY,
                    page_path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    frontmatter_id TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wiki_graph_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    weight REAL NOT NULL,
                    confidence TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    target_path TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wiki_graph_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_wiki_graph_edges_source ON wiki_graph_edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_wiki_graph_edges_target ON wiki_graph_edges(target_id);
                """
            )
            conn.execute("DELETE FROM wiki_graph_nodes")
            conn.execute("DELETE FROM wiki_graph_edges")
            conn.execute("DELETE FROM wiki_graph_metadata")
            conn.executemany(
                """
                INSERT INTO wiki_graph_nodes (
                    node_id, page_path, kind, title, status, content_hash,
                    frontmatter_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.node_id,
                        node.page_path,
                        node.kind,
                        node.title,
                        node.status,
                        node.content_hash,
                        node.frontmatter_id,
                        json.dumps(node.metadata, ensure_ascii=False, sort_keys=True),
                    )
                    for node in snapshot.nodes
                ],
            )
            conn.executemany(
                """
                INSERT INTO wiki_graph_edges (
                    edge_id, source_id, target_id, edge_type, weight, confidence,
                    evidence, source_path, target_path, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.edge_id,
                        edge.source_id,
                        edge.target_id,
                        edge.edge_type.value,
                        edge.weight,
                        edge.confidence,
                        edge.evidence,
                        edge.source_path,
                        edge.target_path,
                        json.dumps(edge.metadata, ensure_ascii=False, sort_keys=True),
                    )
                    for edge in snapshot.edges
                ],
            )
            conn.executemany(
                "INSERT INTO wiki_graph_metadata (key, value) VALUES (?, ?)",
                [
                    ("schema_version", str(snapshot.schema_version)),
                    ("updated_at", snapshot.updated_at),
                    ("node_count", str(len(snapshot.nodes))),
                    ("edge_count", str(len(snapshot.edges))),
                ],
            )
            conn.commit()


def compute_blast_radius(
    snapshot: WikiGraphSnapshot,
    seed_node_id: str,
    *,
    max_depth: int = 2,
    min_relevance: float = 0.3,
    direction: str = "both",
) -> list[BlastRadiusItem]:
    """Traverse graph with weighted BFS relevance decay."""

    if not isinstance(snapshot, WikiGraphSnapshot):
        raise TypeError("snapshot must be a WikiGraphSnapshot")
    seed = _require_text(seed_node_id, "seed_node_id")
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")
    if min_relevance < 0 or min_relevance > 1:
        raise ValueError("min_relevance must be between 0 and 1")
    if direction not in {"in", "out", "both"}:
        raise ValueError("direction must be 'in', 'out', or 'both'")

    node_by_id = {node.node_id: node for node in snapshot.nodes}
    if seed not in node_by_id:
        return []
    adjacency = _adjacency(snapshot.edges, direction)
    queue: deque[tuple[str, float, int, tuple[str, ...], tuple[str, ...]]] = deque()
    queue.append((seed, 1.0, 0, tuple(), (seed,)))
    best: dict[str, BlastRadiusItem] = {}

    while queue:
        node_id, relevance, distance, edge_types, path = queue.popleft()
        if distance > max_depth:
            continue
        if node_id != seed:
            prior = best.get(node_id)
            if prior is not None and prior.relevance >= relevance:
                continue
            node = node_by_id.get(node_id)
            best[node_id] = BlastRadiusItem(
                node_id=node_id,
                title=node.title if node else node_id,
                relevance=round(relevance, 4),
                distance=distance,
                edge_types=edge_types,
                path=path,
            )
        if distance == max_depth:
            continue
        for edge, next_node in adjacency.get(node_id, ()):
            if next_node in path:
                continue
            next_relevance = relevance * edge.weight
            if next_relevance < min_relevance:
                continue
            queue.append(
                (
                    next_node,
                    next_relevance,
                    distance + 1,
                    edge_types + (edge.edge_type.value,),
                    path + (next_node,),
                )
            )

    return sorted(best.values(), key=lambda item: (-item.relevance, item.distance, item.node_id))


def _node_from_page(page_path: Path, parsed: ParsedWikiPage, content: str) -> WikiGraphNode:
    node_id = node_id_from_path(page_path)
    frontmatter = parsed.frontmatter
    metadata = {
        "frontmatter_keys": sorted(str(key) for key in frontmatter.keys()),
    }
    return WikiGraphNode(
        node_id=node_id,
        page_path=page_path.as_posix(),
        kind=str(frontmatter.get("kind") or _kind_from_path(page_path)),
        title=str(frontmatter.get("title") or page_path.stem),
        status=str(frontmatter.get("status") or "draft"),
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        frontmatter_id=str(frontmatter["id"]) if frontmatter.get("id") else None,
        metadata=metadata,
    )


def _edges_from_body(
    page_path: Path,
    body: str,
    source_id: str,
    node_by_id: Mapping[str, WikiGraphNode],
    node_by_basename: Mapping[str, str],
) -> list[WikiGraphEdge]:
    edges: list[WikiGraphEdge] = []
    for link in extract_wikilinks(body):
        target_id = _resolve_link_target(link.target, page_path, node_by_id, node_by_basename)
        if target_id is None or target_id == source_id:
            continue
        edges.append(
            _make_edge(
                source_id=source_id,
                target_id=target_id,
                edge_type=WikiGraphEdgeType.wikilink,
                confidence="high",
                evidence=link.target,
                source_path=page_path.as_posix(),
                target_path=node_by_id.get(target_id).page_path if target_id in node_by_id else None,
                metadata={"display": link.display, "start": link.start, "end": link.end},
            )
        )
    return edges


def _edges_from_frontmatter(
    page_path: Path,
    frontmatter: Mapping[str, Any],
    source_id: str,
    node_by_id: Mapping[str, WikiGraphNode],
    node_by_basename: Mapping[str, str],
) -> list[WikiGraphEdge]:
    edges: list[WikiGraphEdge] = []
    for field_name, default_edge_type in _FRONTMATTER_EDGE_FIELDS.items():
        if field_name not in frontmatter:
            continue
        for raw_item in _iter_relation_items(frontmatter[field_name]):
            relation = _coerce_relation(raw_item, default_edge_type, field_name)
            if relation is None:
                continue
            target_id = _resolve_link_target(relation["target"], page_path, node_by_id, node_by_basename)
            if target_id is None or target_id == source_id:
                continue
            edge_type = relation["edge_type"]
            edges.append(
                _make_edge(
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=edge_type,
                    confidence=relation["confidence"],
                    evidence=relation["evidence"],
                    source_path=page_path.as_posix(),
                    target_path=node_by_id.get(target_id).page_path if target_id in node_by_id else None,
                    metadata={"frontmatter_field": field_name},
                )
            )
    return edges


def _coerce_relation(
    raw_item: Any,
    default_edge_type: WikiGraphEdgeType,
    field_name: str,
) -> dict[str, Any] | None:
    if isinstance(raw_item, Mapping):
        target = raw_item.get("target") or raw_item.get("to") or raw_item.get("id") or raw_item.get("page")
        if target is None:
            return None
        edge_type = _edge_type_from_value(raw_item.get("type"), default_edge_type)
        confidence = _confidence(str(raw_item.get("confidence") or "medium"))
        evidence = str(raw_item.get("evidence") or field_name)
        return {"target": str(target), "edge_type": edge_type, "confidence": confidence, "evidence": evidence}
    if isinstance(raw_item, str):
        target = raw_item.strip()
        if not target:
            return None
        links = extract_wikilinks(target)
        if links:
            target = links[0].target
        return {
            "target": target,
            "edge_type": default_edge_type,
            "confidence": "medium",
            "evidence": field_name,
        }
    return None


def _make_edge(
    *,
    source_id: str,
    target_id: str,
    edge_type: WikiGraphEdgeType,
    confidence: str,
    evidence: str,
    source_path: str,
    target_path: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> WikiGraphEdge:
    confidence_value = _confidence(confidence)
    edge_hash = hashlib.sha256(
        "\n".join([source_id, target_id, edge_type.value, confidence_value, evidence]).encode("utf-8")
    ).hexdigest()[:24]
    return WikiGraphEdge(
        edge_id=f"edge-{edge_hash}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        weight=_EDGE_WEIGHTS[edge_type],
        confidence=confidence_value,
        evidence=evidence,
        source_path=source_path,
        target_path=target_path,
        metadata=dict(metadata or {}),
    )


def _resolve_link_target(
    raw_target: str,
    source_path: Path,
    node_by_id: Mapping[str, WikiGraphNode],
    node_by_basename: Mapping[str, str],
) -> str | None:
    target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if not target:
        return None
    target_path = Path(target)
    if target_path.is_absolute() or ".." in target_path.parts:
        return None
    target_id = node_id_from_path(target_path)
    candidates = [target_id]
    if len(target_path.parts) == 1 and source_path.parent != Path("."):
        candidates.append(node_id_from_path(source_path.parent / target_path))
    basename_match = node_by_basename.get(target_id)
    if basename_match:
        candidates.append(basename_match)
    for candidate in candidates:
        if candidate in node_by_id:
            return candidate
    return target_id


def _iter_relation_items(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, Mapping)):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _edge_type_from_value(value: Any, default_edge_type: WikiGraphEdgeType) -> WikiGraphEdgeType:
    if value is None:
        return default_edge_type
    try:
        return WikiGraphEdgeType(str(value))
    except ValueError:
        return default_edge_type


def _confidence(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"high", "medium", "low"}:
        return "medium"
    return normalized


def _kind_from_path(page_path: Path) -> str:
    if len(page_path.parts) > 1:
        return page_path.parts[0].rstrip("s") or "unknown"
    return "unknown"


def _unique_basename_index(node_ids: Iterable[str]) -> dict[str, str]:
    buckets: dict[str, list[str]] = {}
    for node_id in node_ids:
        basename = node_id.rsplit("/", 1)[-1]
        buckets.setdefault(basename, []).append(node_id)
    return {basename: values[0] for basename, values in buckets.items() if len(values) == 1}


def _adjacency(
    edges: Iterable[WikiGraphEdge],
    direction: str,
) -> dict[str, tuple[tuple[WikiGraphEdge, str], ...]]:
    working: dict[str, list[tuple[WikiGraphEdge, str]]] = {}
    for edge in edges:
        if direction in {"out", "both"}:
            working.setdefault(edge.source_id, []).append((edge, edge.target_id))
        if direction in {"in", "both"}:
            working.setdefault(edge.target_id, []).append((edge, edge.source_id))
    return {key: tuple(sorted(value, key=lambda item: (item[1], item[0].edge_id))) for key, value in working.items()}


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized
