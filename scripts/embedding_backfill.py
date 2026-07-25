"""Backfill chunk.embedding for one or all projects via SiliconFlow BAAI/bge-m3.

Why this exists:
    Marker / PyMuPDF ingestion writes chunks to ``workspace_artifacts/projects/<pid>/chunk_store/<pid>/*.jsonl``
    with ``embedding: null``. As a result, ``ContextAwareRetriever.hybrid_search``
    falls back to ``vector_score = bm25_score`` (see r_layer_hybrid_retriever.py:292)
    and dense retrieval is effectively disabled. This script reads the existing
    chunks, embeds the chunk text with the production embedding pipeline
    (``chunk_vector_store.batch_embed_texts``, default SiliconFlow ``BAAI/bge-m3``),
    and atomically rewrites the jsonl with ``embedding`` populated.

Inputs / outputs:
    - Input: ``--project-id <pid>`` (repeatable) or ``--all-projects``.
    - Output: rewritten ``*.jsonl`` files (atomic write), plus an evidence
      report at ``workspace_artifacts/embedding-backfill-evidence-<ts>/report.json``.
      In ``--dry-run`` mode, the report records ``planned_embeddings`` without
      calling the provider or writing chunk JSONL.
      Real backfills use a strict embedding contract: no cross-provider/model
      credential failover and no local fallback.
    - On failure, original files are untouched (atomic ``.tmp`` + ``replace``).

Idempotence:
    Chunks where ``embedding`` is a list of length ``EMBEDDING_DIM`` are kept
    as-is. Only chunks where ``embedding`` is null / missing / dimension mismatch
    are recomputed. Empty content chunks are skipped (recorded in report).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Resolve repo root and prepend literature_assistant/core onto sys.path so
# relative imports in chunk_vector_store / runtime_env resolve. This mirrors
# how scripts/ other scripts (e.g. precompute_contextual_summaries.py) bootstrap.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "literature_assistant" / "core"
if str(_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_CORE_PATH))

from chunk_vector_store import (  # noqa: E402  (sys.path setup above)
    EMBEDDING_DIM,
    EmbeddingAPIError,
    batch_embed_texts,
)
from chunk_hashing import (  # noqa: E402
    compute_chunk_manifest_digest,
    is_finite_embedding_vector,
)
from runtime_env import env_value as _env_value  # noqa: E402

# Bridge dotenv values into os.environ for libraries that read os.getenv
# directly (e.g. provider_endpoint_policy reads LITASSIST_ALLOW_PROXY_FAKE_IP_*
# via os.getenv, not through runtime_env.env_value).
_DOTENV_BRIDGE_KEYS = (
    "LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS",
    "LITASSIST_PROXY_FAKE_IP_CIDRS",
    "EMBED_CONCURRENCY",
    "EMBEDDING_BATCH_SIZE",
    "SILICONFLOW_EMBEDDING_MIN_INTERVAL_MS",
)
for _key in _DOTENV_BRIDGE_KEYS:
    if os.getenv(_key) is None:
        _value = _env_value(_key)
        if _value is not None:
            os.environ[_key] = _value

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
logger = logging.getLogger("embedding_backfill")

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "BAAI/bge-m3"


@dataclass
class FileReport:
    """Per-jsonl-file backfill outcome for the evidence report."""

    path: str
    chunks_total: int = 0
    already_filled: int = 0
    skipped_empty: int = 0
    planned_embeddings: int = 0
    embedded: int = 0
    errors: list[str] = field(default_factory=list)
    wrote: bool = False
    elapsed_s: float = 0.0


@dataclass
class ProjectReport:
    """Per-project rollup for the evidence report."""

    project_id: str
    files: list[FileReport] = field(default_factory=list)

    def totals(self) -> dict[str, int]:
        return {
            "chunks_total": sum(f.chunks_total for f in self.files),
            "already_filled": sum(f.already_filled for f in self.files),
            "skipped_empty": sum(f.skipped_empty for f in self.files),
            "planned_embeddings": sum(f.planned_embeddings for f in self.files),
            "embedded": sum(f.embedded for f in self.files),
            "files": len(self.files),
            "wrote_files": sum(1 for f in self.files if f.wrote),
            "errors": sum(len(f.errors) for f in self.files),
        }


def _chunk_text(chunk: dict[str, Any]) -> str:
    """Mirror chunk_vector_store._extract_text for embedding input."""
    return str(chunk.get("content") or chunk.get("claim") or chunk.get("text") or "")


def _is_valid_embedding(value: Any) -> bool:
    return is_finite_embedding_vector(value) and len(value) >= EMBEDDING_DIM


def _atomic_write_text(target: Path, text: str) -> None:
    """Atomically replace one UTF-8 text file."""

    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _atomic_write_jsonl(target: Path, chunks: Iterable[dict[str, Any]]) -> None:
    """Write chunks atomically (tmp + os.replace) to avoid partial writes on crash."""
    lines = "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks)
    _atomic_write_text(target, lines + ("\n" if lines else ""))


def _load_owning_manifest(
    path: Path,
    chunks: list[dict[str, Any]],
) -> tuple[Path, dict[str, Any], str, dict[str, Any]]:
    """Return and validate the unique manifest entry that owns ``path``.

    The preflight proves the file has not already drifted before a provider
    call. Real backfill refuses unmanifested or stale JSONL rather than creating
    another silent truth/manifest split.
    """

    manifest_path = path.parent / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("owning manifest.json is missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("owning manifest.json is unreadable or invalid") from exc
    if not isinstance(payload, dict) or payload.get("version") != 2:
        raise ValueError("owning manifest must be a version 2 JSON object")
    materials = payload.get("materials")
    if not isinstance(materials, dict):
        raise ValueError("owning manifest materials must be an object")

    resolved_path = path.resolve()
    matches: list[tuple[str, dict[str, Any]]] = []
    for material_id, raw_entry in materials.items():
        if not isinstance(material_id, str) or not material_id.strip():
            raise ValueError("owning manifest contains an invalid material id")
        if not isinstance(raw_entry, dict):
            raise ValueError("owning manifest material entry must be an object")
        relative_path = raw_entry.get("relative_path") or raw_entry.get("file")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("owning manifest material path is invalid")
        relative = Path(relative_path.strip())
        if (
            relative.is_absolute()
            or relative.name != relative_path.strip()
            or relative.suffix.lower() != ".jsonl"
        ):
            raise ValueError("owning manifest material path must be one local JSONL filename")
        if (manifest_path.parent / relative).resolve() == resolved_path:
            matches.append((material_id, raw_entry))
    if len(matches) != 1:
        raise ValueError("chunk JSONL must have exactly one owning manifest entry")

    material_id, entry = matches[0]
    for chunk in chunks:
        if chunk.get("material_id") != material_id:
            raise ValueError("chunk material identity differs from its owning manifest entry")
    expected_count = entry.get("total_chunks", entry.get("count"))
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count != len(chunks)
    ):
        raise ValueError("owning manifest chunk count differs from the JSONL payload")
    expected_sha256 = entry.get("sha256")
    if (
        not isinstance(expected_sha256, str)
        or expected_sha256 != compute_chunk_manifest_digest(chunks)
    ):
        raise ValueError("owning manifest digest differs from the JSONL payload")
    return manifest_path, payload, material_id, entry


def _discover_chunk_files(project_root: Path) -> list[Path]:
    """Return all *.jsonl chunk files under chunk_store/, ignoring quarantine."""
    chunk_store = project_root / "chunk_store"
    if not chunk_store.exists():
        return []
    return [
        p
        for p in chunk_store.rglob("*.jsonl")
        if "_quarantine" not in p.parts
    ]


def _discover_projects(projects_root: Path) -> list[str]:
    """Return project IDs that have a chunk_store with at least one *.jsonl."""
    if not projects_root.exists():
        return []
    pids: list[str] = []
    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir():
            continue
        if _discover_chunk_files(entry):
            pids.append(entry.name)
    return pids


async def _backfill_file(
    path: Path,
    *,
    api_key: str | None,
    base_url: str,
    model: str,
    dry_run: bool,
    batch_size: int | None,
    concurrency: int | None,
) -> FileReport:
    """Backfill one jsonl. Reads chunks, embeds missing ones, atomically writes."""
    report = FileReport(path=str(path))
    started = time.monotonic()

    try:
        original_text = path.read_text(encoding="utf-8")
        raw_lines = original_text.splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        report.errors.append(f"read_failed: {exc}")
        return report

    chunks: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw_lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError as exc:
            report.errors.append(f"json_decode_failed line={line_no}: {exc}")
            report.elapsed_s = time.monotonic() - started
            return report
        if not isinstance(chunk, dict):
            report.errors.append(f"json_row_invalid line={line_no}: expected object")
            report.elapsed_s = time.monotonic() - started
            return report
        chunks.append(chunk)

    report.chunks_total = len(chunks)
    if not chunks:
        report.elapsed_s = time.monotonic() - started
        return report

    # Pick rows that still need embedding.
    pending_indices: list[int] = []
    pending_texts: list[str] = []
    for idx, chunk in enumerate(chunks):
        if _is_valid_embedding(chunk.get("embedding")):
            report.already_filled += 1
            continue
        text = _chunk_text(chunk)
        if not text.strip():
            report.skipped_empty += 1
            continue
        pending_indices.append(idx)
        pending_texts.append(text)

    if not pending_indices:
        logger.info("%s: nothing to backfill (filled=%d empty=%d)",
                    path.name, report.already_filled, report.skipped_empty)
        report.elapsed_s = time.monotonic() - started
        return report

    report.planned_embeddings = len(pending_indices)
    logger.info("%s: embedding %d/%d chunks (model=%s)",
                path.name, len(pending_indices), report.chunks_total, model)

    if dry_run:
        logger.info("%s: dry-run would embed %d chunks", path.name, len(pending_indices))
        report.elapsed_s = time.monotonic() - started
        return report

    try:
        manifest_path, manifest, _material_id, manifest_entry = _load_owning_manifest(
            path,
            chunks,
        )
    except (OSError, TypeError, ValueError) as exc:
        report.errors.append(f"manifest_preflight_failed: {exc}")
        report.elapsed_s = time.monotonic() - started
        return report

    try:
        vectors = await batch_embed_texts(
            pending_texts,
            api_key=api_key,
            base_url=base_url,
            model=model,
            batch_size=batch_size,
            concurrency=concurrency,
            stage="backfill",
            strict_contract=True,
        )
    except EmbeddingAPIError as exc:
        report.errors.append(f"embedding_failed: {exc}")
        report.elapsed_s = time.monotonic() - started
        return report
    except Exception as exc:  # broad — surface and report rather than abort batch
        report.errors.append(f"embedding_unexpected: {type(exc).__name__}: {exc}")
        report.elapsed_s = time.monotonic() - started
        return report

    if len(vectors) != len(pending_indices):
        report.errors.append(
            f"vector_count_mismatch: got {len(vectors)} for {len(pending_indices)} inputs"
        )
        report.elapsed_s = time.monotonic() - started
        return report

    for slot_idx, vec in zip(pending_indices, vectors):
        if not _is_valid_embedding(vec):
            report.errors.append(f"invalid_vector_at_chunk_index={slot_idx} len={len(vec) if isinstance(vec, list) else 'n/a'}")
            continue
        chunks[slot_idx]["embedding"] = list(vec[:EMBEDDING_DIM])
        report.embedded += 1

    if report.embedded > 0:
        try:
            _atomic_write_jsonl(path, chunks)
            manifest_entry["sha256"] = compute_chunk_manifest_digest(chunks)
            manifest_entry["total_chunks"] = len(chunks)
            manifest_entry.pop("count", None)
            _atomic_write_text(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        except (OSError, TypeError, ValueError) as exc:
            report.errors.append(f"write_failed: {exc}")
            try:
                _atomic_write_text(path, original_text)
            except OSError as rollback_exc:
                report.errors.append(f"rollback_failed: {rollback_exc}")
        else:
            report.wrote = True

    report.elapsed_s = time.monotonic() - started
    return report


async def _backfill_project(
    project_id: str,
    *,
    projects_root: Path,
    api_key: str | None,
    base_url: str,
    model: str,
    dry_run: bool,
    batch_size: int | None,
    concurrency: int | None,
) -> ProjectReport:
    """Backfill every *.jsonl under one project's chunk_store/."""
    project_report = ProjectReport(project_id=project_id)
    project_root = projects_root / project_id
    files = _discover_chunk_files(project_root)
    if not files:
        logger.warning("project=%s: no jsonl chunk files found", project_id)
        return project_report

    for path in files:
        file_report = await _backfill_file(
            path,
            api_key=api_key,
            base_url=base_url,
            model=model,
            dry_run=dry_run,
            batch_size=batch_size,
            concurrency=concurrency,
        )
        project_report.files.append(file_report)
        logger.info(
            "  -> %s: embedded=%d filled=%d skipped=%d errors=%d wrote=%s elapsed=%.1fs",
            Path(file_report.path).name,
            file_report.embedded,
            file_report.already_filled,
            file_report.skipped_empty,
            len(file_report.errors),
            file_report.wrote,
            file_report.elapsed_s,
        )

    return project_report


def _write_evidence_report(
    repo_root: Path,
    project_reports: list[ProjectReport],
    *,
    model: str,
    base_url: str,
    dry_run: bool,
    strict_contract: bool,
) -> Path:
    """Persist per-file + per-project totals so we can verify after the run."""
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    out_dir = repo_root / "workspace_artifacts" / f"embedding-backfill-evidence-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "started_at_utc": ts,
        "model": model,
        "base_url": base_url,
        "dry_run": dry_run,
        "strict_contract": strict_contract,
        "embedding_dim": EMBEDDING_DIM,
        "projects": [
            {
                "project_id": pr.project_id,
                "totals": pr.totals(),
                "files": [
                    {
                        "path": f.path,
                        "chunks_total": f.chunks_total,
                        "already_filled": f.already_filled,
                        "skipped_empty": f.skipped_empty,
                        "planned_embeddings": f.planned_embeddings,
                        "embedded": f.embedded,
                        "wrote": f.wrote,
                        "errors": f.errors,
                        "elapsed_s": round(f.elapsed_s, 2),
                    }
                    for f in pr.files
                ],
            }
            for pr in project_reports
        ],
    }

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--project-id",
        action="append",
        default=[],
        help="Project ID to backfill (repeatable). Mutually exclusive with --all-projects.",
    )
    selection.add_argument(
        "--all-projects",
        action="store_true",
        help="Discover and backfill every project under workspace_artifacts/projects/.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Embedding model (default: BAAI/bge-m3).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Embedding base URL (default: SiliconFlow).")
    parser.add_argument(
        "--api-key-env",
        default="BACKFILL_EMBEDDING_API_KEY",
        help=(
            "Env var holding the API key. If unset or empty, the script falls back to "
            "the project's standard embedding credential resolution (key pool + env)."
        ),
    )
    parser.add_argument("--batch-size", type=int, default=None, help="Override EMBEDDING_BATCH_SIZE.")
    parser.add_argument("--concurrency", type=int, default=None, help="Override EMBED_CONCURRENCY.")
    parser.add_argument(
        "--projects-root",
        default=None,
        help="Override workspace_artifacts/projects/ root (testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only: enumerate chunks needing embedding without calling the API or writing files.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO).")
    return parser.parse_args()


async def _amain() -> int:
    args = _parse_args()
    logging.basicConfig(level=args.log_level.upper(), format=LOG_FORMAT)

    repo_root = Path(__file__).resolve().parents[1]
    projects_root = Path(args.projects_root) if args.projects_root else repo_root / "workspace_artifacts" / "projects"

    if not projects_root.exists():
        logger.error("projects root missing: %s", projects_root)
        return 2

    if args.all_projects:
        project_ids = _discover_projects(projects_root)
        logger.info("--all-projects discovered %d project(s): %s", len(project_ids), project_ids)
    else:
        project_ids = list(dict.fromkeys(args.project_id))  # dedupe preserve order
        logger.info("targeting %d project(s): %s", len(project_ids), project_ids)

    if not project_ids:
        logger.error("no projects selected; nothing to do")
        return 2

    api_key = os.getenv(args.api_key_env) or None
    if api_key:
        logger.info("using explicit API key from env %s (len=%d, suffix=...%s)", args.api_key_env, len(api_key), api_key[-4:])
    else:
        logger.info("no explicit API key (env %s unset); will use project credential resolution", args.api_key_env)

    project_reports: list[ProjectReport] = []
    for pid in project_ids:
        logger.info("=== project %s ===", pid)
        pr = await _backfill_project(
            pid,
            projects_root=projects_root,
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
        )
        project_reports.append(pr)
        totals = pr.totals()
        logger.info(
            "project %s totals: embedded=%d already_filled=%d skipped=%d errors=%d files=%d wrote=%d",
            pid,
            totals["embedded"],
            totals["already_filled"],
            totals["skipped_empty"],
            totals["errors"],
            totals["files"],
            totals["wrote_files"],
        )

    report_path = _write_evidence_report(
        repo_root,
        project_reports,
        model=args.model,
        base_url=args.base_url,
        dry_run=bool(args.dry_run),
        strict_contract=True,
    )
    logger.info("evidence report: %s", report_path)

    any_errors = any(len(f.errors) > 0 for pr in project_reports for f in pr.files)
    return 1 if any_errors else 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
