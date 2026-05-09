from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chunk_vector_store import EMBEDDING_DIM, _chunks_hash, _is_contextualized_chunk
from literature_assistant.core.project_paths import output_path


DEFAULT_OUTPUT_NAME = "post-lmwr-470-cache-corpus-preflight-20260505.json"
SUPPORTED_CORPUS_SUFFIXES = {".json", ".jsonl"}


class CacheCorpusPreflightError(ValueError):
    """Raised when cache/corpus inputs cannot support a read-only decision."""


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
        raise CacheCorpusPreflightError(f"expected file, got directory: {_repo_relative(path)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CacheCorpusPreflightError(f"expected JSON object: {_repo_relative(path)}")
    return payload


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise CacheCorpusPreflightError(f"expected JSONL file, got directory: {_repo_relative(path)}")
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise CacheCorpusPreflightError(f"{_repo_relative(path)}:{line_number} must be a JSON object")
        rows.append(payload)
    return rows


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("claim")
        or chunk.get("text")
        or chunk.get("raw_content")
        or chunk.get("source_text")
        or ""
    )


def _normalize_chunk(chunk: Mapping[str, Any], index: int) -> dict[str, Any]:
    chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or f"chunk_{index}").strip()
    if not chunk_id:
        raise CacheCorpusPreflightError(f"chunk at index {index} has empty chunk_id")
    normalized = dict(chunk)
    normalized["chunk_id"] = chunk_id
    normalized["content"] = _chunk_content(chunk)
    return normalized


def _dedupe_chunks(chunks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, chunk in enumerate(chunks):
        normalized = _normalize_chunk(chunk, index)
        chunk_id = str(normalized["chunk_id"])
        if chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)
        rows.append(normalized)
    rows.sort(key=lambda item: str(item.get("chunk_id") or ""))
    return rows


def load_chunks_from_json(path: Path) -> list[dict[str, Any]]:
    """Load chunks from a corpus JSON, JSONL, or chunk-store material JSONL file.

    Args:
        path: File ending in `.json` or `.jsonl`. JSON inputs may either be a
            corpus object with `chunks`, a chunk-store manifest object, or a
            single chunk object.

    Returns:
        Deterministically ordered chunk dictionaries suitable for cache hashing.
    """

    if path.suffix.lower() not in SUPPORTED_CORPUS_SUFFIXES:
        raise CacheCorpusPreflightError(f"unsupported corpus file suffix: {path.suffix}")
    if path.suffix.lower() == ".jsonl":
        return _dedupe_chunks(_read_jsonl_objects(path))
    payload = _read_json_object(path)
    chunks_value = payload.get("chunks")
    if isinstance(chunks_value, list):
        chunk_rows = [item for item in chunks_value if isinstance(item, Mapping)]
        return _dedupe_chunks(chunk_rows)
    if "chunk_id" in payload or "content" in payload or "text" in payload:
        return _dedupe_chunks([payload])
    raise CacheCorpusPreflightError(f"JSON corpus lacks a chunks array: {_repo_relative(path)}")


def load_chunks_from_chunk_store(project_dir: Path) -> list[dict[str, Any]]:
    """Load all chunks referenced by a v2 project chunk-store manifest."""

    if not isinstance(project_dir, Path):
        raise TypeError("project_dir must be a Path")
    if not project_dir.exists():
        raise FileNotFoundError(project_dir)
    if not project_dir.is_dir():
        raise CacheCorpusPreflightError(f"chunk store path must be a directory: {_repo_relative(project_dir)}")
    manifest_path = project_dir / "manifest.json"
    manifest = _read_json_object(manifest_path)
    materials = manifest.get("materials")
    if not isinstance(materials, Mapping):
        raise CacheCorpusPreflightError(f"chunk store manifest lacks materials: {_repo_relative(manifest_path)}")
    chunks: list[dict[str, Any]] = []
    missing_files: list[str] = []
    for material_id, raw_entry in sorted(materials.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_entry, Mapping):
            continue
        relative_path = str(raw_entry.get("relative_path") or "").strip()
        if not relative_path:
            continue
        material_path = (project_dir / relative_path).resolve()
        try:
            material_path.relative_to(project_dir.resolve())
        except ValueError as exc:
            raise CacheCorpusPreflightError(f"chunk material escapes project dir: {relative_path}") from exc
        if not material_path.exists():
            missing_files.append(relative_path)
            continue
        for row in _read_jsonl_objects(material_path):
            row.setdefault("material_id", str(material_id))
            chunks.append(row)
    if missing_files:
        preview = ", ".join(missing_files[:3])
        raise CacheCorpusPreflightError(f"chunk store missing material files: {preview}")
    return _dedupe_chunks(chunks)


def summarize_chunks(chunks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the cache-relevant corpus summary used by ChunkVectorStore."""

    normalized = _dedupe_chunks(chunks)
    return {
        "chunk_count": len(normalized),
        "chunks_hash": _chunks_hash(normalized),
        "is_contextual": any(_is_contextualized_chunk(chunk) for chunk in normalized),
    }


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _safe_shape(value: Any) -> list[int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    rows = _safe_int(value[0])
    cols = _safe_int(value[1])
    if rows is None or cols is None:
        return None
    return [rows, cols]


def evaluate_manifest(manifest_path: Path, corpus_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Compare one embedding cache manifest with a corpus summary."""

    manifest = _read_json_object(manifest_path)
    expected_count = _safe_int(corpus_summary.get("chunk_count"))
    expected_hash = corpus_summary.get("chunks_hash")
    expected_contextual = corpus_summary.get("is_contextual")
    if expected_count is None:
        raise CacheCorpusPreflightError("corpus_summary.chunk_count must be an integer")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise CacheCorpusPreflightError("corpus_summary.chunks_hash must be a non-empty string")
    if not isinstance(expected_contextual, bool):
        raise CacheCorpusPreflightError("corpus_summary.is_contextual must be a boolean")

    manifest_count = _safe_int(manifest.get("chunk_count"))
    manifest_hash = manifest.get("chunks_hash")
    manifest_shape = _safe_shape(manifest.get("embedding_shape"))
    manifest_dim = _safe_int(manifest.get("embedding_dim"))
    manifest_contextual = manifest.get("is_contextual")
    zero_row_count = _safe_int(manifest.get("zero_row_count"))
    checks = {
        "chunk_count_match": manifest_count == expected_count,
        "chunks_hash_match": isinstance(manifest_hash, str) and manifest_hash == expected_hash,
        "shape_row_match": manifest_shape is not None and manifest_shape[0] == expected_count,
        "shape_dim_match": manifest_shape is not None and manifest_shape[1] == EMBEDDING_DIM,
        "embedding_dim_match": manifest_dim in (None, EMBEDDING_DIM),
        "contextual_match": manifest_contextual == expected_contextual,
        "zero_rows_absent": zero_row_count in (None, 0),
    }
    failure_reasons = [name for name, passed in checks.items() if not passed]
    status = "PASS" if not failure_reasons else "FAIL"
    return {
        "manifest_path": _repo_relative(manifest_path),
        "status": status,
        "checks": checks,
        "failure_reasons": failure_reasons,
        "manifest": {
            "version": manifest.get("version"),
            "model": manifest.get("model"),
            "chunk_count": manifest_count,
            "chunks_hash": manifest_hash if isinstance(manifest_hash, str) else None,
            "embedding_shape": manifest_shape,
            "embedding_dim": manifest_dim,
            "is_contextual": manifest_contextual if isinstance(manifest_contextual, bool) else None,
            "zero_row_count": zero_row_count,
        },
        "expected": {
            "chunk_count": expected_count,
            "chunks_hash": expected_hash,
            "embedding_dim": EMBEDDING_DIM,
            "is_contextual": expected_contextual,
        },
    }


def discover_manifest_paths(cache_dir: Path) -> list[Path]:
    """Return sorted embedding cache manifest paths under a cache directory."""

    if not cache_dir.exists():
        return []
    if not cache_dir.is_dir():
        raise CacheCorpusPreflightError(f"cache path must be a directory: {_repo_relative(cache_dir)}")
    return sorted(path for path in cache_dir.glob("*.manifest.json") if path.is_file())


def build_cache_corpus_preflight(
    *,
    corpus_json: Path | None = None,
    chunk_store_dir: Path | None = None,
    manifest_paths: Sequence[Path] | None = None,
    cache_dirs: Sequence[Path] | None = None,
    review_date: str = "2026-05-05",
) -> dict[str, Any]:
    """Build a read-only cache/corpus preflight report for post-LMWR-470."""

    if bool(corpus_json) == bool(chunk_store_dir):
        raise ValueError("provide exactly one of corpus_json or chunk_store_dir")
    if manifest_paths is not None and cache_dirs is not None:
        raise ValueError("provide either manifest_paths or cache_dirs, not both")
    if not isinstance(review_date, str) or not review_date.strip():
        raise ValueError("review_date must be a non-empty string")

    if corpus_json is not None:
        chunks = load_chunks_from_json(corpus_json)
        corpus_source = {"kind": "corpus_json", "path": _repo_relative(corpus_json)}
    else:
        assert chunk_store_dir is not None
        chunks = load_chunks_from_chunk_store(chunk_store_dir)
        corpus_source = {"kind": "chunk_store", "path": _repo_relative(chunk_store_dir)}
    corpus_summary = summarize_chunks(chunks)
    paths = list(manifest_paths or [])
    if not paths:
        dirs = list(cache_dirs or [output_path("embedding_cache")])
        seen_paths: set[Path] = set()
        for cache_dir in dirs:
            for path in discover_manifest_paths(cache_dir):
                resolved = path.resolve()
                if resolved not in seen_paths:
                    paths.append(path)
                    seen_paths.add(resolved)
    evaluations = [evaluate_manifest(path, corpus_summary) for path in paths]
    fail_count = sum(1 for item in evaluations if item["status"] != "PASS")
    pass_count = len(evaluations) - fail_count
    if not evaluations:
        status = "NO_MANIFEST"
        recommendation = "No embedding manifest found; run cache rebuild only after provider/cost authorization is explicit."
    elif fail_count:
        status = "FAIL"
        recommendation = "Do not rerun canary30 or promote 200/8 until cache manifests are rebuilt and pass this preflight."
    else:
        status = "PASS"
        recommendation = "Cache/corpus manifest checks passed; canary30 control may be rerun if provider/cost authorization is explicit."
    return {
        "schema_version": 1,
        "task_id": "Post-LMWR-470-cache-corpus-preflight",
        "review_date": review_date,
        "mode": "read_only_no_embedding_calls",
        "status": status,
        "corpus_source": corpus_source,
        "corpus_summary": corpus_summary,
        "manifest_count": len(evaluations),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "manifest_evaluations": evaluations,
        "recommendation": recommendation,
        "mature_solution_alignment": [
            {
                "source": "LlamaIndex ingestion pipeline",
                "url": "https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/",
                "applied_rule": "Treat source/chunk hashes as cache invalidation evidence before reusing embeddings.",
            },
            {
                "source": "LangChain indexing API",
                "url": "https://python.langchain.com/docs/how_to/indexing/",
                "applied_rule": "Use record/hash style bookkeeping to avoid stale retrieval indexes.",
            },
            {
                "source": "FAISS index IO guidance",
                "url": "https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning",
                "applied_rule": "Persisted vector indexes need explicit validation before loading as trusted retrieval state.",
            },
        ],
    }


def write_preflight_payload(payload: Mapping[str, Any], output_path: Path) -> Path:
    """Write a deterministic JSON preflight report."""

    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _parse_manifest_paths(values: Sequence[str] | None) -> list[Path] | None:
    if not values:
        return None
    return [Path(value) for value in values]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for read-only cache/corpus manifest preflight."""

    parser = argparse.ArgumentParser(description="Run a read-only embedding cache/corpus manifest preflight.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--corpus-json", type=Path, help="Corpus JSON or JSONL file containing chunks.")
    group.add_argument("--chunk-store-dir", type=Path, help="Project chunk-store v2 directory with manifest.json.")
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
    cache_dirs = list(args.cache_dir or [output_path("embedding_cache")])
    if args.include_legacy_cache:
        legacy_cache_dir = REPO_ROOT / "output" / "embedding_cache"
        if legacy_cache_dir not in cache_dirs:
            cache_dirs.append(legacy_cache_dir)
    payload = build_cache_corpus_preflight(
        corpus_json=args.corpus_json,
        chunk_store_dir=args.chunk_store_dir,
        manifest_paths=_parse_manifest_paths(args.manifest),
        cache_dirs=cache_dirs,
        review_date=args.review_date,
    )
    written_path = write_preflight_payload(payload, args.output)
    if args.pretty:
        print(written_path.read_text(encoding="utf-8"))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
