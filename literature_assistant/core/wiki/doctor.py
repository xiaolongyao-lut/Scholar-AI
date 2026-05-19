from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from literature_assistant.core.project_paths import (
    wiki_graph_db_path,
    wiki_graph_path,
    wiki_query_index_path,
    wiki_runtime_db_path,
)
from literature_assistant.core.wiki.citation_validator import ValidationMode, validate_page
from literature_assistant.core.wiki.graph import (
    WikiGraphSnapshot,
    WikiGraphStore,
    build_wiki_graph,
    node_id_from_path,
    parse_wiki_page,
)
from literature_assistant.core.wiki.observability import WikiObservabilitySink
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.query import WikiQueryIndex
from literature_assistant.core.wiki.source_registry import WikiRegistry


class DoctorStatus(str, Enum):
    ok = "ok"
    warning = "warning"
    error = "error"


@dataclass(frozen=True)
class DoctorAction:
    """Machine-readable remediation action for a doctor check."""

    command: str
    description: str
    safe_auto_repair: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "description": self.description,
            "safe_auto_repair": self.safe_auto_repair,
        }


@dataclass(frozen=True)
class DoctorCheck:
    """One health check result for API/UI/report consumers."""

    id: str
    label: str
    status: DoctorStatus
    summary: str
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    actions: tuple[DoctorAction, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status.value,
            "summary": self.summary,
            "detail": self.detail,
            "metrics": self.metrics,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class DoctorReport:
    """Complete wiki doctor report with stable severity semantics."""

    ok: bool
    status: DoctorStatus
    checks: tuple[DoctorCheck, ...]
    counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "counts": self.counts,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class RepairResult:
    """Result of the safe doctor repair subset."""

    repaired: tuple[str, ...]
    skipped: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repaired": list(self.repaired),
            "skipped": list(self.skipped),
        }


class WikiDoctor:
    """Run read-only wiki health checks for generated wiki artifacts."""

    def __init__(
        self,
        page_store: WikiPageStore | Path | str,
        db_path: Path | str | None = None,
        *,
        registry: WikiRegistry | None = None,
        query_index: WikiQueryIndex | None = None,
        graph_store: WikiGraphStore | None = None,
        observability_sink: WikiObservabilitySink | None = None,
    ) -> None:
        if isinstance(page_store, WikiPageStore):
            resolved_page_store = page_store
        elif isinstance(page_store, (Path, str)):
            resolved_page_store = WikiPageStore(Path(page_store), create=False)
        else:
            raise TypeError("page_store must be a WikiPageStore, Path, or string")
        if db_path is not None and registry is None:
            registry = WikiRegistry(Path(db_path))
        self.page_store = resolved_page_store
        self.registry = registry
        self.query_index = query_index
        self.graph_store = graph_store or WikiGraphStore.default()
        self.observability_sink = observability_sink

    def run(self) -> DoctorReport:
        span = self.observability_sink.start_span("wiki.doctor.run") if self.observability_sink is not None else None
        if span is not None:
            span.__enter__()
        span_error: BaseException | None = None
        try:
            graph_snapshot = _safe_build_graph(self.page_store)
            checks = (
                self.check_workspace(),
                self.check_registry(),
                self.check_retrieval(),
                self.check_citations(),
                self.check_graph(graph_snapshot),
                self.check_review(),
            )
            status = _worst_status(tuple(check.status for check in checks))
            report = DoctorReport(
                ok=status == DoctorStatus.ok,
                status=status,
                checks=checks,
                counts={
                    "ok": sum(1 for check in checks if check.status == DoctorStatus.ok),
                    "warning": sum(1 for check in checks if check.status == DoctorStatus.warning),
                    "error": sum(1 for check in checks if check.status == DoctorStatus.error),
                },
            )
            if self.observability_sink is not None:
                self.observability_sink.emit_event(
                    "wiki.doctor.completed",
                    {"status": report.status.value, "check_count": len(report.checks), "counts": report.counts},
                    status="error" if report.status == DoctorStatus.error else "ok",
                )
                self.observability_sink.record_metric("wiki.doctor.check_count", len(report.checks), unit="checks")
                self.observability_sink.record_metric("wiki.doctor.error_count", report.counts["error"], unit="checks")
            return report
        except Exception as exc:
            span_error = exc
            raise
        finally:
            if span is not None:
                if span_error is None:
                    span.__exit__(None, None, None)
                else:
                    span.__exit__(type(span_error), span_error, span_error.__traceback__)

    def repair_safe_subset(self) -> RepairResult:
        """Run only repairs that rebuild derived artifacts or create dirs."""

        repaired: list[str] = []
        skipped: list[str] = []
        if not self.page_store.wiki_root.exists():
            self.page_store.wiki_root.mkdir(parents=True, exist_ok=True)
            repaired.append("workspace")
        if self.registry is None:
            skipped.append("registry")
        else:
            self.registry.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self.registry.connect():
                pass
            repaired.append("registry")
        if self.query_index is None:
            skipped.append("retrieval")
        else:
            from literature_assistant.core.wiki.query import build_wiki_index

            build_wiki_index(self.page_store, self.query_index)
            repaired.append("retrieval")
        graph_snapshot = _safe_build_graph(self.page_store)
        if graph_snapshot is not None:
            self.graph_store.save(graph_snapshot)
            repaired.append("graph")
        else:
            skipped.append("graph")
        return RepairResult(repaired=tuple(repaired), skipped=tuple(skipped))

    def check_workspace(self) -> DoctorCheck:
        wiki_root = self.page_store.wiki_root
        pages = self.page_store.list_pages() if wiki_root.exists() else []
        missing_dirs = [path for path in (wiki_root,) if not path.exists()]
        if missing_dirs:
            return DoctorCheck(
                id="workspace",
                label="Workspace",
                status=DoctorStatus.error,
                summary="Wiki workspace is missing.",
                detail=", ".join(str(path) for path in missing_dirs),
                metrics={"page_count": 0},
                actions=(
                    DoctorAction(
                        command="wiki doctor --repair",
                        description="Create missing generated wiki directories.",
                        safe_auto_repair=True,
                    ),
                ),
            )
        return DoctorCheck(
            id="workspace",
            label="Workspace",
            status=DoctorStatus.ok,
            summary=f"Wiki workspace is present with {len(pages)} markdown pages.",
            metrics={"page_count": len(pages), "wiki_root": str(wiki_root)},
        )

    def check_registry(self) -> DoctorCheck:
        db_path = self.registry.db_path if self.registry is not None else wiki_runtime_db_path()
        if not db_path.exists():
            return DoctorCheck(
                id="registry",
                label="Source Registry",
                status=DoctorStatus.warning,
                summary="Wiki source registry database is missing.",
                metrics={"source_count": 0},
                actions=(
                    DoctorAction(
                        command="wiki doctor --repair",
                        description="Initialize source/chunk registry schema.",
                        safe_auto_repair=True,
                    ),
                ),
            )
        if self.registry is None:
            return DoctorCheck(
                id="registry",
                label="Source Registry",
                status=DoctorStatus.ok,
                summary="Wiki source registry database exists.",
                metrics={"db_path": str(db_path)},
            )
        sources = self.registry.list_sources()
        source_ids = {source.source_id for source in sources}
        page_source_ids = _source_ids_from_pages(self.page_store)
        orphan_sources = sorted(source_ids - page_source_ids)
        status = DoctorStatus.warning if orphan_sources else DoctorStatus.ok
        return DoctorCheck(
            id="registry",
            label="Source Registry",
            status=status,
            summary=(
                f"{len(sources)} registered sources; {len(orphan_sources)} sources have no generated wiki page."
                if orphan_sources
                else f"{len(sources)} registered sources are visible to the wiki doctor."
            ),
            detail=", ".join(orphan_sources[:10]),
            metrics={"source_count": len(sources), "orphan_source_count": len(orphan_sources)},
            actions=(
                DoctorAction(
                    command="wiki compile --dry-run",
                    description="Preview missing source pages before writing.",
                    safe_auto_repair=False,
                ),
            )
            if orphan_sources
            else tuple(),
        )

    def check_retrieval(self) -> DoctorCheck:
        db_path = self.query_index.db_path if self.query_index is not None else wiki_query_index_path()
        page_count = len(self.page_store.list_pages())
        if not db_path.exists():
            return DoctorCheck(
                id="retrieval",
                label="Retrieval",
                status=DoctorStatus.warning,
                summary="Wiki query index database is missing.",
                metrics={"indexed_pages": 0, "page_count": page_count},
                actions=(
                    DoctorAction(
                        command="wiki query-index rebuild",
                        description="Rebuild wiki FTS query index.",
                        safe_auto_repair=True,
                    ),
                ),
            )
        if self.query_index is None:
            return DoctorCheck(
                id="retrieval",
                label="Retrieval",
                status=DoctorStatus.ok,
                summary="Wiki query index database exists.",
                metrics={"db_path": str(db_path), "page_count": page_count},
            )
        status = self.query_index.get_status()
        stale = status.page_count != page_count
        return DoctorCheck(
            id="retrieval",
            label="Retrieval",
            status=DoctorStatus.warning if stale else DoctorStatus.ok,
            summary=(
                f"Wiki query index has {status.page_count} pages but page store has {page_count}."
                if stale
                else f"Wiki query index is aligned with {status.page_count} pages."
            ),
            metrics={
                "indexed_pages": status.page_count,
                "page_count": page_count,
                "index_hash": status.index_hash,
                "last_indexed": status.last_indexed,
            },
            actions=(
                DoctorAction(
                    command="wiki query-index rebuild",
                    description="Rebuild wiki FTS query index.",
                    safe_auto_repair=True,
                ),
            )
            if stale
            else tuple(),
        )

    def check_citations(self) -> DoctorCheck:
        pages = self.page_store.list_pages()
        if self.registry is None:
            return DoctorCheck(
                id="citation",
                label="Citation",
                status=DoctorStatus.warning,
                summary="Citation validation skipped because no registry was provided.",
                metrics={"page_count": len(pages)},
            )
        broken: list[str] = []
        uncited_final: list[str] = []
        for page_path in pages:
            content = self.page_store.read_page(page_path)
            if not content:
                continue
            try:
                parsed = parse_wiki_page(content)
            except (json.JSONDecodeError, ValueError) as exc:
                broken.append(f"{page_path.as_posix()}: invalid frontmatter: {exc}")
                continue
            mode = ValidationMode.FINAL if parsed.frontmatter.get("status") == "final" else ValidationMode.DRAFT
            report = validate_page(parsed.body, parsed.frontmatter, self.registry, mode=mode)
            for issue in report.issues:
                target = f"{page_path.as_posix()}: {issue.message}"
                if issue.level.value == "failed":
                    broken.append(target)
                else:
                    uncited_final.append(target)
        status = DoctorStatus.error if broken else DoctorStatus.warning if uncited_final else DoctorStatus.ok
        return DoctorCheck(
            id="citation",
            label="Citation",
            status=status,
            summary=f"Citation scan found {len(broken)} errors and {len(uncited_final)} warnings.",
            detail="\n".join((broken + uncited_final)[:20]),
            metrics={"error_count": len(broken), "warning_count": len(uncited_final), "page_count": len(pages)},
            actions=(
                DoctorAction(
                    command="wiki review list --filter citation",
                    description="Review pages with broken or weak citations.",
                    safe_auto_repair=False,
                ),
            )
            if broken or uncited_final
            else tuple(),
        )

    def check_graph(self, snapshot: WikiGraphSnapshot | None = None) -> DoctorCheck:
        graph = snapshot or _safe_build_graph(self.page_store)
        json_exists = self.graph_store.json_path.exists() or wiki_graph_path().exists()
        sqlite_exists = self.graph_store.sqlite_path.exists() or wiki_graph_db_path().exists()
        if graph is None:
            return DoctorCheck(
                id="graph",
                label="Graph",
                status=DoctorStatus.error,
                summary="Wiki graph could not be built from pages.",
                actions=(
                    DoctorAction(
                        command="wiki graph rebuild",
                        description="Rebuild graph artifacts from wiki pages.",
                        safe_auto_repair=True,
                    ),
                ),
            )
        node_ids = {node.node_id for node in graph.nodes}
        broken_edges = sorted(
            f"{edge.source_id} -> {edge.target_id}"
            for edge in graph.edges
            if edge.target_id not in node_ids
        )
        inbound_counts: dict[str, int] = {node_id: 0 for node_id in node_ids}
        outbound_counts: dict[str, int] = {node_id: 0 for node_id in node_ids}
        for edge in graph.edges:
            if edge.target_id in inbound_counts:
                inbound_counts[edge.target_id] += 1
            if edge.source_id in outbound_counts:
                outbound_counts[edge.source_id] += 1
        orphans = sorted(
            node_id
            for node_id in node_ids
            if inbound_counts[node_id] == 0 and outbound_counts[node_id] == 0
        )
        duplicates = find_duplicate_concept_candidates(graph)
        status = (
            DoctorStatus.error
            if broken_edges
            else DoctorStatus.warning
            if orphans or duplicates or not (json_exists and sqlite_exists)
            else DoctorStatus.ok
        )
        detail_parts = []
        if broken_edges:
            detail_parts.append("broken=" + ", ".join(broken_edges[:10]))
        if orphans:
            detail_parts.append("orphans=" + ", ".join(orphans[:10]))
        if duplicates:
            detail_parts.append(
                "duplicates="
                + ", ".join(f"{left}/{right}:{score:.2f}" for left, right, score in duplicates[:10])
            )
        return DoctorCheck(
            id="graph",
            label="Graph",
            status=status,
            summary=(
                f"Graph has {len(graph.nodes)} nodes, {len(graph.edges)} edges, "
                f"{len(broken_edges)} broken links, {len(orphans)} orphans, {len(duplicates)} duplicate candidates."
            ),
            detail="\n".join(detail_parts),
            metrics={
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "broken_link_count": len(broken_edges),
                "orphan_count": len(orphans),
                "duplicate_candidate_count": len(duplicates),
                "graph_json_exists": json_exists,
                "graph_db_exists": sqlite_exists,
            },
            actions=(
                DoctorAction(
                    command="wiki graph rebuild",
                    description="Rebuild graph JSON/SQLite artifacts from pages.",
                    safe_auto_repair=True,
                ),
            )
            if broken_edges or not (json_exists and sqlite_exists)
            else tuple(),
        )

    def check_review(self) -> DoctorCheck:
        draft_pages = 0
        review_pages = 0
        final_pages = 0
        for page_path in self.page_store.list_pages():
            content = self.page_store.read_page(page_path)
            if not content:
                continue
            try:
                status = str(parse_wiki_page(content).frontmatter.get("status") or "draft")
            except (json.JSONDecodeError, ValueError):
                status = "draft"
            if status == "review":
                review_pages += 1
            elif status == "final":
                final_pages += 1
            else:
                draft_pages += 1
        needs_review = draft_pages + review_pages
        return DoctorCheck(
            id="review",
            label="Review",
            status=DoctorStatus.warning if needs_review else DoctorStatus.ok,
            summary=(
                f"{needs_review} pages are draft/review and need human governance."
                if needs_review
                else f"All {final_pages} pages are final."
            ),
            metrics={"draft_pages": draft_pages, "review_pages": review_pages, "final_pages": final_pages},
            actions=(
                DoctorAction(
                    command="wiki review list",
                    description="Inspect draft/review pages before approval.",
                    safe_auto_repair=False,
                ),
            )
            if needs_review
            else tuple(),
        )


def find_duplicate_concept_candidates(
    snapshot: WikiGraphSnapshot,
    *,
    ratio_threshold: float = 0.86,
) -> list[tuple[str, str, float]]:
    """Find near-duplicate concept pages by slug/title similarity only."""

    if not isinstance(snapshot, WikiGraphSnapshot):
        raise TypeError("snapshot must be a WikiGraphSnapshot")
    if ratio_threshold <= 0 or ratio_threshold > 1:
        raise ValueError("ratio_threshold must be in (0, 1]")
    concepts = [
        node
        for node in snapshot.nodes
        if node.kind in {"concept", "concepts"} or node.node_id.startswith("concepts/")
    ]
    candidates: list[tuple[str, str, float]] = []
    for left_index, left in enumerate(concepts):
        for right in concepts[left_index + 1 :]:
            left_key = _duplicate_key(left.title or left.node_id)
            right_key = _duplicate_key(right.title or right.node_id)
            ratio = difflib.SequenceMatcher(a=left_key, b=right_key).ratio()
            if ratio >= ratio_threshold:
                candidates.append((left.node_id, right.node_id, round(ratio, 4)))
    return sorted(candidates, key=lambda item: (-item[2], item[0], item[1]))


def _safe_build_graph(page_store: WikiPageStore) -> WikiGraphSnapshot | None:
    try:
        return build_wiki_graph(page_store)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _source_ids_from_pages(page_store: WikiPageStore) -> set[str]:
    source_ids: set[str] = set()
    for page_path in page_store.list_pages():
        content = page_store.read_page(page_path)
        if not content:
            continue
        try:
            frontmatter = parse_wiki_page(content).frontmatter
        except (json.JSONDecodeError, ValueError):
            continue
        for key in ("id", "source_id"):
            value = frontmatter.get(key)
            if isinstance(value, str) and value.strip():
                source_ids.add(value.strip())
        source_id_values = frontmatter.get("source_ids")
        if isinstance(source_id_values, Sequence) and not isinstance(source_id_values, (str, bytes)):
            for value in source_id_values:
                if isinstance(value, str) and value.strip():
                    source_ids.add(value.strip())
    return source_ids


def _worst_status(statuses: Sequence[DoctorStatus]) -> DoctorStatus:
    if any(status == DoctorStatus.error for status in statuses):
        return DoctorStatus.error
    if any(status == DoctorStatus.warning for status in statuses):
        return DoctorStatus.warning
    return DoctorStatus.ok


def _duplicate_key(value: str) -> str:
    lowered = value.lower()
    return "".join(char for char in lowered if char.isalnum())
