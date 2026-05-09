# -*- coding: utf-8 -*-
"""Volume analysis service.

Bridges the mature batch -> volume bundle -> cross-paper analysis workflow from
legacy scripts into API-friendly helpers for the current Modular project.
"""

from __future__ import annotations

import asyncio
import json
import logging
from hashlib import sha1
from pathlib import Path
from typing import Any

from layers.w_layer_cross_paper_analysis import CrossPaperAnalyzer

logger = logging.getLogger("VolumeAnalysisService")

REPO_ROOT = Path(__file__).resolve().parent
BATCH_OUTPUT_PATTERN = "batch_output*"
VOLUME_BUNDLE_PATTERN = "volume_*/volume_bundle_*.json"
BATCH_REPORT_PATTERN = "batch_logs/batch_report_*.json"
_VOLUME_ANALYSIS_LOCKS: dict[str, asyncio.Lock] = {}
_VOLUME_ANALYSIS_LOCKS_GUARD = asyncio.Lock()


async def _get_volume_lock(volume_key: str) -> asyncio.Lock:
    async with _VOLUME_ANALYSIS_LOCKS_GUARD:
        lock = _VOLUME_ANALYSIS_LOCKS.get(volume_key)
        if lock is None:
            lock = asyncio.Lock()
            _VOLUME_ANALYSIS_LOCKS[volume_key] = lock
        return lock


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_to_repo(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _build_volume_key(bundle_path: Path) -> str:
    relative = _relative_to_repo(bundle_path)
    digest = sha1(relative.encode("utf-8")).hexdigest()[:12]
    return f"{bundle_path.parent.name.lower()}-{digest}"


def _analysis_paths(bundle_path: Path, volume_id: str) -> dict[str, Path]:
    parent = bundle_path.parent
    return {
        "report": parent / f"02_volume_deep_analysis_report_{volume_id}.json",
        "conflict": parent / f"03_conflict_analysis_{volume_id}.json",
        "trend": parent / f"04_technology_trends_{volume_id}.json",
        "master_index": parent / f"05_master_global_index_{volume_id}.json",
    }


def _load_latest_batch_report(output_root: Path) -> dict[str, Any] | None:
    reports = sorted(output_root.glob(BATCH_REPORT_PATTERN), key=lambda item: item.stat().st_mtime, reverse=True)
    if not reports:
        return None
    try:
        return _load_json(reports[0])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read batch report %s: %s", reports[0], exc)
        return None


def _normalize_batch_summary(report: dict[str, Any] | None, output_root: Path) -> dict[str, Any]:
    if report is None:
        return {
            "output_root": output_root.name,
            "pdf_folder": None,
            "total_pdfs": 0,
            "successful_pdfs": 0,
            "failed_pdfs": 0,
            "batch_size": 0,
            "status": "unknown",
            "start_time": None,
        }

    return {
        "output_root": str(report.get("output_root") or output_root.name),
        "pdf_folder": report.get("pdf_folder"),
        "total_pdfs": int(report.get("total_pdfs") or 0),
        "successful_pdfs": int(report.get("successful_pdfs") or 0),
        "failed_pdfs": int(report.get("failed_pdfs") or 0),
        "batch_size": int(report.get("batch_size") or 0),
        "status": str(report.get("status") or "unknown"),
        "start_time": report.get("start_time"),
    }


def _cached_analysis_exists(paths: dict[str, Path]) -> bool:
    return paths["conflict"].is_file() and paths["trend"].is_file() and paths["master_index"].is_file()


def _list_batch_output_roots() -> list[Path]:
    roots = [path for path in REPO_ROOT.glob(BATCH_OUTPUT_PATTERN) if path.is_dir()]
    return sorted(roots, key=lambda item: item.stat().st_mtime, reverse=True)


def _serialize_conflict_item(item: dict[str, Any]) -> dict[str, Any]:
    grouped_claims: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for claim_group in item.get("claims", []):
        claim_text = str(claim_group.get("text") or "").strip()
        if not claim_text or claim_text in seen_texts:
            continue
        seen_texts.add(claim_text)
        grouped_claims.append({
            "text": claim_text,
            "papers": list(dict.fromkeys(claim_group.get("source_papers", []))),
        })

    return {
        "parameter": item.get("parameter"),
        "conflict_level": item.get("conflict_level"),
        "unique_claims": int(item.get("unique_claims") or 0),
        "paper_count": int(item.get("paper_count") or 0),
        "papers": list(dict.fromkeys(item.get("papers", []))),
        "claim_groups": grouped_claims[:6],
    }


def _serialize_trend_rows(trends: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for parameter, info in trends.get("parameter_trends", {}).items():
        rows.append({
            "parameter": parameter,
            "consensus": bool(info.get("consensus")),
            "trend": info.get("trend"),
            "papers_count": int(info.get("papers_count") or 0),
            "representative_claim": info.get("representative_claim"),
            "claim_variants": int(info.get("claim_variants") or 0),
        })

    return sorted(rows, key=lambda row: (row["consensus"], row["papers_count"]), reverse=True)


def list_volume_summaries() -> list[dict[str, Any]]:
    """Scan current batch outputs and surface available volume bundles."""
    volumes: list[dict[str, Any]] = []

    for output_root in _list_batch_output_roots():
        report = _load_latest_batch_report(output_root)
        batch_summary = _normalize_batch_summary(report, output_root)

        for bundle_path in sorted(output_root.glob(VOLUME_BUNDLE_PATTERN), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                bundle = _load_json(bundle_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable volume bundle %s: %s", bundle_path, exc)
                continue

            volume_id = str(bundle.get("volume_id") or bundle_path.stem)
            stats = bundle.get("stats", {}) if isinstance(bundle.get("stats"), dict) else {}
            analysis_paths = _analysis_paths(bundle_path, volume_id)

            volumes.append({
                "volume_key": _build_volume_key(bundle_path),
                "volume_id": volume_id,
                "label": f"{output_root.name} · {volume_id}",
                "paper_count": int(bundle.get("paper_count") or 0),
                "writing_point_count": int(stats.get("writing_point_count") or len(bundle.get("writing_points", []))),
                "figure_count": int(stats.get("figure_count") or len(bundle.get("figures", []))),
                "reference_count": int(stats.get("reference_count") or len(bundle.get("references", []))),
                "created_at": bundle.get("created_at") or batch_summary.get("start_time"),
                "status": "indexed" if _cached_analysis_exists(analysis_paths) else "pending",
                "source_root": output_root.name,
                "batch_summary": batch_summary,
                "bundle_path": str(bundle_path),
                "report_paths": {name: _relative_to_repo(path) for name, path in analysis_paths.items()},
            })

    volumes.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return volumes


def _find_volume_summary(volume_key: str) -> dict[str, Any]:
    for volume in list_volume_summaries():
        if volume["volume_key"] == volume_key:
            return volume
    raise KeyError(volume_key)


async def get_volume_analysis(volume_key: str, *, refresh: bool = False) -> dict[str, Any]:
    """Load or generate deep cross-paper analysis for one volume bundle."""
    summary = _find_volume_summary(volume_key)
    bundle_path = Path(summary["bundle_path"])
    if not bundle_path.is_file():
        raise FileNotFoundError(bundle_path)

    bundle = _load_json(bundle_path)
    volume_id = str(summary["volume_id"])
    paths = _analysis_paths(bundle_path, volume_id)
    before_refresh_mtime = paths["conflict"].stat().st_mtime if paths["conflict"].is_file() else None
    volume_lock = await _get_volume_lock(volume_key)

    async with volume_lock:
        # Re-check inside lock so concurrent requests for same volume do not duplicate heavy analysis work.
        cache_exists = _cached_analysis_exists(paths)
        current_refresh_mtime = paths["conflict"].stat().st_mtime if paths["conflict"].is_file() else None

        should_rebuild = not cache_exists
        if refresh:
            # Force refresh for the first entrant, but if another request already refreshed while we waited,
            # reuse latest cache instead of rebuilding again.
            should_rebuild = (not cache_exists) or (current_refresh_mtime == before_refresh_mtime)

        if should_rebuild:
            analyzer = CrossPaperAnalyzer()
            analysis_result = await analyzer.analyze_volume_bundle(bundle, bundle_path)

            paths["conflict"].write_text(
                json.dumps(analysis_result["conflict_analysis"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            paths["trend"].write_text(
                json.dumps(analysis_result["technology_trends"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            analyzer.index_builder.export_to_file(paths["master_index"])

            deep_analysis_report = {
                "schema_version": "v3.volume-deep-analysis",
                "volume_id": volume_id,
                "generated_at": bundle.get("created_at"),
                "analysis_generated_at": paths["conflict"].stat().st_mtime,
                "analysis_results": {name: _relative_to_repo(path) for name, path in paths.items()},
                "statistics": {
                    "paper_count": summary["paper_count"],
                    "writing_point_count": summary["writing_point_count"],
                    "figure_count": summary["figure_count"],
                    "reference_count": summary["reference_count"],
                    "tracked_parameter_count": len(analysis_result["conflict_analysis"].get("parameter_consensus", {})),
                    "high_conflict_count": len(analysis_result["conflict_analysis"].get("high_conflict_parameters", [])),
                    "consensus_count": len(analysis_result["conflict_analysis"].get("consensus_parameters", [])),
                },
                "status": "deep_analysis_complete",
            }
            paths["report"].write_text(json.dumps(deep_analysis_report, ensure_ascii=False, indent=2), encoding="utf-8")

    conflicts = _load_json(paths["conflict"])
    trends = _load_json(paths["trend"])
    master_index = _load_json(paths["master_index"])
    report = _load_json(paths["report"]) if paths["report"].is_file() else {}

    serialized_summary = {key: value for key, value in summary.items() if key != "bundle_path"}
    serialized_summary["status"] = "indexed"
    serialized_summary["report_paths"] = {name: _relative_to_repo(path) for name, path in paths.items()}

    return {
        "volume": serialized_summary,
        "analysis": {
            "generated_at": report.get("generated_at") or bundle.get("created_at"),
            "tracked_parameter_count": len(conflicts.get("parameter_consensus", {})),
            "high_conflict_count": len(conflicts.get("high_conflict_parameters", [])),
            "consensus_count": len(conflicts.get("consensus_parameters", [])),
            "top_conflicts": [_serialize_conflict_item(item) for item in conflicts.get("high_conflict_parameters", [])[:8]],
            "top_consensus": [_serialize_conflict_item(item) for item in conflicts.get("consensus_parameters", [])[:8]],
            "trend_rows": _serialize_trend_rows(trends)[:20],
            "master_index_stats": master_index.get("statistics", {}),
            "report_paths": {name: _relative_to_repo(path) for name, path in paths.items()},
        },
    }
