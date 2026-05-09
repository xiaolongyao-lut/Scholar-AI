from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_REVIEW_DATE = "2026-05-05"
DEFAULT_OUTPUT_NAME = "lmwr-470-chunk-param-review-20260505.json"
METRIC_KEYS: tuple[str, ...] = (
    "recall_at_1",
    "recall_at_3",
    "recall_at_5",
    "recall_at_10",
    "mrr",
)


class ReviewInputError(ValueError):
    """Raised when a review input cannot support a safe LMWR-470 decision."""


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _read_json_object(path: Path) -> dict[str, Any]:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ReviewInputError(f"expected JSON file, got directory: {_repo_relative(path)}")
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ReviewInputError(f"expected top-level JSON object: {_repo_relative(path)}")
    return payload


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewInputError(f"{label} must be an object")
    return value


def _as_number(value: Any, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReviewInputError(f"{label} must be numeric")
    return float(value)


def _extract_metric_map(value: Any, *, label: str) -> dict[str, float]:
    source = _as_mapping(value, label=label)
    metrics: dict[str, float] = {}
    for key in METRIC_KEYS:
        if key not in source:
            raise ReviewInputError(f"{label}.{key} is required")
        metrics[key] = round(_as_number(source[key], label=f"{label}.{key}"), 4)
    return metrics


def extract_current_chunk_constants(resources_router_path: Path) -> dict[str, int]:
    """Read chunk constants from `resources_router.py` without importing runtime code.

    Args:
        resources_router_path: Existing Python source file containing module-level
            integer assignments for `CHUNK_SIZE`, `CHUNK_OVERLAP`, and
            `MAX_CHUNKS_PER_MATERIAL`.

    Returns:
        Mapping with the three required constants as positive integers.
    """

    if not isinstance(resources_router_path, Path):
        raise TypeError("resources_router_path must be a Path")
    if not resources_router_path.exists():
        raise FileNotFoundError(resources_router_path)
    source = resources_router_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(resources_router_path))
    wanted = {"CHUNK_SIZE", "CHUNK_OVERLAP", "MAX_CHUNKS_PER_MATERIAL"}
    constants: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, int):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                constants[target.id] = int(node.value.value)
    missing = sorted(wanted - constants.keys())
    if missing:
        raise ReviewInputError(f"missing chunk constants: {', '.join(missing)}")
    for name, value in constants.items():
        if value <= 0:
            raise ReviewInputError(f"{name} must be positive")
    return constants


def _run_metrics(run: Mapping[str, Any], *, label: str) -> dict[str, float]:
    metrics = _as_mapping(run.get("metrics"), label=f"{label}.metrics")
    return _extract_metric_map(metrics, label=f"{label}.metrics")


def _run_parameters(run: Mapping[str, Any], *, label: str) -> dict[str, int]:
    parameters = _as_mapping(run.get("parameters"), label=f"{label}.parameters")
    chunk_overlap = parameters.get("chunk_overlap")
    max_chunks = parameters.get("max_chunks_per_material")
    if not isinstance(chunk_overlap, int) or isinstance(chunk_overlap, bool) or chunk_overlap <= 0:
        raise ReviewInputError(f"{label}.parameters.chunk_overlap must be a positive integer")
    if not isinstance(max_chunks, int) or isinstance(max_chunks, bool) or max_chunks <= 0:
        raise ReviewInputError(f"{label}.parameters.max_chunks_per_material must be a positive integer")
    return {"chunk_overlap": chunk_overlap, "max_chunks_per_material": max_chunks}


def _metric_deltas(left: Mapping[str, float], right: Mapping[str, float]) -> dict[str, float]:
    return {key: round(float(right[key]) - float(left[key]), 4) for key in METRIC_KEYS}


def metrics_are_identical(left: Mapping[str, float], right: Mapping[str, float], *, tolerance: float = 0.0001) -> bool:
    """Return whether ranked retrieval metrics match within rounding tolerance."""

    if tolerance < 0.0:
        raise ValueError("tolerance must be non-negative")
    for key in METRIC_KEYS:
        if key not in left or key not in right:
            raise ReviewInputError(f"missing metric key: {key}")
        if abs(float(left[key]) - float(right[key])) > tolerance:
            return False
    return True


def _extract_target_corpus_chunk_count(*payloads: Mapping[str, Any]) -> int | None:
    pattern = re.compile(r"current corpus\s+(\d+)\s+chunks|corpus has\s+(\d+)\s+chunks|current\s+(\d+)", re.I)
    for payload in payloads:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for match in pattern.finditer(encoded):
            for group in match.groups():
                if group:
                    value = int(group)
                    if value > 0:
                        return value
    return None


def _extract_old_cache_counts(cache_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    analysis = _as_mapping(cache_payload.get("cache_manifest_analysis"), label="cache_manifest_analysis")
    old_cache_state = _as_mapping(analysis.get("old_cache_state"), label="cache_manifest_analysis.old_cache_state")
    counts: list[dict[str, Any]] = []
    for name, value in sorted(old_cache_state.items()):
        state = _as_mapping(value, label=f"old_cache_state.{name}")
        chunk_count = state.get("chunk_count")
        if not isinstance(chunk_count, int) or isinstance(chunk_count, bool) or chunk_count <= 0:
            raise ReviewInputError(f"old_cache_state.{name}.chunk_count must be a positive integer")
        counts.append(
            {
                "cache_name": str(name),
                "model": str(state.get("model") or ""),
                "chunk_count": chunk_count,
                "chunks_hash": str(state.get("chunks_hash") or ""),
                "embedding_shape": state.get("embedding_shape"),
                "is_contextual": bool(state.get("is_contextual")),
            }
        )
    if not counts:
        raise ReviewInputError("old cache chunk counts are required")
    return counts


def _cache_staleness_evidence(cache_payload: Mapping[str, Any], final_payload: Mapping[str, Any]) -> dict[str, Any]:
    old_counts = _extract_old_cache_counts(cache_payload)
    target_count = _extract_target_corpus_chunk_count(cache_payload, final_payload)
    stale_entries: list[dict[str, Any]] = []
    if target_count is not None:
        for item in old_counts:
            chunk_count = int(item["chunk_count"])
            stale_entries.append(
                {
                    **item,
                    "target_corpus_chunk_count": target_count,
                    "chunk_count_delta": target_count - chunk_count,
                    "status": "STALE" if chunk_count != target_count else "MATCH",
                }
            )
    return {
        "target_corpus_chunk_count": target_count,
        "old_cache_entries": stale_entries if stale_entries else old_counts,
        "has_stale_cache_evidence": any(item.get("status") == "STALE" for item in stale_entries),
    }


def build_lmwr470_review(
    *,
    resources_router_path: Path,
    chunk_params_analysis_path: Path,
    causality_path: Path,
    cache_rebuild_path: Path,
    final_evaluation_path: Path,
    backup_path: Path,
    review_date: str = DEFAULT_REVIEW_DATE,
) -> dict[str, Any]:
    """Build the deterministic LMWR-470 chunk-parameter review payload.

    The review is intentionally read-only. It uses historical canary artifacts
    to prevent a parameter promotion before cache/corpus causality is verified.
    """

    if not review_date or not isinstance(review_date, str):
        raise ValueError("review_date must be a non-empty string")
    current_constants = extract_current_chunk_constants(resources_router_path)
    analysis = _read_json_object(chunk_params_analysis_path)
    causality = _read_json_object(causality_path)
    cache_rebuild = _read_json_object(cache_rebuild_path)
    final_eval = _read_json_object(final_evaluation_path)
    runs = _as_mapping(causality.get("evaluation_runs"), label="evaluation_runs")
    regression_run = _as_mapping(runs.get("regression_run_200_8"), label="evaluation_runs.regression_run_200_8")
    revert_run = _as_mapping(runs.get("revert_run_150_5"), label="evaluation_runs.revert_run_150_5")
    regression_metrics = _run_metrics(regression_run, label="regression_run_200_8")
    revert_metrics = _run_metrics(revert_run, label="revert_run_150_5")
    aligned = _as_mapping(analysis.get("aligned_baseline_comparison"), label="aligned_baseline_comparison")
    aligned_metrics = _extract_metric_map(
        _as_mapping(aligned.get("baseline_metrics"), label="aligned_baseline_comparison.baseline_metrics"),
        label="aligned_baseline_comparison.baseline_metrics",
    )
    identical_param_metrics = metrics_are_identical(regression_metrics, revert_metrics)
    cache_evidence = _cache_staleness_evidence(cache_rebuild, final_eval)
    promote_200_8 = False
    requires_rebuild_verification = bool(
        identical_param_metrics and cache_evidence.get("has_stale_cache_evidence")
    )
    decision = {
        "status": "closed_for_now",
        "runtime_constants_change": "none",
        "qrels_goldset_canary30_change": "none",
        "promote_200_8": promote_200_8,
        "keep_current_defaults": True,
        "parameter_causality": "not_proven" if identical_param_metrics else "inconclusive",
        "primary_blocker": "post_cache_rebuild_retrieval_verification_missing",
        "next_gate": (
            "Rebuild/verify embedding cache against current corpus, then rerun aligned canary30 no-rerank control "
            "before any 200/8 promotion."
        ),
    }
    sources = [
        resources_router_path,
        chunk_params_analysis_path,
        causality_path,
        cache_rebuild_path,
        final_evaluation_path,
    ]
    return {
        "schema_version": 1,
        "task_id": "LMWR-470",
        "review_date": review_date,
        "mode": "read_only_existing_artifacts",
        "artifact_sources": [
            {
                "path": _repo_relative(source),
                "sha256": _sha256_file(source),
            }
            for source in sources
        ],
        "backup": {
            "path": _repo_relative(backup_path),
            "exists": backup_path.exists(),
            "purpose": "Snapshot of evaluation inputs before any qrels/goldset/canary30 changes.",
        },
        "mature_solution_alignment": [
            {
                "source": "LangChain text splitter docs",
                "url": "https://docs.langchain.com/oss/python/integrations/splitters/index",
                "applied_rule": "Use chunk_size/chunk_overlap as tunable retrieval parameters, not as unverified defaults.",
            },
            {
                "source": "LlamaIndex retrieval evaluation docs",
                "url": "https://docs.llamaindex.ai/en/stable/module_guides/evaluating/",
                "applied_rule": "Judge retriever changes with ranking metrics such as MRR, hit-rate, precision, and recall.",
            },
            {
                "source": "Pinecone chunking strategies guide",
                "url": "https://www.pinecone.io/learn/chunking-strategies/",
                "applied_rule": "Evaluate chunk sizes on representative queries and compare quality before promotion.",
            },
        ],
        "current_runtime_constants": current_constants,
        "historical_runs": {
            "aligned_baseline_2026_04_27": {
                "parameters": "historical_aligned_no_rerank_control",
                "metrics": aligned_metrics,
            },
            "regression_run_200_8": {
                "parameters": _run_parameters(regression_run, label="regression_run_200_8"),
                "metrics": regression_metrics,
            },
            "revert_run_150_5": {
                "parameters": _run_parameters(revert_run, label="revert_run_150_5"),
                "metrics": revert_metrics,
            },
        },
        "comparisons": {
            "regression_200_8_minus_revert_150_5": {
                "metric_delta": _metric_deltas(revert_metrics, regression_metrics),
                "rank_metrics_identical": identical_param_metrics,
                "interpretation": (
                    "200/8 and 150/5 produced identical Recall/MRR in the available causality run; "
                    "the parameter change is not proven as the regression cause."
                ),
            },
            "revert_150_5_minus_aligned_baseline": {
                "metric_delta": _metric_deltas(aligned_metrics, revert_metrics),
                "interpretation": "The regression persisted after reverting to 150/5, so cache/corpus state must be verified first.",
            },
        },
        "cache_evidence": cache_evidence,
        "decision": decision,
        "recommended_next_steps": [
            "Keep CHUNK_OVERLAP=150 and MAX_CHUNKS_PER_MATERIAL=5 until post-rebuild aligned canary30 metrics exist.",
            "Verify the rebuilt embedding cache manifest chunk_count and corpus hash match the current corpus.",
            "Rerun aligned canary30 no-rerank/raw/default control after cache verification.",
            "Only compare 200/8 against 150/5 after cache sanity passes; record old/new metrics and restore paths.",
            "Prefer a versioned added query set before editing existing qrels/goldset/canary30 files.",
        ],
        "stop_conditions": [
            "Stop before paid or credentialed embedding/model calls unless the environment and authorization are explicit.",
            "Stop before modifying qrels/goldset/canary30 if backup, old/new metrics, and restore path are missing.",
            "Stop before changing default runtime chunk constants if 200/8 lacks a passing post-cache control comparison.",
        ],
        "requires_cache_rebuild_verification": requires_rebuild_verification,
    }


def write_review_payload(payload: Mapping[str, Any], output_path: Path) -> Path:
    """Write a deterministic JSON review artifact."""

    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _default_paths() -> dict[str, Path]:
    evaluations = REPO_ROOT / "workspace_artifacts" / "evaluations"
    return {
        "resources_router_path": REPO_ROOT / "literature_assistant" / "core" / "routers" / "resources_router.py",
        "chunk_params_analysis_path": evaluations / "canary30-chunk-params-analysis-20260503.json",
        "causality_path": evaluations / "canary30-causality-confirmation-20260503.json",
        "cache_rebuild_path": evaluations / "canary30-cache-rebuild-20260503.json",
        "final_evaluation_path": evaluations / "canary30-final-20260503.json",
        "backup_path": REPO_ROOT / "workspace_artifacts" / "backups" / "lmwr-470-20260505" / "evaluation-inputs",
        "output_path": evaluations / DEFAULT_OUTPUT_NAME,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for LMWR-470's read-only chunk-parameter review."""

    defaults = _default_paths()
    parser = argparse.ArgumentParser(description="Build the read-only LMWR-470 chunk parameter review artifact.")
    parser.add_argument("--resources-router", type=Path, default=defaults["resources_router_path"])
    parser.add_argument("--chunk-params-analysis", type=Path, default=defaults["chunk_params_analysis_path"])
    parser.add_argument("--causality", type=Path, default=defaults["causality_path"])
    parser.add_argument("--cache-rebuild", type=Path, default=defaults["cache_rebuild_path"])
    parser.add_argument("--final-evaluation", type=Path, default=defaults["final_evaluation_path"])
    parser.add_argument("--backup", type=Path, default=defaults["backup_path"])
    parser.add_argument("--output", type=Path, default=defaults["output_path"])
    parser.add_argument("--review-date", default=DEFAULT_REVIEW_DATE)
    parser.add_argument("--pretty", action="store_true", help="Print the review JSON to stdout after writing it.")
    args = parser.parse_args(argv)
    payload = build_lmwr470_review(
        resources_router_path=args.resources_router,
        chunk_params_analysis_path=args.chunk_params_analysis,
        causality_path=args.causality,
        cache_rebuild_path=args.cache_rebuild,
        final_evaluation_path=args.final_evaluation,
        backup_path=args.backup,
        review_date=args.review_date,
    )
    output_path = write_review_payload(payload, args.output)
    if args.pretty:
        print(output_path.read_text(encoding="utf-8"))
    return 0 if payload["decision"]["promote_200_8"] is False else 2


if __name__ == "__main__":
    raise SystemExit(main())
