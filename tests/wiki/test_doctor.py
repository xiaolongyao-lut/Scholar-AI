from __future__ import annotations

from pathlib import Path

from literature_assistant.core.project_paths import WORKSPACE_TESTS_ROOT
from literature_assistant.core.wiki.doctor import (
    DoctorStatus,
    WikiDoctor,
    find_duplicate_concept_candidates,
)
from literature_assistant.core.wiki.graph import WikiGraphStore, build_wiki_graph
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_wiki_index
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    derive_source_id,
    sha256_text,
    utc_now_iso,
)


def write_page(
    page_store: WikiPageStore,
    relative_path: str,
    *,
    title: str,
    kind: str = "concept",
    status: str = "draft",
    body: str = "Body.",
    extra_frontmatter: dict[str, object] | None = None,
) -> None:
    frontmatter: dict[str, object] = {
        "id": relative_path.removesuffix(".md"),
        "kind": kind,
        "title": title,
        "status": status,
    }
    frontmatter.update(extra_frontmatter or {})
    page_store.write_rendered(render_page(Path(relative_path), frontmatter, body))


def check_by_id(report, check_id: str):
    matches = [check for check in report.checks if check.id == check_id]
    assert len(matches) == 1
    return matches[0]


def test_doctor_empty_workspace_reports_missing_root(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.wiki_root.rmdir()

    report = WikiDoctor(page_store).run()
    workspace = check_by_id(report, "workspace")

    assert report.status == DoctorStatus.error
    assert workspace.status == DoctorStatus.error
    assert workspace.actions[0].safe_auto_repair is True


def test_doctor_retrieval_aligned_is_ok(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/a.md", title="A", body="Alpha text.")
    query_index = WikiQueryIndex(tmp_path / "wiki_query.db")
    build_wiki_index(page_store, query_index)

    report = WikiDoctor(page_store, query_index=query_index).run()
    retrieval = check_by_id(report, "retrieval")

    assert retrieval.status == DoctorStatus.ok
    assert retrieval.metrics["indexed_pages"] == 1


def test_doctor_retrieval_stale_warns(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/a.md", title="A", body="Alpha text.")
    query_index = WikiQueryIndex(tmp_path / "wiki_query.db")
    query_index.initialize()

    report = WikiDoctor(page_store, query_index=query_index).run()
    retrieval = check_by_id(report, "retrieval")

    assert retrieval.status == DoctorStatus.warning
    assert retrieval.actions[0].safe_auto_repair is True


def test_doctor_retrieval_warns_when_source_manifest_hash_changes(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_path = Path("concepts/a.md")
    write_page(page_store, page_path.as_posix(), title="A", body="Alpha text.")
    query_index = WikiQueryIndex(tmp_path / "wiki_query.db")
    build_wiki_index(page_store, query_index)
    write_page(page_store, page_path.as_posix(), title="A", body="Alpha text changed.")

    report = WikiDoctor(page_store, query_index=query_index).run()
    retrieval = check_by_id(report, "retrieval")

    assert retrieval.status == DoctorStatus.warning
    assert retrieval.metrics["integrity_status"] == "source_hash_mismatch"
    assert retrieval.metrics["source_manifest_hash"] != retrieval.metrics["indexed_source_manifest_hash"]
    assert retrieval.metrics["manifest_mismatched_count"] == 1
    assert retrieval.metrics["manifest_drilldown"]["mismatched_pages"][0]["page_path"] == "concepts/a.md"
    assert "source manifest hash differs" in retrieval.detail
    assert retrieval.actions[0].safe_auto_repair is True


def test_doctor_retrieval_reports_page_level_manifest_drilldown(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/a.md", title="A", body="Alpha text.")
    write_page(page_store, "concepts/b.md", title="B", body="Beta text.")
    query_index = WikiQueryIndex(tmp_path / "wiki_query.db")
    build_wiki_index(page_store, query_index)
    page_store.resolve(Path("concepts/b.md")).unlink()
    write_page(page_store, "concepts/c.md", title="C", body="Gamma text.")

    report = WikiDoctor(page_store, query_index=query_index).run()
    retrieval = check_by_id(report, "retrieval")

    assert retrieval.status == DoctorStatus.warning
    assert retrieval.metrics["manifest_missing_count"] == 1
    assert retrieval.metrics["manifest_extra_count"] == 1
    assert retrieval.metrics["manifest_drilldown"]["missing_pages"][0]["page_path"] == "concepts/c.md"
    assert retrieval.metrics["manifest_drilldown"]["extra_pages"][0]["page_path"] == "concepts/b.md"
    assert retrieval.metrics["manifest_drilldown"]["extra_pages"][0]["redacted"] is False


def test_doctor_graph_reports_broken_orphan_and_duplicate_candidates(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/alpha-model.md", title="Alpha Model", body="See [[missing/page]].")
    write_page(page_store, "concepts/alpha-models.md", title="Alpha Models", body="Standalone.")

    report = WikiDoctor(page_store).run()
    graph = check_by_id(report, "graph")

    assert graph.status == DoctorStatus.error
    assert graph.metrics["broken_link_count"] == 1
    assert graph.metrics["orphan_count"] == 1
    assert graph.metrics["duplicate_candidate_count"] == 1


def test_doctor_graph_smoke_fixture_reports_broken_orphan_and_duplicate_candidates() -> None:
    fixture_root = WORKSPACE_TESTS_ROOT / "fixtures" / "wiki_graph_doctor_smoke" / "pages"
    page_store = WikiPageStore(fixture_root)

    report = WikiDoctor(page_store).run()
    graph = check_by_id(report, "graph")

    assert graph.status in {DoctorStatus.error, DoctorStatus.warning}
    assert graph.metrics["broken_link_count"] == 1
    assert graph.metrics["orphan_count"] == 1
    assert graph.metrics["duplicate_candidate_count"] == 1


def test_find_duplicate_concept_candidates_is_conservative(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/context-window.md", title="Context Window")
    write_page(page_store, "concepts/context-windows.md", title="Context Windows")
    write_page(page_store, "concepts/beam-search.md", title="Beam Search")
    snapshot = build_wiki_graph(page_store)

    candidates = find_duplicate_concept_candidates(snapshot)

    assert len(candidates) == 1
    assert candidates[0][0:2] == ("concepts/context-window", "concepts/context-windows")
    assert candidates[0][2] >= 0.95


def test_doctor_citation_final_page_with_missing_citation_errors(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    registry = WikiRegistry(tmp_path / "wiki.db")
    source_hash = sha256_text("source text")
    source_id = derive_source_id("paper", "Paper A", source_hash)
    registry.upsert_source(
        SourceRecord(
            source_id=source_id,
            source_type="paper",
            title="Paper A",
            source_hash=source_hash,
            source_path=tmp_path / "paper.pdf",
        ),
        now_iso=utc_now_iso(),
    )
    write_page(
        page_store,
        "claims/claim-a.md",
        title="Claim A",
        kind="claim",
        status="final",
        body="This Claim lacks a citation.",
    )

    report = WikiDoctor(page_store, registry=registry).run()
    citation = check_by_id(report, "citation")

    assert citation.status == DoctorStatus.error
    assert citation.metrics["error_count"] == 1


def test_doctor_registry_reports_source_vault_mirror_backlog(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    source_text = "Legacy Source Vault mirror backlog text."
    source_path = tmp_path / "source.md"
    source_path.write_text(source_text, encoding="utf-8")
    source_hash = sha256_text(source_text)
    source_id = derive_source_id("local_markdown_import", "Backlog Source", source_hash)
    registry = WikiRegistry(tmp_path / "runtime" / "wiki.db", mirror_to_source_vault=False)
    registry.upsert_source(
        SourceRecord(
            source_id=source_id,
            source_type="local_markdown_import",
            title="Backlog Source",
            source_hash=source_hash,
            source_path=source_path,
        ),
        now_iso="2026-06-27T23:50:00+00:00",
    )
    registry.register_chunks(
        source_id,
        source_hash,
        [ChunkInput(text=source_text, chunk_index=0, section="diagnostics.md")],
        now_iso="2026-06-27T23:50:00+00:00",
    )
    write_page(
        page_store,
        "synthesis/backlog-source.md",
        title="Backlog Source",
        extra_frontmatter={"source_id": source_id},
    )

    report = WikiDoctor(page_store, registry=registry).run()
    registry_check = check_by_id(report, "registry")

    assert registry_check.status == DoctorStatus.warning
    assert "Source Vault mirror backlog" in registry_check.summary
    mirror_metrics = registry_check.metrics["source_vault_mirror"]
    assert mirror_metrics["needs_replay"] is True
    assert mirror_metrics["pending_source_count"] == 1
    assert mirror_metrics["pending_chunk_count"] == 1
    assert mirror_metrics["source_status_counts"] == {"not_mirrored": 1}
    assert mirror_metrics["chunk_status_counts"] == {"not_mirrored": 1}
    assert mirror_metrics["samples"][0]["record_type"] == "source"
    assert mirror_metrics["samples"][0]["source_id"] == source_id
    assert registry_check.actions[-1].safe_auto_repair is False
    assert registry_check.actions[-1].command == "WikiRegistry.replay_source_vault_mirror()"


def test_doctor_report_is_machine_readable(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/a.md", title="A")

    payload = WikiDoctor(page_store).run().to_dict()

    assert payload["status"] in {"ok", "warning", "error"}
    assert isinstance(payload["checks"], list)
    assert {"id", "label", "status", "summary", "detail", "metrics", "actions"} <= set(payload["checks"][0])


def test_doctor_repair_safe_subset_rebuilds_derived_artifacts_only(tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    write_page(page_store, "concepts/a.md", title="A", body="See [[concepts/b]].")
    write_page(page_store, "concepts/b.md", title="B")
    page_path = page_store.resolve(Path("concepts/a.md"))
    before = page_path.read_text(encoding="utf-8")
    registry = WikiRegistry(tmp_path / "runtime" / "wiki.db")
    query_index = WikiQueryIndex(tmp_path / "runtime" / "wiki_query.db")
    graph_json = tmp_path / "runtime" / "graph.json"
    graph_db = tmp_path / "runtime" / "graph.db"

    result = WikiDoctor(
        page_store,
        registry=registry,
        query_index=query_index,
        graph_store=WikiGraphStore(graph_json, graph_db),
    ).repair_safe_subset()

    assert "retrieval" in result.repaired
    assert "graph" in result.repaired
    assert graph_json.exists()
    assert graph_db.exists()
    assert page_path.read_text(encoding="utf-8") == before
