from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from literature_assistant.core.project_paths import output_path


DEFAULT_QUERIES_PATH = REPO_ROOT / "workspace_tests" / "evaluation_data" / "eval_queries_v2.1_canary30_ALIGNED.jsonl"
DEFAULT_TRACE_PATH = (
    REPO_ROOT
    / "workspace_artifacts"
    / "evaluations"
    / "canary30-post-cache-no-rerank-effective-dense-20260505.rerank_trace.jsonl"
)
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT
    / "workspace_artifacts"
    / "evaluations"
    / "post-lmwr-470-canary30-goldset-drift-20260505.json"
)
DEFAULT_PROPOSAL_OUTPUT_PATH = (
    REPO_ROOT
    / "workspace_artifacts"
    / "evaluations"
    / "post-lmwr-470-canary30-goldset-proposal-20260505.json"
)
TITLE_SUFFIX_RE = re.compile(r"\.(pdf|docx?|txt|md|html?)$", flags=re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
ASCII_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", flags=re.IGNORECASE)
ANCHOR_TERMS = (
    "激光焊接",
    "力学性能",
    "钛合金",
    "铝合金",
    "镁合金",
    "不锈钢",
    "高强钢",
    "tc4",
    "ti6al4v",
    "硬度",
    "磨损",
    "空蚀",
    "腐蚀",
    "疲劳",
    "显微组织",
    "组织性能",
    "接头",
    "熔池",
    "氮化",
    "气体氮化",
    "laser welding",
    "mechanical properties",
    "titanium alloy",
    "cavitation erosion",
    "laser gas nitrided",
)


class CanaryGoldsetDriftError(ValueError):
    """Raised when canary goldset drift inputs are malformed."""


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise CanaryGoldsetDriftError(f"expected JSONL file: {_repo_relative(path)}")
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise CanaryGoldsetDriftError(f"{_repo_relative(path)}:{line_number} must be a JSON object")
        rows.append(payload)
    return rows


def _read_json_object(path: Path) -> dict[str, Any]:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CanaryGoldsetDriftError(f"expected JSON object: {_repo_relative(path)}")
    return payload


def _normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = TITLE_SUFFIX_RE.sub("", text)
    text = text.replace("–", "-").replace("—", "-").replace("_", " ")
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def _safe_material_id(value: Any) -> str:
    text = str(value or "").strip()
    if text:
        return text
    return ""


def _material_id_from_chunk(chunk: Mapping[str, Any]) -> str:
    material_id = _safe_material_id(chunk.get("material_id") or chunk.get("doc_id"))
    if material_id:
        return material_id
    chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if "_chunk_" in chunk_id:
        return chunk_id.split("_chunk_", 1)[0]
    return ""


def _flatten_chunk_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        raw_chunks = payload.get("chunks")
        if isinstance(raw_chunks, list):
            return [item for item in raw_chunks if isinstance(item, dict)]
        chunks: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, list):
                chunks.extend(item for item in value if isinstance(item, dict))
        return chunks
    return []


def _read_material_jsonl(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path)


def _load_v2_project_chunks(project_dir: Path, project_id: str) -> list[dict[str, Any]]:
    manifest_path = project_dir / "manifest.json"
    manifest = _read_json_object(manifest_path)
    materials = manifest.get("materials")
    if not isinstance(materials, Mapping):
        raise CanaryGoldsetDriftError(f"chunk store manifest lacks materials: {_repo_relative(manifest_path)}")
    chunks: list[dict[str, Any]] = []
    for material_id, raw_entry in sorted(materials.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_entry, Mapping):
            continue
        relative_path = str(raw_entry.get("relative_path") or raw_entry.get("file") or "").strip()
        if not relative_path:
            continue
        material_path = (project_dir / relative_path).resolve()
        try:
            material_path.relative_to(project_dir.resolve())
        except ValueError as exc:
            raise CanaryGoldsetDriftError(f"chunk material escapes project dir: {relative_path}") from exc
        if not material_path.exists():
            raise CanaryGoldsetDriftError(f"chunk material file missing: {_repo_relative(material_path)}")
        for row in _read_material_jsonl(material_path):
            row.setdefault("material_id", str(material_id))
            row["_diagnostic_project_id"] = project_id
            row["_diagnostic_source_path"] = _repo_relative(material_path)
            chunks.append(row)
    return chunks


def load_chunk_store_chunks(chunk_store_dir: Path) -> list[dict[str, Any]]:
    """Load chunk rows using eval-compatible root or single-project semantics.

    Args:
        chunk_store_dir: Either a v2 project directory containing `manifest.json`
            or a root directory containing v2 projects and legacy JSON files.

    Returns:
        Chunk dictionaries annotated with diagnostic source fields. The function
        is read-only and never calls embedding or provider APIs.
    """

    if not isinstance(chunk_store_dir, Path):
        raise TypeError("chunk_store_dir must be a Path")
    if not chunk_store_dir.exists():
        raise FileNotFoundError(chunk_store_dir)
    if not chunk_store_dir.is_dir():
        raise CanaryGoldsetDriftError(f"chunk store must be a directory: {_repo_relative(chunk_store_dir)}")

    if (chunk_store_dir / "manifest.json").exists():
        return _load_v2_project_chunks(chunk_store_dir, chunk_store_dir.name)

    chunks: list[dict[str, Any]] = []
    v2_project_ids: set[str] = set()
    for project_dir in sorted(path for path in chunk_store_dir.iterdir() if path.is_dir()):
        if not (project_dir / "manifest.json").exists():
            continue
        v2_project_ids.add(project_dir.name)
        chunks.extend(_load_v2_project_chunks(project_dir, project_dir.name))

    for path in sorted(chunk_store_dir.glob("*.json")):
        legacy_project_id = path.name[: -len("_chunks.json")] if path.name.endswith("_chunks.json") else None
        if legacy_project_id and legacy_project_id in v2_project_ids:
            continue
        for row in _flatten_chunk_payload(_read_json_object(path)):
            row["_diagnostic_project_id"] = legacy_project_id or path.stem
            row["_diagnostic_source_path"] = _repo_relative(path)
            chunks.append(row)
    return chunks


def build_material_catalog(chunks: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build material-level metadata used to explain canary trace hits."""

    if not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence")

    draft: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        material_id = _material_id_from_chunk(chunk)
        if not material_id:
            continue
        entry = draft.setdefault(
            material_id,
            {
                "material_id": material_id,
                "titles": set(),
                "normalized_titles": set(),
                "chunk_count": 0,
                "project_ids": set(),
                "source_paths": set(),
                "chunk_ids_preview": [],
                "first_content_sha256": None,
            },
        )
        entry["chunk_count"] += 1
        title = str(chunk.get("title") or chunk.get("source_title") or chunk.get("document_title") or "").strip()
        if title:
            entry["titles"].add(title)
            normalized = _normalize_title(title)
            if normalized:
                entry["normalized_titles"].add(normalized)
        project_id = str(chunk.get("_diagnostic_project_id") or "").strip()
        if project_id:
            entry["project_ids"].add(project_id)
        source_path = str(chunk.get("_diagnostic_source_path") or "").strip()
        if source_path:
            entry["source_paths"].add(source_path)
        chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
        if chunk_id and len(entry["chunk_ids_preview"]) < 5:
            entry["chunk_ids_preview"].append(chunk_id)
        if entry["first_content_sha256"] is None:
            content = str(chunk.get("content") or chunk.get("raw_content") or chunk.get("text") or "")
            if content:
                entry["first_content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()

    catalog: dict[str, dict[str, Any]] = {}
    for material_id, entry in sorted(draft.items()):
        titles = sorted(entry["titles"])
        normalized_titles = sorted(entry["normalized_titles"])
        catalog[material_id] = {
            "material_id": material_id,
            "title": titles[0] if titles else None,
            "titles": titles,
            "normalized_titles": normalized_titles,
            "chunk_count": int(entry["chunk_count"]),
            "project_ids": sorted(entry["project_ids"]),
            "source_paths": sorted(entry["source_paths"]),
            "chunk_ids_preview": list(entry["chunk_ids_preview"]),
            "first_content_sha256": entry["first_content_sha256"],
        }
    return catalog


def build_title_groups(catalog: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return exact normalized-title groups with more than one material id."""

    groups: dict[str, list[str]] = defaultdict(list)
    for material_id, entry in catalog.items():
        normalized_titles = entry.get("normalized_titles")
        if not isinstance(normalized_titles, list):
            continue
        for normalized_title in normalized_titles:
            if isinstance(normalized_title, str) and normalized_title:
                groups[normalized_title].append(str(material_id))
    duplicate_groups: list[dict[str, Any]] = []
    for normalized_title, material_ids in sorted(groups.items()):
        unique_ids = sorted(set(material_ids))
        if len(unique_ids) < 2:
            continue
        duplicate_groups.append(
            {
                "normalized_title": normalized_title,
                "material_ids": unique_ids,
                "titles": sorted(
                    {
                        str(catalog.get(material_id, {}).get("title") or "")
                        for material_id in unique_ids
                        if str(catalog.get(material_id, {}).get("title") or "").strip()
                    }
                ),
            }
        )
    return duplicate_groups


def _query_by_id(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        query_id = str(row.get("query_id") or "").strip()
        if query_id:
            result[query_id] = row
    return result


def _expected_doc_ids(query: Mapping[str, Any], trace: Mapping[str, Any]) -> list[str]:
    ids: set[str] = set()
    raw_trace_ids = trace.get("expected_doc_ids")
    if isinstance(raw_trace_ids, list):
        ids.update(str(item).strip() for item in raw_trace_ids if str(item).strip())
    evidence = query.get("evidence_set")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, Mapping):
                doc_id = str(item.get("doc_id") or "").strip()
                if doc_id:
                    ids.add(doc_id)
    return sorted(ids)


def _candidate_material_ids(hit: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("material_id", "doc_id", "id"):
        value = str(hit.get(key) or "").strip()
        if value:
            ids.add(value)
    candidate_doc_ids = hit.get("candidate_doc_ids")
    if isinstance(candidate_doc_ids, list):
        ids.update(str(item).strip() for item in candidate_doc_ids if str(item).strip())
    chunk_id = str(hit.get("chunk_id") or "").strip()
    if "_chunk_" in chunk_id:
        ids.add(chunk_id.split("_chunk_", 1)[0])
    return {item for item in ids if item}


def _ranked_hits(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = trace.get("returned_hits")
    if not isinstance(candidates, list):
        candidates = trace.get("candidates_after_rerank")
    if not isinstance(candidates, list):
        candidates = trace.get("candidates_before_rerank")
    if not isinstance(candidates, list):
        return []
    hits: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, Mapping):
            continue
        hit = dict(item)
        if not isinstance(hit.get("rank"), int):
            hit["rank"] = index
        hits.append(hit)
    return hits


def _material_title(material_id: str, catalog: Mapping[str, Mapping[str, Any]]) -> str | None:
    title = catalog.get(material_id, {}).get("title")
    return str(title).strip() if str(title or "").strip() else None


def _compact_hit(hit: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    material_ids = sorted(_candidate_material_ids(hit))
    primary_material_id = str(hit.get("material_id") or (material_ids[0] if material_ids else "")).strip()
    return {
        "rank": int(hit.get("rank") or 0),
        "chunk_id": str(hit.get("chunk_id") or "").strip() or None,
        "material_id": primary_material_id or None,
        "candidate_doc_ids": material_ids,
        "title": _material_title(primary_material_id, catalog) if primary_material_id else None,
        **({"rrf_score": hit.get("rrf_score")} if hit.get("rrf_score") is not None else {}),
        **({"dense_score": hit.get("dense_score")} if hit.get("dense_score") is not None else {}),
        **({"rerank_score": hit.get("rerank_score")} if hit.get("rerank_score") is not None else {}),
    }


def _first_gold_rank(hits: Sequence[Mapping[str, Any]], expected_ids: set[str]) -> int | None:
    for index, hit in enumerate(hits, start=1):
        rank = int(hit.get("rank") or index)
        if _candidate_material_ids(hit).intersection(expected_ids):
            return rank
    return None


def _unique_material_ids(hits: Sequence[Mapping[str, Any]], limit: int) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for hit in hits[:limit]:
        material_id = str(hit.get("material_id") or "").strip()
        if not material_id:
            ids = sorted(_candidate_material_ids(hit))
            material_id = ids[0] if ids else ""
        if material_id and material_id not in seen:
            seen.add(material_id)
            ordered.append(material_id)
    return ordered


def _query_anchor_terms(query_text: str) -> list[str]:
    normalized = _normalize_title(query_text)
    terms = [term for term in ANCHOR_TERMS if term.lower() in normalized]
    terms.extend(token.lower() for token in ASCII_TOKEN_RE.findall(normalized))
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped


def _title_contains_any(title: str | None, terms: Sequence[str]) -> bool:
    normalized = _normalize_title(title)
    return any(term.lower() in normalized for term in terms)


def _same_title_materials(source_title: Any, catalog: Mapping[str, Mapping[str, Any]]) -> list[str]:
    normalized_source = _normalize_title(source_title)
    if not normalized_source:
        return []
    matches: list[str] = []
    for material_id, entry in catalog.items():
        normalized_titles = entry.get("normalized_titles")
        if isinstance(normalized_titles, list) and normalized_source in normalized_titles:
            matches.append(str(material_id))
    return sorted(matches)


def _classify_query(
    *,
    query: Mapping[str, Any],
    expected_ids: set[str],
    hits: Sequence[Mapping[str, Any]],
    top_k: int,
    first_gold_rank: int | None,
    catalog: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    labels: list[str] = []
    top_hits = hits[:top_k]
    top_ids = [
        str(hit.get("material_id") or "").strip()
        for hit in top_hits
        if str(hit.get("material_id") or "").strip()
    ]
    top_counts = Counter(top_ids)
    source_title = query.get("source_title")
    same_title_ids = set(_same_title_materials(source_title, catalog)) - expected_ids

    if first_gold_rank is None:
        labels.append("gold_missing_in_trace_window")
    elif first_gold_rank <= top_k:
        labels.append("gold_hit_top_k")
    else:
        labels.append("gold_buried_after_top_k")

    if same_title_ids and any(_candidate_material_ids(hit).intersection(same_title_ids) for hit in top_hits):
        labels.append("same_title_alternate_in_top_k")

    if top_counts:
        material_id, count = top_counts.most_common(1)[0]
        if material_id not in expected_ids and count >= max(2, min(top_k, 5) // 2 + 1):
            labels.append("non_gold_top_k_dominance")

    query_text = str(query.get("query_text") or "")
    terms = _query_anchor_terms(query_text)
    top1_id = top_ids[0] if top_ids else ""
    top1_title = _material_title(top1_id, catalog) if top1_id else None
    expected_titles = [_material_title(material_id, catalog) for material_id in sorted(expected_ids)]
    expected_has_anchor = any(_title_contains_any(title, terms) for title in expected_titles if title)
    top1_has_anchor = _title_contains_any(top1_title, terms)
    broad_query = any(marker in query_text for marker in ("最新研究进展", "基本原理", "方法", "综述", "进展"))
    if top1_id and top1_id not in expected_ids and terms and broad_query and top1_has_anchor and not expected_has_anchor:
        labels.append("broad_query_competing_topic")

    return labels


def _top_competing_materials(records: Sequence[Mapping[str, Any]], catalog: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    affected: dict[str, list[str]] = defaultdict(list)
    for record in records:
        expected_ids = set(record.get("expected_doc_ids") if isinstance(record.get("expected_doc_ids"), list) else [])
        top1 = record.get("top1_material_id")
        if not isinstance(top1, str) or not top1 or top1 in expected_ids:
            continue
        counter[top1] += 1
        query_id = str(record.get("query_id") or "").strip()
        if query_id:
            affected[top1].append(query_id)
    return [
        {
            "material_id": material_id,
            "title": _material_title(material_id, catalog),
            "top1_count": count,
            "affected_query_ids": affected.get(material_id, [])[:20],
        }
        for material_id, count in counter.most_common(20)
    ]


def _safe_query_records(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    query_records = report.get("query_records")
    if not isinstance(query_records, list):
        raise CanaryGoldsetDriftError("drift report lacks query_records list")
    return [record for record in query_records if isinstance(record, Mapping)]


def _hit_contains_any(hit: Mapping[str, Any], material_ids: set[str]) -> bool:
    return bool(_candidate_material_ids(hit).intersection(material_ids))


def _proposal_type(labels: Sequence[str]) -> str:
    label_set = set(labels)
    if "same_title_alternate_in_top_k" in label_set:
        return "add_same_title_alternate_candidate"
    if "broad_query_competing_topic" in label_set:
        return "review_generic_query_scope"
    if "non_gold_top_k_dominance" in label_set:
        return "review_non_gold_top_k_dominance"
    if "gold_missing_in_trace_window" in label_set:
        return "review_missing_gold_or_query_rewrite"
    return "review_gold_buried_after_top_k"


def _proposal_candidates(record: Mapping[str, Any], max_candidates: int) -> list[dict[str, Any]]:
    expected_ids = {
        str(item).strip()
        for item in record.get("expected_doc_ids", [])
        if str(item).strip()
    } if isinstance(record.get("expected_doc_ids"), list) else set()
    top_hits = record.get("top_hits")
    if not isinstance(top_hits, list):
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in top_hits:
        if not isinstance(hit, Mapping):
            continue
        material_id = str(hit.get("material_id") or "").strip()
        if not material_id or material_id in expected_ids or material_id in seen:
            continue
        seen.add(material_id)
        candidates.append(
            {
                "material_id": material_id,
                "title": hit.get("title"),
                "first_seen_rank": hit.get("rank"),
                "source": "existing_eval_trace_top_k",
            }
        )
        if len(candidates) >= max_candidates:
            break
    return candidates


def build_goldset_update_proposal(
    drift_report: Mapping[str, Any],
    *,
    max_candidates_per_query: int = 3,
) -> dict[str, Any]:
    """Build a no-write proposal for versioned canary goldset evolution.

    Args:
        drift_report: Payload from `build_goldset_drift_report`.
        max_candidates_per_query: Upper bound for proposed alternate materials
            per missed query. Candidate inclusion is diagnostic and must be
            reviewed before modifying qrels or query files.

    Returns:
        JSON-serializable proposal with simulated trace-only metrics. The
        simulation is an upper-bound estimate, not a release gate.
    """

    if max_candidates_per_query < 1:
        raise CanaryGoldsetDriftError("max_candidates_per_query must be >= 1")
    query_records = _safe_query_records(drift_report)
    actions: list[dict[str, Any]] = []
    simulated_hit_ids: list[str] = []
    current_hit_ids: list[str] = []
    current_miss_ids: list[str] = []

    for record in query_records:
        query_id = str(record.get("query_id") or "").strip()
        if not query_id:
            continue
        expected_ids = {
            str(item).strip()
            for item in record.get("expected_doc_ids", [])
            if str(item).strip()
        } if isinstance(record.get("expected_doc_ids"), list) else set()
        top_hits = [
            hit for hit in record.get("top_hits", [])
            if isinstance(hit, Mapping)
        ] if isinstance(record.get("top_hits"), list) else []
        current_hit = bool(record.get("hit_top_k"))
        if current_hit:
            current_hit_ids.append(query_id)
            simulated_hit_ids.append(query_id)
            continue
        current_miss_ids.append(query_id)
        candidates = _proposal_candidates(record, max_candidates_per_query)
        proposed_ids = {str(item.get("material_id") or "").strip() for item in candidates}
        simulated_hit = any(_hit_contains_any(hit, expected_ids | proposed_ids) for hit in top_hits)
        if simulated_hit:
            simulated_hit_ids.append(query_id)
        labels = [
            str(label)
            for label in record.get("drift_labels", [])
            if str(label).strip()
        ] if isinstance(record.get("drift_labels"), list) else []
        actions.append(
            {
                "query_id": query_id,
                "query_text": record.get("query_text"),
                "source_title": record.get("source_title"),
                "expected_doc_ids": sorted(expected_ids),
                "first_gold_rank": record.get("first_gold_rank"),
                "top1_material_id": record.get("top1_material_id"),
                "top1_title": record.get("top1_title"),
                "proposal_type": _proposal_type(labels),
                "drift_labels": labels,
                "candidate_alternates": candidates,
                "simulated_hit_top_k_if_candidates_accepted": simulated_hit,
                "review_required": True,
                "mutation_allowed_without_backup": False,
            }
        )

    total = len(query_records)
    current_hit_count = len(current_hit_ids)
    simulated_hit_count = len(simulated_hit_ids)
    return {
        "schema_version": 1,
        "mode": "read_only_goldset_proposal_no_file_mutation",
        "status": "DRAFT_REVIEW_REQUIRED",
        "source_drift_report": drift_report.get("inputs"),
        "guardrails": {
            "does_not_modify_queries_qrels_goldset_or_canary30": True,
            "requires_checkpoint_before_materializing": True,
            "requires_file_backup_before_materializing": True,
            "requires_old_new_metrics_before_replacing_old_baseline": True,
            "trace_simulation_is_not_release_gate": True,
        },
        "recommended_versioned_outputs_not_written": {
            "queries_path": "workspace_tests/evaluation_data/eval_queries_v2.2_canary30_DRAFT.jsonl",
            "goldset_path": "workspace_tests/evaluation_data/canary30_goldset_v2.2_DRAFT.jsonl",
            "backup_dir": "workspace_artifacts/backups/canary30-goldset-v2.2-<date>/",
        },
        "summary": {
            "total_queries": total,
            "current_hit_top_k_count": current_hit_count,
            "current_recall_at_top_k": round(current_hit_count / total, 4) if total else 0.0,
            "current_miss_query_ids": current_miss_ids,
            "proposed_action_count": len(actions),
            "simulated_hit_top_k_count_if_all_candidates_accepted": simulated_hit_count,
            "simulated_recall_at_top_k_if_all_candidates_accepted": round(simulated_hit_count / total, 4) if total else 0.0,
        },
        "actions": actions,
    }


def build_goldset_drift_report(
    *,
    queries_path: Path,
    trace_path: Path,
    chunk_store_dir: Path,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Build a read-only diagnosis for canary goldset/material-id drift.

    Args:
        queries_path: Canary query JSONL containing `evidence_set` gold ids.
        trace_path: Eval rerank trace JSONL containing ranked retrieval hits.
        chunk_store_dir: Root or single-project chunk store used to resolve titles.
        top_k: Optional override for the ranking cutoff; defaults to trace `top_k`.

    Returns:
        Deterministic JSON-serializable report. It is diagnostic only and does
        not modify qrels, goldsets, canary files, caches, or chunk stores.
    """

    query_rows = _read_jsonl(queries_path)
    trace_rows = _read_jsonl(trace_path)
    query_map = _query_by_id(query_rows)
    chunks = load_chunk_store_chunks(chunk_store_dir)
    catalog = build_material_catalog(chunks)
    title_groups = build_title_groups(catalog)

    query_records: list[dict[str, Any]] = []
    expected_frequency: Counter[str] = Counter()
    label_frequency: Counter[str] = Counter()
    top1_frequency: Counter[str] = Counter()
    missing_query_ids: list[str] = []
    buried_query_ids: list[str] = []
    hit_topk_query_ids: list[str] = []

    for trace in trace_rows:
        query_id = str(trace.get("query_id") or "").strip()
        if not query_id:
            continue
        query = query_map.get(query_id, {})
        expected_ids = set(_expected_doc_ids(query, trace))
        expected_frequency.update(expected_ids)
        hits = _ranked_hits(trace)
        cutoff = int(top_k or trace.get("top_k") or 5)
        first_rank = _first_gold_rank(hits, expected_ids)
        top_hits = [_compact_hit(hit, catalog) for hit in hits[:cutoff]]
        recall_window_hits = [_compact_hit(hit, catalog) for hit in hits[: min(len(hits), 20)]]
        top1_material_id = str(top_hits[0].get("material_id") or "").strip() if top_hits else ""
        if top1_material_id:
            top1_frequency[top1_material_id] += 1
        labels = _classify_query(
            query=query,
            expected_ids=expected_ids,
            hits=top_hits,
            top_k=cutoff,
            first_gold_rank=first_rank,
            catalog=catalog,
        )
        label_frequency.update(labels)
        if first_rank is None:
            missing_query_ids.append(query_id)
        elif first_rank <= cutoff:
            hit_topk_query_ids.append(query_id)
        else:
            buried_query_ids.append(query_id)

        same_title_ids = sorted(set(_same_title_materials(query.get("source_title"), catalog)) - expected_ids)
        query_records.append(
            {
                "query_id": query_id,
                "difficulty": query.get("difficulty_level") or trace.get("difficulty"),
                "query_text": query.get("query_text"),
                "source_title": query.get("source_title"),
                "expected_doc_ids": sorted(expected_ids),
                "expected_titles": [
                    {"material_id": material_id, "title": _material_title(material_id, catalog)}
                    for material_id in sorted(expected_ids)
                ],
                "first_gold_rank": first_rank,
                "top_k": cutoff,
                "hit_top_k": first_rank is not None and first_rank <= cutoff,
                "top1_material_id": top1_material_id or None,
                "top1_title": _material_title(top1_material_id, catalog) if top1_material_id else None,
                "unique_top_k_material_ids": _unique_material_ids(top_hits, cutoff),
                "same_title_alternate_material_ids": same_title_ids,
                "drift_labels": labels,
                "top_hits": top_hits,
                "recall_window_preview": recall_window_hits,
            }
        )

    total_queries = len(query_records)
    hit_topk_count = len(hit_topk_query_ids)
    status = "PASS" if total_queries > 0 and hit_topk_count == total_queries else "DRIFT_DETECTED"
    return {
        "schema_version": 1,
        "mode": "read_only_trace_diagnostic_no_provider_calls",
        "status": status,
        "inputs": {
            "queries_path": _repo_relative(queries_path),
            "trace_path": _repo_relative(trace_path),
            "chunk_store_dir": _repo_relative(chunk_store_dir),
        },
        "summary": {
            "total_queries": total_queries,
            "hit_top_k_count": hit_topk_count,
            "miss_top_k_count": total_queries - hit_topk_count,
            "gold_missing_in_trace_window_count": len(missing_query_ids),
            "gold_buried_after_top_k_count": len(buried_query_ids),
            "duplicate_title_group_count": len(title_groups),
            "material_count": len(catalog),
            "chunk_count": len(chunks),
        },
        "label_frequency": dict(sorted(label_frequency.items())),
        "expected_doc_frequency": dict(sorted(expected_frequency.items())),
        "top1_material_frequency": dict(sorted(top1_frequency.items())),
        "hit_top_k_query_ids": hit_topk_query_ids,
        "gold_missing_in_trace_window_query_ids": missing_query_ids,
        "gold_buried_after_top_k_query_ids": buried_query_ids,
        "duplicate_title_groups_preview": title_groups[:20],
        "top_competing_materials": _top_competing_materials(query_records, catalog),
        "query_records": query_records,
    }


def write_report(payload: Mapping[str, Any], output_path: Path) -> Path:
    """Write deterministic JSON report for audit and runbook references."""

    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose canary30 goldset/material-id drift from existing eval traces.")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--chunk-store-dir", type=Path, default=output_path("chunk_store"))
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--proposal-output", type=Path, default=None)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--fail-on-drift", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    payload = build_goldset_drift_report(
        queries_path=args.queries,
        trace_path=args.trace,
        chunk_store_dir=args.chunk_store_dir,
        top_k=args.top_k,
    )
    write_report(payload, args.output)
    if args.proposal_output:
        proposal = build_goldset_update_proposal(payload)
        write_report(proposal, args.proposal_output)
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_drift and payload.get("status") != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
