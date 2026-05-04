from __future__ import annotations

import argparse
import gc
import json
import math
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from literature_assistant.core.wiki.compiler import WikiCompiler
from literature_assistant.core.wiki.doctor import WikiDoctor
from literature_assistant.core.wiki.graph import WikiGraphStore
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.query import WikiQueryIndex, build_wiki_index
from literature_assistant.core.wiki.source_registry import ChunkInput, SourceRecord, WikiRegistry, utc_now_iso


DEFAULT_ITERATIONS = 5


@dataclass(frozen=True)
class BaselineSample:
    """One temp-workspace performance sample with no external model calls."""

    compile_ms: float
    index_ms: float
    query_ms: float
    doctor_ms: float
    total_ms: float
    created_pages: int
    updated_pages: int
    skipped_pages: int
    error_count: int
    query_hit_count: int
    doctor_check_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "compile_ms": self.compile_ms,
            "index_ms": self.index_ms,
            "query_ms": self.query_ms,
            "doctor_ms": self.doctor_ms,
            "total_ms": self.total_ms,
            "created_pages": self.created_pages,
            "updated_pages": self.updated_pages,
            "skipped_pages": self.skipped_pages,
            "error_count": self.error_count,
            "query_hit_count": self.query_hit_count,
            "doctor_check_count": self.doctor_check_count,
        }


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _require_positive_iterations(iterations: int) -> int:
    if not isinstance(iterations, int):
        raise TypeError("iterations must be an integer")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if iterations > 100:
        raise ValueError("iterations must be <= 100")
    return iterations


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    if percentile < 0.0 or percentile > 100.0:
        raise ValueError("percentile must be between 0 and 100")
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    rank = math.ceil((percentile / 100.0) * len(sorted_values)) - 1
    index = min(max(rank, 0), len(sorted_values) - 1)
    return round(sorted_values[index], 3)


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    return round(sum(values) / len(values), 3)


def _latency_summary(values: list[float]) -> dict[str, object]:
    if not values:
        raise ValueError("values cannot be empty")
    return {
        "samples": [round(value, 3) for value in values],
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": _mean(values),
        "p50": _percentile(values, 50.0),
        "p95": _percentile(values, 95.0),
        "p99": _percentile(values, 99.0),
    }


def _per_second(count: int, elapsed_ms: float) -> float:
    if count < 0:
        raise ValueError("count must be non-negative")
    if elapsed_ms < 0.0:
        raise ValueError("elapsed_ms must be non-negative")
    if count == 0:
        return 0.0
    if elapsed_ms == 0.0:
        return float(count)
    return round(count / (elapsed_ms / 1000.0), 3)


def _register_baseline_source(registry: WikiRegistry) -> SourceRecord:
    source = SourceRecord(
        source_id="src-baseline",
        source_type="paper",
        title="Wave 14 Baseline Paper",
        source_hash="baselinehash",
        source_path=Path("fixtures/baseline-paper.pdf"),
    )
    registry.upsert_source(source, now_iso=utc_now_iso())
    registry.register_chunks(
        source.source_id,
        source.source_hash,
        [
            ChunkInput(text="Wave 14 baseline chunk about citation quality and graph checks.", chunk_index=0),
            ChunkInput(text="Wave 14 baseline chunk about retrieval comparison and no-secret traces.", chunk_index=1),
        ],
        now_iso=utc_now_iso(),
    )
    return source


def _run_one_sample() -> BaselineSample:
    """Run one isolated zero-cost baseline sample in a temporary workspace."""

    total_started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="wiki-wave14-baseline-") as tmp_name:
        root = Path(tmp_name)
        registry = WikiRegistry(root / "runtime" / "wiki.db")
        page_store = WikiPageStore(root / "pages")
        _register_baseline_source(registry)
        compiler = WikiCompiler(registry, page_store)

        started = time.perf_counter()
        compile_result = compiler.compile_project()
        compile_ms = _elapsed_ms(started)

        query_index = WikiQueryIndex(root / "runtime" / "wiki_query.db")
        started = time.perf_counter()
        build_wiki_index(page_store, query_index)
        index_ms = _elapsed_ms(started)

        started = time.perf_counter()
        query_hits = query_index.search("baseline citation", limit=5)
        query_ms = _elapsed_ms(started)

        graph_store = WikiGraphStore(root / "runtime" / "wiki_graph.json", root / "runtime" / "wiki_graph.db")
        started = time.perf_counter()
        doctor = WikiDoctor(page_store, registry=registry, query_index=query_index, graph_store=graph_store).run()
        doctor_ms = _elapsed_ms(started)

        query_index.close()

        sample = BaselineSample(
            compile_ms=compile_ms,
            index_ms=index_ms,
            query_ms=query_ms,
            doctor_ms=doctor_ms,
            total_ms=_elapsed_ms(total_started),
            created_pages=compile_result.created,
            updated_pages=compile_result.updated,
            skipped_pages=compile_result.skipped,
            error_count=len(compile_result.errors),
            query_hit_count=len(query_hits),
            doctor_check_count=len(doctor.checks),
        )
        gc.collect()
        return sample


def _summarize_samples(samples: list[BaselineSample]) -> dict[str, object]:
    if not samples:
        raise ValueError("samples cannot be empty")
    compile_values = [sample.compile_ms for sample in samples]
    index_values = [sample.index_ms for sample in samples]
    query_values = [sample.query_ms for sample in samples]
    doctor_values = [sample.doctor_ms for sample in samples]
    total_values = [sample.total_ms for sample in samples]
    total_created = sum(sample.created_pages for sample in samples)
    total_queries = len(samples)
    total_doctor_checks = sum(sample.doctor_check_count for sample in samples)
    total_compile_ms = sum(compile_values)
    total_query_ms = sum(query_values)
    total_doctor_ms = sum(doctor_values)
    return {
        "latency_ms": {
            "compile": _latency_summary(compile_values),
            "index": _latency_summary(index_values),
            "query": _latency_summary(query_values),
            "doctor": _latency_summary(doctor_values),
            "total": _latency_summary(total_values),
        },
        "throughput_per_second": {
            "compile_pages": _per_second(total_created, total_compile_ms),
            "queries": _per_second(total_queries, total_query_ms),
            "doctor_checks": _per_second(total_doctor_checks, total_doctor_ms),
        },
    }


def run_wiki_wave14_performance_baseline(iterations: int = DEFAULT_ITERATIONS) -> dict[str, object]:
    """Run a zero-cost wiki compile/index/query/doctor timing baseline.

    The baseline uses temporary workspaces, deterministic source text, and the
    stub compiler path. It does not call models, mutate qrels, or write runtime
    artifacts outside temporary directories.
    """

    sample_count = _require_positive_iterations(iterations)
    samples = [_run_one_sample() for _ in range(sample_count)]
    first_sample = samples[0]
    summary = _summarize_samples(samples)
    compile_values = [sample.compile_ms for sample in samples]
    index_values = [sample.index_ms for sample in samples]
    query_values = [sample.query_ms for sample in samples]
    doctor_values = [sample.doctor_ms for sample in samples]
    payload: dict[str, object] = {
        "schema_version": 2,
        "mode": "zero_cost_temp_workspace",
        "iterations": sample_count,
        "samples": [sample.to_dict() for sample in samples],
        "created_pages": first_sample.created_pages,
        "updated_pages": first_sample.updated_pages,
        "skipped_pages": first_sample.skipped_pages,
        "error_count": sum(sample.error_count for sample in samples),
        "query_hit_count": first_sample.query_hit_count,
        "doctor_check_count": first_sample.doctor_check_count,
        "compile_ms": _percentile(compile_values, 50.0),
        "index_ms": _percentile(index_values, 50.0),
        "query_ms": _percentile(query_values, 50.0),
        "doctor_ms": _percentile(doctor_values, 50.0),
        **summary,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the zero-cost Wave 14 performance baseline."""

    parser = argparse.ArgumentParser(description="Run the zero-cost LLM-Wiki Wave 14 performance baseline.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of isolated temp-workspace samples to run (default: {DEFAULT_ITERATIONS}).",
    )
    args = parser.parse_args(argv)
    payload = run_wiki_wave14_performance_baseline(iterations=args.iterations)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
