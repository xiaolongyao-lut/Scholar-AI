from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from literature_assistant.core.project_paths import wiki_observability_path
from literature_assistant.core.wiki.observability import (
    WikiObservabilitySink,
    record_wiki_metric,
    sanitize_attributes,
    trace_wiki_operation,
    wiki_observability_enabled,
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_wiki_observability_writes_event_metric_and_span_jsonl(tmp_path: Path) -> None:
    sink = WikiObservabilitySink(tmp_path / "observability")

    event = sink.emit_event("wiki.query.started", {"source_id": "src-1", "hit_count": 2}, trace_id="trace-1")
    metric = sink.record_metric(
        "wiki.query.hits",
        2,
        {"source_id": "src-1"},
        unit="count",
        trace_id=event.trace_id,
    )
    with sink.start_span("wiki.query.search", {"source_id": "src-1"}, trace_id=event.trace_id) as span:
        span.set_attribute("result_count", 2)

    event_rows = _read_jsonl(sink.events_path)
    metric_rows = _read_jsonl(sink.metrics_path)
    span_rows = _read_jsonl(sink.spans_path)

    assert event_rows[0]["schema_version"] == 1
    assert event_rows[0]["kind"] == "event"
    assert event_rows[0]["name"] == "wiki.query.started"
    assert metric_rows[0]["kind"] == "metric"
    assert metric_rows[0]["value"] == metric.value
    assert metric_rows[0]["unit"] == "count"
    assert span_rows[0]["kind"] == "span"
    assert span_rows[0]["duration_ms"] >= 0
    assert span_rows[0]["trace_id"] == "trace-1"


def test_sensitive_attributes_are_redacted_before_jsonl_write(tmp_path: Path) -> None:
    sink = WikiObservabilitySink(tmp_path / "observability")
    private_path = r"C:\Users\xiao\secret-paper.pdf"
    raw_query = "exact private research question"
    api_key = "sk-test-secret-value-1234567890"

    sink.emit_event(
        "wiki.query.debug",
        {
            "query": raw_query,
            "source_path": private_path,
            "api_key": api_key,
            "safe_token": "concept-alpha",
        },
    )

    payload = sink.events_path.read_text(encoding="utf-8")
    row = _read_jsonl(sink.events_path)[0]

    assert raw_query not in payload
    assert private_path not in payload
    assert api_key not in payload
    assert row["attributes"]["safe_token"] == "concept-alpha"
    assert row["attributes"]["query"]["redacted"] is True
    assert row["attributes"]["source_path"]["reason"] == "sensitive_key"
    assert row["attributes"]["api_key"]["redacted"] is True


def test_sanitize_attributes_bounds_nested_and_unsupported_values() -> None:
    payload = sanitize_attributes(
        {
            "nested": {
                "query": "private query",
                "items": [Path("C:/Users/xiao/a.md"), "safe"],
            },
            "unsupported": object(),
        }
    )

    assert payload["nested"]["query"]["redacted"] is True
    assert payload["nested"]["items"][0]["redacted"] is True
    assert payload["nested"]["items"][1] == "safe"
    assert payload["unsupported"]["reason"] == "unsupported_type"


def test_span_records_error_without_swallowing_exception(tmp_path: Path) -> None:
    sink = WikiObservabilitySink(tmp_path / "observability")

    with pytest.raises(RuntimeError, match="boom"):
        with sink.start_span("wiki.doctor.run"):
            raise RuntimeError("boom")

    row = _read_jsonl(sink.spans_path)[0]
    assert row["status"] == "error"
    assert row["error_type"] == "RuntimeError"
    assert "boom" not in sink.spans_path.read_text(encoding="utf-8")


def test_observability_rejects_invalid_inputs(tmp_path: Path) -> None:
    sink = WikiObservabilitySink(tmp_path / "observability")

    with pytest.raises(ValueError, match="name"):
        sink.emit_event("")
    with pytest.raises(ValueError, match="finite"):
        sink.record_metric("wiki.metric", math.inf)
    with pytest.raises(TypeError, match="number"):
        sink.record_metric("wiki.metric", True)
    with pytest.raises(ValueError, match="status"):
        sink.emit_event("wiki.event", status="started")


def test_disabled_sink_does_not_write_jsonl(tmp_path: Path) -> None:
    sink = WikiObservabilitySink(tmp_path / "observability", enabled=False)

    sink.emit_event("wiki.disabled", {"source_id": "src-1"})
    sink.record_metric("wiki.disabled.count", 1)

    assert not sink.events_path.exists()
    assert not sink.metrics_path.exists()


def test_module_helpers_use_injected_sink(tmp_path: Path) -> None:
    sink = WikiObservabilitySink(tmp_path / "observability")

    record_wiki_metric("wiki.compiler.created", 3, {"source_id": "src-1"}, sink=sink, unit="pages")
    with trace_wiki_operation("wiki.compiler.project", {"source_id": "src-1"}, sink=sink):
        pass

    assert _read_jsonl(sink.metrics_path)[0]["unit"] == "pages"
    assert _read_jsonl(sink.spans_path)[0]["name"] == "wiki.compiler.project"


def test_default_observability_path_stays_under_wiki_runtime() -> None:
    path = wiki_observability_path()

    assert path.parts[-2:] == ("wiki", "observability")


def test_observability_env_switch() -> None:
    assert wiki_observability_enabled({"LITERATURE_ASSISTANT_WIKI_OBSERVABILITY": "0"}) is False
    assert wiki_observability_enabled({"LITERATURE_ASSISTANT_WIKI_OBSERVABILITY": "1"}) is True


def test_query_index_can_emit_sanitized_observability(tmp_path: Path) -> None:
    from literature_assistant.core.wiki.query import WikiQueryIndex

    sink = WikiObservabilitySink(tmp_path / "observability")
    index = WikiQueryIndex(tmp_path / "wiki_index.db", observability_sink=sink)
    index.initialize()
    index.index_page(Path("concepts/alpha.md"), "Alpha", "Alpha content about retrieval.")

    results = index.search("retrieval", limit=5)

    assert len(results) == 1
    assert "retrieval" not in sink.metrics_path.read_text(encoding="utf-8")
    assert _read_jsonl(sink.metrics_path)[0]["name"] == "wiki.query.index.hit_count"
    assert _read_jsonl(sink.spans_path)[0]["name"] == "wiki.query.index.search"


def test_compiler_can_emit_observability_without_writing_sensitive_source_path(tmp_path: Path) -> None:
    from literature_assistant.core.wiki.compiler import WikiCompiler
    from literature_assistant.core.wiki.page_store import WikiPageStore
    from literature_assistant.core.wiki.source_registry import ChunkInput, SourceRecord, WikiRegistry, utc_now_iso

    sink = WikiObservabilitySink(tmp_path / "observability")
    registry = WikiRegistry(tmp_path / "runtime" / "wiki.db")
    registry.upsert_source(
        SourceRecord(
            "src-private",
            "paper",
            "Private Compile Paper",
            "hash-private",
            Path(r"C:\Users\xiao\private-paper.pdf"),
        ),
        now_iso=utc_now_iso(),
    )
    registry.register_chunks(
        "src-private",
        "hash-private",
        [ChunkInput(text="compile chunk text", chunk_index=0)],
        now_iso=utc_now_iso(),
    )

    result = WikiCompiler(
        registry,
        WikiPageStore(tmp_path / "wiki"),
        observability_sink=sink,
    ).compile_source("src-private", dry_run=True)

    payload = sink.events_path.read_text(encoding="utf-8")
    assert result.created == 1
    assert r"C:\Users\xiao\private-paper.pdf" not in payload
    assert _read_jsonl(sink.events_path)[0]["name"] == "wiki.compiler.source.completed"


def test_doctor_can_emit_summary_observability(tmp_path: Path) -> None:
    from literature_assistant.core.wiki.doctor import WikiDoctor
    from literature_assistant.core.wiki.page_store import WikiPageStore, render_page

    sink = WikiObservabilitySink(tmp_path / "observability")
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body.",
        )
    )

    report = WikiDoctor(page_store, observability_sink=sink).run()

    assert len(report.checks) == 6
    assert _read_jsonl(sink.events_path)[0]["name"] == "wiki.doctor.completed"
    assert _read_jsonl(sink.metrics_path)[0]["name"] == "wiki.doctor.check_count"
    assert _read_jsonl(sink.spans_path)[0]["name"] == "wiki.doctor.run"
