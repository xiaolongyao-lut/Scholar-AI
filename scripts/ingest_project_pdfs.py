"""Ingest a project's PDF source files into doc_store + chunk_store.

Why this exists:
    A project freshly created on disk (e.g. via API or hand-placed
    workspace_artifacts/projects/<pid>/source_files/) has no doc_store
    or chunk_store until ingestion runs. This script walks the
    project's source_files/, runs the active PDF backend
    (marker when the feature flag is on, PyMuPDF otherwise), and
    persists doc_store row + chunk jsonl + markdown sidecar exactly the
    same way the API upload path does — by calling the production
    ``_write_material_document_content`` helper.

Inputs / outputs:
    - Input: ``--project-id <pid>``. Optional ``--material-id`` to bind
      a specific id; otherwise generated as ``mat_<uuid-12-hex>``.
    - Output: writes via the resources_router helpers:
        workspace_artifacts/projects/<pid>/doc_store/<pid>.json
        workspace_artifacts/projects/<pid>/chunk_store/<pid>/manifest.json
        workspace_artifacts/projects/<pid>/chunk_store/<pid>/*.jsonl
        workspace_artifacts/projects/<pid>/chunk_store/<pid>/markdown/*.md (marker only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

# Force stdout to utf-8 for Chinese filenames on Windows cp936 terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE = _REPO_ROOT / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


def _bridge_env() -> None:
    """Copy LITASSIST_* vars from dotenv into os.environ so the production
    security policy / endpoint validation reads them. Mirrors what other
    long-running scripts in this repo do."""
    from runtime_env import env_value

    for key in (
        "LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS",
        "LITASSIST_PROXY_FAKE_IP_CIDRS",
    ):
        if os.getenv(key) is None:
            value = env_value(key)
            if value is not None:
                os.environ[key] = value


def _file_fingerprint(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def _ingest_one_pdf(
    project_id: str,
    pdf_path: Path,
    *,
    material_id: str | None,
) -> dict[str, Any]:
    from routers import resources_router as _rr

    if material_id is None:
        material_id = f"mat_{uuid4().hex[:12]}"

    payload = _rr._extract_document_payload_from_path(pdf_path.name, pdf_path)
    content = _rr._truncate_document_content(payload.content)
    result = _rr._write_material_document_content(
        project_id,
        material_id,
        pdf_path.name,
        content,
        source_relative_path=pdf_path.name,
        source_fingerprint=_file_fingerprint(pdf_path),
        source_size=pdf_path.stat().st_size,
        source_mtime=pdf_path.stat().st_mtime,
        blocks=payload.blocks,
        markdown_full=payload.markdown_full,
    )
    return {
        "pdf": str(pdf_path),
        "material_id": material_id,
        "chunks": int(result.get("chunks") or 0),
        "sidecar_markdown_path": str(result.get("sidecar_markdown_path") or ""),
        "has_blocks": bool(payload.blocks),
        "has_markdown_full": bool(payload.markdown_full),
        "content_length": int(result.get("content_length") or 0),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--material-id",
        default=None,
        help="Optional explicit material_id. If absent, one is generated as mat_<12hex>. Only useful when re-ingesting and you want the new chunks to keep an existing chunk_id prefix.",
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help="Optional explicit PDF path. If absent, ingests every *.pdf under workspace_artifacts/projects/<pid>/source_files/.",
    )
    parser.add_argument(
        "--projects-root",
        default=None,
        help="Override workspace_artifacts/projects/ root (testing).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _bridge_env()

    projects_root = (
        Path(args.projects_root)
        if args.projects_root
        else _REPO_ROOT / "workspace_artifacts" / "projects"
    )
    project_dir = projects_root / args.project_id
    source_dir = project_dir / "source_files"
    if not source_dir.is_dir():
        print(f"[FATAL] source_files dir missing: {source_dir}")
        return 2

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        pdfs = sorted(p for p in source_dir.glob("*.pdf") if p.is_file())

    if not pdfs:
        print(f"[FATAL] no PDFs found in {source_dir}")
        return 2

    print(f"project={args.project_id} ingesting {len(pdfs)} PDF(s)")
    started = time.monotonic()
    out: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"  → {pdf.name}")
        slot_started = time.monotonic()
        try:
            row = _ingest_one_pdf(args.project_id, pdf, material_id=args.material_id)
        except Exception as exc:
            print(f"    FAILED: {type(exc).__name__}: {exc}")
            out.append({"pdf": str(pdf), "error": f"{type(exc).__name__}: {exc}"})
            continue
        elapsed = round(time.monotonic() - slot_started, 1)
        print(
            f"    OK: material_id={row['material_id']} chunks={row['chunks']} "
            f"has_blocks={row['has_blocks']} elapsed={elapsed}s"
        )
        out.append(row)

    total_elapsed = round(time.monotonic() - started, 1)
    report_dir = (
        _REPO_ROOT
        / "workspace_artifacts"
        / f"pdf-ingest-evidence-{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {"project_id": args.project_id, "elapsed_s": total_elapsed, "items": out},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nelapsed={total_elapsed}s report={report_path}")
    any_errors = any("error" in row for row in out)
    return 1 if any_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
