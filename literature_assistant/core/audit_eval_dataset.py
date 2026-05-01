"""audit_eval_dataset.py — 一次性 eval jsonl + chunk_store 体检。

Wave 1 — agile-hugging-peacock.md §改动 1。

产出:
1. 审计 JSON(schema_version=1,机读可追溯)
2. template flags sidecar JSONL(给 eval_retrieval_runtime.py 的 --template-flags 用)

CLI:
    python audit_eval_dataset.py \\
        --queries eval_queries_v2.1.jsonl \\
        --chunk-dir output/chunk_store \\
        --output artifacts/eval_audit/audit_v21.json \\
        --flags-output artifacts/eval_audit/audit_v21_template_flags.jsonl \\
        --top-n 10
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_eval_corpus import QUERY_TEMPLATES

SCHEMA_VERSION = 1
BAD_CASE_MULTI_DOC_THRESHOLD = 6
BAD_CASE_SAMPLE_LIMIT = 5
NON_TEMPLATE_SAMPLE_LIMIT = 10


# ---------------- loaders ----------------

def load_queries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"query file not found: {path}")
    queries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                queries.append(json.loads(stripped))
    return queries


def load_chunk_material_ids(chunk_dir: Path) -> set[str]:
    material_ids: set[str] = set()

    # 支持 V2 Layout — 扫描子目录下的 manifest
    for project_dir in chunk_dir.iterdir():
        if not project_dir.is_dir():
            continue
        manifest_path = project_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mats = manifest.get("materials", {})
                if isinstance(mats, dict):
                    material_ids.update(str(mid) for mid in mats.keys())
            except (OSError, json.JSONDecodeError):
                pass

    # 兼容 V1 Layout
    for fp in chunk_dir.glob("*.json"):
        if fp.name == "manifest.json": continue # Skip project manifests at root if any


# ---------------- template detection ----------------

_PLACEHOLDER_RE = re.compile(r"\{topic\d*\}")


def _template_to_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{topic\d*\})", template)
    pieces: list[str] = []
    for p in parts:
        if _PLACEHOLDER_RE.fullmatch(p):
            pieces.append("(.+?)")
        else:
            pieces.append(re.escape(p))
    return re.compile("^" + "".join(pieces) + "$", re.UNICODE | re.DOTALL)


def compile_template_patterns(
    templates: dict[str, list[str]],
) -> list[tuple[str, int, str, re.Pattern[str]]]:
    """返回 [(difficulty, index, raw_template, compiled_regex), ...]。

    顺序按 `templates` 字典 order(Python 3.7+ 保序),即 simple → medium → hard。
    """
    out: list[tuple[str, int, str, re.Pattern[str]]] = []
    for difficulty, tmpl_list in templates.items():
        for idx, raw in enumerate(tmpl_list):
            out.append((difficulty, idx, raw, _template_to_regex(raw)))
    return out


def classify_query(
    query_text: str,
    patterns: list[tuple[str, int, str, re.Pattern[str]]],
) -> tuple[bool, str | None]:
    """返回 (is_template, template_id)。template_id 形如 'simple:0'。

    一条 query 命中**第一个**匹配到的 template 就停(simple → medium → hard)。
    """
    for difficulty, idx, _raw, regex in patterns:
        if regex.fullmatch(query_text):
            return True, f"{difficulty}:{idx}"
    return False, None


# ---------------- aggregators ----------------

def compute_totals(queries: list[dict]) -> dict[str, Any]:
    unique_text: set[str] = set()
    doc_ids: set[str] = set()
    source_titles: set[str] = set()
    for q in queries:
        if qt := q.get("query_text"):
            unique_text.add(qt)
        for ev in q.get("evidence_set", []) or []:
            if did := ev.get("doc_id"):
                doc_ids.add(str(did))
        if st := q.get("source_title"):
            source_titles.add(str(st))
    return {
        "total_queries": len(queries),
        "unique_query_text": len(unique_text),
        "unique_doc_ids_in_evidence": len(doc_ids),
        "unique_source_titles": len(source_titles),
    }


def compute_per_difficulty(
    queries: list[dict],
    patterns: list[tuple[str, int, str, re.Pattern[str]]],
) -> dict[str, dict[str, int]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for q in queries:
        buckets[str(q.get("difficulty_level", "unknown"))].append(q)
    out: dict[str, dict[str, int]] = {}
    for diff in sorted(buckets):
        subset = buckets[diff]
        unique_text = {q.get("query_text", "") for q in subset}
        matched = sum(1 for q in subset if classify_query(q.get("query_text", ""), patterns)[0])
        out[diff] = {
            "count": len(subset),
            "unique_text": len(unique_text),
            "template_matched": matched,
        }
    return out


def compute_doc_id_coverage(
    queries: list[dict],
    material_ids: set[str] | None,
) -> dict[str, Any] | None:
    if material_ids is None:
        return None
    seen: set[str] = set()
    for q in queries:
        for ev in q.get("evidence_set", []) or []:
            if did := ev.get("doc_id"):
                seen.add(str(did))
    missing = sorted(d for d in seen if d not in material_ids)
    hit = len(seen) - len(missing)
    return {
        "total_distinct_doc_ids": len(seen),
        "hit": hit,
        "missing": len(missing),
        "missing_samples": missing[: BAD_CASE_SAMPLE_LIMIT * 2],
    }


def compute_top_repeated_query_text(
    queries: list[dict],
    top_n: int,
) -> list[dict]:
    counter: Counter[str] = Counter()
    diff_map: dict[str, str] = {}
    for q in queries:
        qt = q.get("query_text", "")
        if not qt:
            continue
        counter[qt] += 1
        diff_map.setdefault(qt, str(q.get("difficulty_level", "unknown")))
    return [
        {"query_text": qt, "count": c, "difficulty": diff_map[qt]}
        for qt, c in counter.most_common(top_n)
    ]


def compute_per_source_fanout(
    queries: list[dict],
    top_n: int,
) -> dict[str, Any]:
    doc_fanout: Counter[str] = Counter()
    for q in queries:
        for ev in q.get("evidence_set", []) or []:
            if did := ev.get("doc_id"):
                doc_fanout[str(did)] += 1
    if not doc_fanout:
        return {"mode": "by_material_id", "unique_sources": 0}
    counts = list(doc_fanout.values())
    return {
        "mode": "by_material_id",
        "unique_sources": len(doc_fanout),
        "min": min(counts),
        "median": statistics.median(counts),
        "mean": round(statistics.mean(counts), 2),
        "max": max(counts),
        "top_sources_by_fanout": [
            {"material_id": mid, "count": c}
            for mid, c in doc_fanout.most_common(top_n)
        ],
    }


def compute_template_match(
    queries: list[dict],
    patterns: list[tuple[str, int, str, re.Pattern[str]]],
) -> dict[str, Any]:
    per_template: Counter[str] = Counter()
    matched = 0
    non_template_samples: list[str] = []
    for q in queries:
        qt = q.get("query_text", "")
        is_tmpl, tid = classify_query(qt, patterns)
        if is_tmpl and tid:
            matched += 1
            per_template[tid] += 1
        elif len(non_template_samples) < NON_TEMPLATE_SAMPLE_LIMIT:
            non_template_samples.append(qt)
    return {
        "templates_checked": len(patterns),
        "matched": matched,
        "non_template": len(queries) - matched,
        "non_template_samples": non_template_samples,
        "per_template_count": dict(per_template),
    }


def collect_bad_cases(
    queries: list[dict],
    coverage_result: dict[str, Any] | None,
    patterns: list[tuple[str, int, str, re.Pattern[str]]],
) -> dict[str, dict[str, Any]]:
    _ = patterns

    text_to_docs: dict[str, set[str]] = defaultdict(set)
    for q in queries:
        qt = q.get("query_text", "")
        for ev in q.get("evidence_set", []) or []:
            if did := ev.get("doc_id"):
                text_to_docs[qt].add(str(did))
    duplicate_types = [
        (qt, doc_set)
        for qt, doc_set in text_to_docs.items()
        if len(doc_set) >= BAD_CASE_MULTI_DOC_THRESHOLD
    ]
    duplicate_types.sort(key=lambda x: len(x[1]), reverse=True)
    dup_samples = [
        {
            "query_text": qt,
            "distinct_doc_count": len(docs),
            "sampled_doc_ids": sorted(docs)[:BAD_CASE_MULTI_DOC_THRESHOLD],
        }
        for qt, docs in duplicate_types[:BAD_CASE_SAMPLE_LIMIT]
    ]

    missing_samples: list[dict[str, str]] = []
    missing_count = 0
    if coverage_result is not None:
        missing_count = coverage_result.get("missing", 0)
        for did in (coverage_result.get("missing_samples") or [])[:BAD_CASE_SAMPLE_LIMIT]:
            missing_samples.append({"doc_id": did})

    hard_single_samples: list[dict[str, Any]] = []
    hard_single_count = 0
    for q in queries:
        if str(q.get("difficulty_level", "")) == "hard" and len(q.get("evidence_set", []) or []) <= 1:
            hard_single_count += 1
            if len(hard_single_samples) < BAD_CASE_SAMPLE_LIMIT:
                hard_single_samples.append(
                    {
                        "query_id": q.get("query_id"),
                        "query_text": q.get("query_text"),
                        "evidence_count": len(q.get("evidence_set", []) or []),
                    }
                )

    return {
        "duplicate_query_text_across_docs": {
            "type_count": len(duplicate_types),
            "samples": dup_samples,
        },
        "missing_doc_id": {
            "type_count": missing_count,
            "samples": missing_samples,
        },
        "hard_with_single_doc_evidence": {
            "type_count": hard_single_count,
            "samples": hard_single_samples,
        },
    }


def run_audit(
    queries_path: Path,
    chunk_dir: Path | None,
    top_n: int = 10,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    queries = load_queries(queries_path)
    material_ids = load_chunk_material_ids(chunk_dir) if chunk_dir else None
    patterns = compile_template_patterns(QUERY_TEMPLATES)

    totals = compute_totals(queries)
    per_difficulty = compute_per_difficulty(queries, patterns)
    coverage = compute_doc_id_coverage(queries, material_ids)
    top_repeated = compute_top_repeated_query_text(queries, top_n)
    fanout = compute_per_source_fanout(queries, top_n)
    template_match = compute_template_match(queries, patterns)
    bad_cases = collect_bad_cases(queries, coverage, patterns)

    audit: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_queries": str(queries_path),
        "input_chunk_dir": str(chunk_dir) if chunk_dir else None,
        "totals": totals,
        "per_difficulty": per_difficulty,
        "doc_id_coverage": coverage,
        "top_repeated_query_text": top_repeated,
        "per_source_fanout": fanout,
        "template_match": template_match,
        "bad_cases": bad_cases,
    }

    flags: list[dict[str, Any]] = []
    for q in queries:
        is_tmpl, tid = classify_query(q.get("query_text", ""), patterns)
        flags.append({
            "query_id": q.get("query_id"),
            "is_template": is_tmpl,
            "template_id": tid,
        })
    return audit, flags


# ---------------- presentation ----------------

def print_stdout_summary(audit: dict[str, Any]) -> None:
    totals = audit["totals"]
    pd = audit["per_difficulty"]
    tm = audit["template_match"]
    cov = audit["doc_id_coverage"]
    fan = audit["per_source_fanout"]
    bc = audit["bad_cases"]
    print(f"[audit] {audit['input_queries']}")
    print(
        f"  total={totals['total_queries']} "
        f"unique_text={totals['unique_query_text']} "
        f"unique_doc_ids={totals['unique_doc_ids_in_evidence']} "
        f"source_titles={totals['unique_source_titles']}"
    )
    print("  per_difficulty: " + " ".join(f"{d}={v['count']}" for d, v in pd.items()))
    print(
        f"  template_match: matched={tm['matched']}/{totals['total_queries']} "
        f"non_template={tm['non_template']}"
    )
    if cov is not None:
        print(
            f"  doc_id_coverage: {cov['hit']}/{cov['total_distinct_doc_ids']} hit "
            f"missing={cov['missing']}"
        )
    else:
        print("  doc_id_coverage: skipped (no --chunk-dir)")
    if fan.get("unique_sources"):
        print(
            f"  fanout: min={fan['min']} median={fan['median']} "
            f"mean={fan['mean']} max={fan['max']}"
        )
    print("  bad_cases:")
    for bucket_name, payload in bc.items():
        print(f"    {bucket_name}: {payload['type_count']} types, {len(payload.get('samples', []))} sampled")


# ---------------- CLI ----------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Wave 1 eval jsonl + chunk_store audit tool.")
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--chunk-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("output/eval_query_audit.json"))
    parser.add_argument("--flags-output", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    flags_output = args.flags_output
    if flags_output is None:
        flags_output = args.output.with_name(args.output.stem + "_template_flags.jsonl")

    chunk_dir = args.chunk_dir if args.chunk_dir and args.chunk_dir.exists() else None

    audit, flags = run_audit(
        queries_path=args.queries,
        chunk_dir=chunk_dir,
        top_n=args.top_n,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    flags_output.parent.mkdir(parents=True, exist_ok=True)
    with flags_output.open("w", encoding="utf-8") as f:
        for rec in flags:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print_stdout_summary(audit)
    print(f"  wrote {args.output}")
    print(f"  wrote {flags_output}")


if __name__ == "__main__":
    main()
