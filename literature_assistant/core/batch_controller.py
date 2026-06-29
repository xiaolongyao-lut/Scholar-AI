# -*- coding: utf-8 -*-
"""Deterministic batch PDF controller for public source checkouts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from layers.v_layer_volume_bundle import build_volume_bundle, dump_volume_bundle

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class BatchProcessController:
    """Process local PDFs into material packs and volume bundles.

    Args:
        pdf_folder: Directory containing source PDF files.
        output_root: Directory that receives batch and volume JSON outputs.
        goal: Research goal attached to generated material packs.
        batch_size: Number of material packs per volume bundle; must be >= 1.
        enable_llm: Reserved compatibility flag; this controller is deterministic.
        progress_callback: Optional callback receiving progress in [0, 1] and a stage label.
    """

    pdf_folder: str
    output_root: str
    goal: str
    batch_size: int = 10
    enable_llm: bool = True
    progress_callback: ProgressCallback | None = None

    def __post_init__(self) -> None:
        if not str(self.pdf_folder).strip():
            raise ValueError("pdf_folder must be non-empty")
        if not str(self.output_root).strip():
            raise ValueError("output_root must be non-empty")
        if not str(self.goal).strip():
            raise ValueError("goal must be non-empty")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")

    def process_batch(self) -> dict[str, Any]:
        """Process PDFs and return a JSON-serializable batch report."""
        source_dir = Path(self.pdf_folder).expanduser().resolve()
        output_dir = Path(self.output_root).expanduser().resolve()
        if not source_dir.is_dir():
            raise FileNotFoundError(f"pdf_folder does not exist or is not a directory: {source_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(source_dir.glob("*.pdf"))
        total = len(pdfs)
        material_packs: list[Path] = []
        failed: list[dict[str, str]] = []
        started_at = datetime.now(timezone.utc).isoformat()
        self._emit_progress(0.0, "Scanning PDFs")

        for index, pdf_path in enumerate(pdfs, start=1):
            try:
                paper_id = f"P{index:04d}"
                pack_path = output_dir / "batch_0001" / paper_id / "02_writing_material_pack.json"
                self._write_material_pack(pack_path, paper_id, pdf_path)
                material_packs.append(pack_path)
            except OSError as exc:
                failed.append({"path": str(pdf_path), "error": str(exc)})
            progress = index / total if total else 1.0
            self._emit_progress(progress * 0.8, f"Processed {index}/{total} PDFs")

        volumes_created = self._create_volume_bundles(output_dir, material_packs)
        report = {
            "schema_version": "scholar-ai-batch-process-report/v1",
            "status": "completed",
            "start_time": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "pdf_folder": str(source_dir),
            "output_root": str(output_dir),
            "goal": self.goal,
            "batch_size": self.batch_size,
            "total_pdfs": total,
            "successful_pdfs": len(material_packs),
            "failed_pdfs": len(failed),
            "failures": failed,
            "volumes_created": volumes_created,
        }
        self._write_report(output_dir, report)
        self._emit_progress(1.0, "Completed")
        return report

    def _create_volume_bundles(self, output_dir: Path, material_packs: list[Path]) -> int:
        """Create volume bundles from generated material-pack JSON files."""
        volumes_created = 0
        for volume_index, start in enumerate(range(0, len(material_packs), self.batch_size), start=1):
            chunk = material_packs[start : start + self.batch_size]
            if not chunk:
                continue
            volume_id = f"V{volume_index:02d}"
            volume_dir = output_dir / f"volume_{volume_id}"
            bundle = build_volume_bundle(chunk, volume_id=volume_id)
            dump_volume_bundle(bundle, volume_dir / f"volume_bundle_{volume_id}.json")
            volumes_created += 1
            self._emit_progress(
                0.8 + (0.2 * volumes_created / max(1, (len(material_packs) + self.batch_size - 1) // self.batch_size)),
                f"Created volume {volume_id}",
            )
        return volumes_created

    def _write_material_pack(self, pack_path: Path, paper_id: str, pdf_path: Path) -> None:
        """Write a material pack with source provenance and deterministic seed cards."""
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        title = pdf_path.stem
        payload = {
            "schema_version": "scholar-ai-writing-material-pack/v1",
            "source_pdf": str(pdf_path),
            "paper_id": paper_id,
            "title": title,
            "goal": self.goal,
            "llm_status": "disabled",
            "writing_point_cards": [
                {
                    "writing_point_id": f"{paper_id}_wp001",
                    "claim": f"{title} is available for review under goal: {self.goal}",
                    "relevance_score": 0.8,
                }
            ],
            "selected_references": [
                {
                    "reference_id": f"{paper_id}_ref001",
                    "source_pdf": str(pdf_path),
                    "title": title,
                }
            ],
            "single_figure_cards": [],
        }
        pack_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_report(self, output_dir: Path, report: dict[str, Any]) -> None:
        """Persist the report where the volume analysis service already scans."""
        report_dir = output_dir / "batch_logs"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (report_dir / f"batch_report_{stamp}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _emit_progress(self, progress: float, stage: str) -> None:
        """Notify optional observers while keeping batch execution independent."""
        if self.progress_callback is None:
            return
        self.progress_callback(max(0.0, min(1.0, float(progress))), stage)
