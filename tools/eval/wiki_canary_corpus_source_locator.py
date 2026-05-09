from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chunk_vector_store import _chunks_hash, _is_contextualized_chunk
from chunk_size_guard import filter_embedding_safe_chunks
from literature_assistant.core.project_paths import output_path
from tools.eval.wiki_cache_corpus_preflight import (
    CacheCorpusPreflightError,
    _repo_relative,
    discover_manifest_paths,
    evaluate_manifest,
    write_preflight_payload,
)


DEFAULT_OUTPUT_NAME = "post-lmwr-470-canary-corpus-source-locator-20260505.json"


def _display_path(path: Path) -> str:
    candidate = path if path.is_absolute() else (REPO_ROOT / path)
    try:
        return candidate.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return candidate.as_posix()


def _read_json_file(path: Path) -> Any:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_chunk_payload(payload: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if isinstance(payload, list):
        chunks.extend([item for item in payload if isinstance(item, dict)])
        return chunks
    if isinstance(payload, dict):
        raw_chunks = payload.get("chunks")
        if isinstance(raw_chunks, list):
            chunks.extend([item for item in raw_chunks if isinstance(item, dict)])
            return chunks
        for value in payload.values():
            if isinstance(value, list):
                chunks.extend([item for item in value if isinstance(item, dict)])
    return chunks


def _read_runtime_material_jsonl(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    chunks.append(payload)
    except OSError:
        return []
    return chunks


def _load_runtime_v2_project(project_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_path = project_dir / "manifest.json"
    try:
        manifest = _read_json_file(manifest_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return [], []
    if not isinstance(manifest, dict):
        return [], []
    materials = manifest.get("materials")
    if not isinstance(materials, dict):
        return [], []

    chunks: list[dict[str, Any]] = []
    material_details: list[dict[str, Any]] = []
    for material_id, entry in materials.items():
        if not isinstance(entry, dict):
            continue
        relative_path = entry.get("relative_path") or entry.get("file")
        if not relative_path:
            continue
        material_path = project_dir / str(relative_path)
        material_chunks = _read_runtime_material_jsonl(material_path)
        chunks.extend(material_chunks)
        material_details.append(
            {
                "material_id": str(material_id),
                "relative_path": str(relative_path),
                "chunk_count": len(material_chunks),
                "declared_total_chunks": entry.get("total_chunks"),
            }
        )
    return chunks, material_details


def _runtime_summary(chunks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence")
    runtime_chunks = [dict(chunk) for chunk in chunks if isinstance(chunk, Mapping)]
    return {
        "chunk_count": len(runtime_chunks),
        "chunks_hash": _chunks_hash(runtime_chunks),
        "is_contextual": any(_is_contextualized_chunk(chunk) for chunk in runtime_chunks),
    }


def _dense_embedding_filter_report(chunks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence")
    runtime_chunks = [dict(chunk) for chunk in chunks if isinstance(chunk, Mapping)]
    filter_report = filter_embedding_safe_chunks(runtime_chunks)
    effective_chunks = filter_report["chunks"]
    return {
        "filter_semantics": {
            "source_file": "literature_assistant/core/chunk_size_guard.py",
            "function": "filter_embedding_safe_chunks",
            "rule": "Drop only chunks rejected by inspect_chunk().is_oversize hard max char/token guard.",
            "hard_max_chars": filter_report["hard_max_chars"],
            "hard_max_tokens": filter_report["hard_max_tokens"],
        },
        "input_count": filter_report["input_count"],
        "kept_count": filter_report["kept_count"],
        "filtered_count": filter_report["filtered_count"],
        "filtered_chunks_preview": filter_report["filtered_chunks"][:20],
        "summary": _runtime_summary(effective_chunks),
    }


def _strip_group_chunks(group: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in group.items() if key != "chunks"}


def _collect_runtime_chunk_groups(chunk_store_root: Path) -> dict[str, Any]:
    if not isinstance(chunk_store_root, Path):
        raise TypeError("chunk_store_root must be a Path")

    root_exists = chunk_store_root.exists()
    resolved_root = chunk_store_root.resolve() if root_exists else chunk_store_root.absolute()
    if not root_exists:
        return {
            "root_exists": False,
            "resolved_root": resolved_root,
            "groups": [],
            "v2_project_ids": set(),
            "skipped_legacy_files": [],
            "unreadable_legacy_files": [],
        }
    if not chunk_store_root.is_dir():
        raise CacheCorpusPreflightError(f"chunk store root must be a directory: {_display_path(chunk_store_root)}")

    groups: list[dict[str, Any]] = []
    v2_project_ids: set[str] = set()
    skipped_legacy_files: list[dict[str, Any]] = []
    unreadable_legacy_files: list[str] = []

    for project_dir in sorted(path for path in chunk_store_root.iterdir() if path.is_dir()):
        manifest_path = project_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        project_chunks, material_details = _load_runtime_v2_project(project_dir)
        v2_project_ids.add(project_dir.name)
        groups.append(
            {
                "kind": "v2_project",
                "group_id": project_dir.name,
                "path": _display_path(project_dir),
                "resolved_path": _repo_relative(project_dir.resolve()),
                "chunk_count": len(project_chunks),
                "material_count": len(material_details),
                "materials_preview": material_details[:5],
                "chunks": project_chunks,
            }
        )

    for path in sorted(chunk_store_root.glob("*.json")):
        legacy_project_id = path.name[: -len("_chunks.json")] if path.name.endswith("_chunks.json") else None
        if legacy_project_id and legacy_project_id in v2_project_ids:
            skipped_legacy_files.append(
                {
                    "path": _display_path(path),
                    "project_id": legacy_project_id,
                    "reason": "v2_project_preferred",
                }
            )
            continue
        try:
            legacy_chunks = _flatten_chunk_payload(_read_json_file(path))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            unreadable_legacy_files.append(_display_path(path))
            continue
        groups.append(
            {
                "kind": "legacy_json",
                "group_id": path.name,
                "path": _display_path(path),
                "resolved_path": _repo_relative(path.resolve()),
                "project_id": legacy_project_id,
                "chunk_count": len(legacy_chunks),
                "chunks": legacy_chunks,
            }
        )

    return {
        "root_exists": True,
        "resolved_root": resolved_root,
        "groups": groups,
        "v2_project_ids": v2_project_ids,
        "skipped_legacy_files": skipped_legacy_files,
        "unreadable_legacy_files": unreadable_legacy_files,
    }


def _single_group_exclusion_diagnostics(
    groups: Sequence[Mapping[str, Any]],
    manifest_paths: Sequence[Path],
) -> dict[str, Any]:
    all_chunks: list[dict[str, Any]] = []
    group_chunks: list[tuple[Mapping[str, Any], list[dict[str, Any]]]] = []
    for group in groups:
        chunks_value = group.get("chunks")
        chunks = [dict(chunk) for chunk in chunks_value if isinstance(chunk, Mapping)] if isinstance(chunks_value, list) else []
        group_chunks.append((group, chunks))
        all_chunks.extend(chunks)

    exact_matches: list[dict[str, Any]] = []
    count_only_candidates: list[dict[str, Any]] = []
    for group, chunks in group_chunks:
        if not chunks:
            continue
        excluded_group_id = str(group.get("group_id") or "")
        projected_chunks: list[dict[str, Any]] = []
        for candidate_group, candidate_chunks in group_chunks:
            if str(candidate_group.get("group_id") or "") == excluded_group_id:
                continue
            projected_chunks.extend(candidate_chunks)
        projected_summary = _runtime_summary(projected_chunks)
        evaluations = [evaluate_manifest(path, projected_summary) for path in manifest_paths]
        exact_for_group = [item for item in evaluations if item["status"] == "PASS"]
        if exact_for_group:
            exact_matches.append(
                {
                    "excluded_group": _strip_group_chunks(group),
                    "projected_summary": projected_summary,
                    "matching_manifests": [item["manifest_path"] for item in exact_for_group],
                }
            )
            continue
        count_matches = [
            item
            for item in evaluations
            if item["checks"].get("chunk_count_match") and item["checks"].get("shape_row_match")
        ]
        if count_matches:
            count_only_candidates.append(
                {
                    "excluded_group": _strip_group_chunks(group),
                    "projected_summary": projected_summary,
                    "count_matching_manifests": [item["manifest_path"] for item in count_matches],
                }
            )

    return {
        "exact_single_group_exclusion_matches": exact_matches,
        "count_only_single_group_exclusion_candidate_count": len(count_only_candidates),
        "count_only_single_group_exclusion_candidates_preview": count_only_candidates[:20],
        "current_group_count": len(group_chunks),
        "current_chunk_count": len(all_chunks),
    }


def inspect_runtime_chunk_store_root(chunk_store_root: Path) -> dict[str, Any]:
    """Inspect a chunk-store root using eval runtime loader semantics.

    Args:
        chunk_store_root: Directory equivalent to `Path("output") / "chunk_store"`
            in `eval_retrieval_runtime._load_retrieval_corpus`.

    Returns:
        A machine-readable report with runtime-order corpus hash evidence and
        source layout details. Chunks are not sorted or deduplicated because the
        eval runtime hashes and embeds them in loader order.
    """

    if not isinstance(chunk_store_root, Path):
        raise TypeError("chunk_store_root must be a Path")

    collected = _collect_runtime_chunk_groups(chunk_store_root)
    root_exists = bool(collected["root_exists"])
    resolved_root = collected["resolved_root"]
    groups = collected["groups"]
    chunks = [chunk for group in groups for chunk in group.get("chunks", []) if isinstance(chunk, dict)]
    v2_projects = [
        {
            "project_id": str(group.get("group_id") or ""),
            "path": group.get("path"),
            "resolved_path": group.get("resolved_path"),
            "chunk_count": group.get("chunk_count"),
            "material_count": group.get("material_count"),
            "materials_preview": group.get("materials_preview"),
        }
        for group in groups
        if group.get("kind") == "v2_project"
    ]
    legacy_json_files = [
        {
            "path": group.get("path"),
            "resolved_path": group.get("resolved_path"),
            "project_id": group.get("project_id"),
            "chunk_count": group.get("chunk_count"),
        }
        for group in groups
        if group.get("kind") == "legacy_json"
    ]
    summary = _runtime_summary(chunks)
    return {
        "root": _display_path(chunk_store_root),
        "resolved_root": _repo_relative(resolved_root),
        "root_exists": root_exists,
        "runtime_summary": summary,
        "v2_project_count": len(v2_projects),
        "legacy_json_count": len(legacy_json_files),
        "skipped_legacy_count": len(collected["skipped_legacy_files"]),
        "unreadable_legacy_count": len(collected["unreadable_legacy_files"]),
        "v2_projects": v2_projects,
        "legacy_json_files": legacy_json_files,
        "skipped_legacy_files": collected["skipped_legacy_files"],
        "unreadable_legacy_files": collected["unreadable_legacy_files"],
    }


def _collect_manifest_paths(
    *,
    manifest_paths: Sequence[Path] | None,
    cache_dirs: Sequence[Path] | None,
) -> list[Path]:
    if manifest_paths and cache_dirs:
        raise ValueError("provide either manifest_paths or cache_dirs, not both")
    if manifest_paths:
        return list(manifest_paths)

    paths: list[Path] = []
    seen_paths: set[Path] = set()
    for cache_dir in list(cache_dirs or [output_path("embedding_cache")]):
        for path in discover_manifest_paths(cache_dir):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            paths.append(path)
    return paths


def build_canary_corpus_source_locator(
    *,
    chunk_store_roots: Sequence[Path],
    manifest_paths: Sequence[Path] | None = None,
    cache_dirs: Sequence[Path] | None = None,
    review_date: str = "2026-05-05",
) -> dict[str, Any]:
    """Build a read-only locator report for the canary30 retrieval corpus source."""

    if not chunk_store_roots:
        raise ValueError("chunk_store_roots must not be empty")
    if not isinstance(review_date, str) or not review_date.strip():
        raise ValueError("review_date must be a non-empty string")

    manifests = _collect_manifest_paths(manifest_paths=manifest_paths, cache_dirs=cache_dirs)
    root_reports: list[dict[str, Any]] = []
    root_aliases: list[dict[str, str]] = []
    seen_roots: dict[Path, str] = {}
    for root in chunk_store_roots:
        resolved_root = root.resolve() if root.exists() else root.absolute()
        if resolved_root in seen_roots:
            root_aliases.append(
                {
                    "requested_root": _display_path(root),
                    "resolved_root": _repo_relative(resolved_root),
                    "canonical_report_root": seen_roots[resolved_root],
                }
            )
            continue
        collected = _collect_runtime_chunk_groups(root)
        root_report = inspect_runtime_chunk_store_root(root)
        seen_roots[resolved_root] = str(root_report["root"])
        evaluations = [
            evaluate_manifest(manifest_path, root_report["runtime_summary"])
            for manifest_path in manifests
        ]
        chunks = [
            chunk
            for group in collected["groups"]
            for chunk in group.get("chunks", [])
            if isinstance(chunk, dict)
        ]
        dense_filter_report = _dense_embedding_filter_report(chunks)
        dense_evaluations = [
            evaluate_manifest(manifest_path, dense_filter_report["summary"])
            for manifest_path in manifests
        ]
        dense_pass_count = sum(1 for evaluation in dense_evaluations if evaluation["status"] == "PASS")
        pass_count = sum(1 for evaluation in evaluations if evaluation["status"] == "PASS")
        root_report["manifest_count"] = len(evaluations)
        root_report["pass_count"] = pass_count
        root_report["fail_count"] = len(evaluations) - pass_count
        root_report["matching_manifests"] = [
            evaluation["manifest_path"] for evaluation in evaluations if evaluation["status"] == "PASS"
        ]
        root_report["manifest_evaluations"] = evaluations
        root_report["dense_embedding_filter"] = {
            **dense_filter_report,
            "manifest_count": len(dense_evaluations),
            "pass_count": dense_pass_count,
            "fail_count": len(dense_evaluations) - dense_pass_count,
            "matching_manifests": [
                evaluation["manifest_path"] for evaluation in dense_evaluations if evaluation["status"] == "PASS"
            ],
            "manifest_evaluations": dense_evaluations,
        }
        root_report["single_group_exclusion_diagnostics"] = _single_group_exclusion_diagnostics(
            collected["groups"],
            manifests,
        )
        root_reports.append(root_report)

    matching_roots = [
        report
        for report in root_reports
        if report.get("dense_embedding_filter", {}).get("pass_count", 0) > 0
        and report.get("runtime_summary", {}).get("chunk_count", 0) > 0
    ]
    existing_nonempty_roots = [
        report
        for report in root_reports
        if report.get("root_exists") and report.get("runtime_summary", {}).get("chunk_count", 0) > 0
    ]
    repair_candidate_roots = [
        report
        for report in root_reports
        if report.get("single_group_exclusion_diagnostics", {}).get("exact_single_group_exclusion_matches")
    ]
    if matching_roots:
        status = "PASS"
        recommendation = "At least one runtime root has an effective dense corpus matching an embedding manifest; rerun canary only with that exact root/filter/config."
    elif repair_candidate_roots:
        status = "REPAIR_CANDIDATE"
        recommendation = "A single runtime chunk group can be backed up and excluded to match an existing manifest; do not mutate until backup and restore path are recorded."
    elif existing_nonempty_roots:
        status = "NO_MATCH"
        recommendation = "Do not rerun canary30 or promote 200/8; runtime corpus roots are located but no visible embedding manifest matches their count/hash."
    else:
        status = "NO_CORPUS"
        recommendation = "No non-empty runtime corpus root was found; identify or rebuild the corpus before any canary30 control."

    default_root = Path("output") / "chunk_store"
    return {
        "schema_version": 1,
        "task_id": "Post-LMWR-470-canary-corpus-source-locator",
        "review_date": review_date,
        "mode": "read_only_no_embedding_or_provider_calls",
        "status": status,
        "runtime_loader_semantics": {
            "source_file": "workspace_tests/evaluation_scripts/eval_retrieval_runtime.py",
            "function": "_load_retrieval_corpus",
            "default_chunk_store_root": default_root.as_posix(),
            "v2_behavior": "Load sorted project directories containing manifest.json and append material JSONL rows in manifest order.",
            "legacy_behavior": "Then load sorted root *.json files; skip *_chunks.json when a same-name v2 project already exists.",
            "hash_behavior": "Use runtime chunk order without sorting or deduplication for cache manifest comparison.",
            "dense_embedding_behavior": "Before ChunkVectorStore.build, eval filters only chunks rejected by chunk_size_guard.inspect_chunk hard max limits.",
        },
        "manifest_count": len(manifests),
        "manifest_paths": [_repo_relative(path) for path in manifests],
        "root_aliases": root_aliases,
        "matching_root_count": len(matching_roots),
        "root_reports": root_reports,
        "selected_canary_runtime_source": {
            "path": default_root.as_posix(),
            "inference": "The eval runtime defaults to this relative path when canary30 is run from the repository root.",
        },
        "recommendation": recommendation,
        "mature_solution_alignment": [
            {
                "source": "LlamaIndex ingestion pipeline",
                "url": "https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/",
                "applied_rule": "Use source/chunk identity, transformation/filter semantics, and hash evidence before reusing an existing embedding cache.",
            },
            {
                "source": "LangChain indexing API",
                "url": "https://python.langchain.com/docs/how_to/indexing/",
                "applied_rule": "Keep record-manager style source tracking so stale index state is detectable.",
            },
            {
                "source": "FAISS Index IO",
                "url": "https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning",
                "applied_rule": "Validate persisted vector-index/cache metadata before trusting it for retrieval evaluation.",
            },
        ],
    }


def _parse_paths(values: Sequence[str] | None) -> list[Path] | None:
    if not values:
        return None
    return [Path(value) for value in values]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for read-only canary corpus source location."""

    parser = argparse.ArgumentParser(description="Locate canary30 runtime corpus sources and manifest alignment.")
    parser.add_argument(
        "--chunk-store-root",
        action="append",
        type=Path,
        help="Chunk-store root to inspect. Repeatable. Defaults to runtime root plus canonical generated root.",
    )
    parser.add_argument("--manifest", action="append", help="Specific embedding manifest path. Repeatable.")
    parser.add_argument(
        "--cache-dir",
        action="append",
        type=Path,
        help="Embedding cache directory to scan. Repeatable. Defaults to canonical workspace_artifacts output.",
    )
    parser.add_argument(
        "--include-legacy-cache",
        action="store_true",
        help="Also scan legacy root output/embedding_cache without writing to it.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "workspace_artifacts" / "evaluations" / DEFAULT_OUTPUT_NAME,
    )
    parser.add_argument("--review-date", default="2026-05-05")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    roots = list(
        args.chunk_store_root
        or [
            REPO_ROOT / "output" / "chunk_store",
            output_path("chunk_store"),
        ]
    )
    cache_dirs = list(args.cache_dir or [output_path("embedding_cache")])
    if args.include_legacy_cache:
        legacy_cache_dir = REPO_ROOT / "output" / "embedding_cache"
        if legacy_cache_dir not in cache_dirs:
            cache_dirs.append(legacy_cache_dir)

    payload = build_canary_corpus_source_locator(
        chunk_store_roots=roots,
        manifest_paths=_parse_paths(args.manifest),
        cache_dirs=cache_dirs,
        review_date=args.review_date,
    )
    written_path = write_preflight_payload(payload, args.output)
    if args.pretty:
        print(written_path.read_text(encoding="utf-8"))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
