#!/usr/bin/env python3
"""
Gate B Phase A: Build trusted canonical inputs from repo-local sources.

INPUT:  artifacts/eval_audit/gateb_initial_candidates.jsonl (trusted)
OUTPUT: artifacts/eval_audit/gateb_goldset.jsonl (reviewer-ready)
        artifacts/eval_audit/gateb_qrels.tsv (reviewer-ready)

Constraints:
- Root gateb_goldset.jsonl is FORBIDDEN as input
- Only seed from repo-local trusted sources
- S4 entries (query_text=null) are user-authored placeholders; excluded from Phase A
- Phase A scope: 36 candidates with actual query_text → reviewer-ready format
- Human annotation/pooling remains as a blocker for full trusted status
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any


def load_initial_candidates(path: Path) -> List[Dict[str, Any]]:
    """Load and validate initial candidates from trusted source."""
    if not path.exists():
        raise FileNotFoundError(f"Trusted source not found: {path}")
    
    candidates = []
    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                candidates.append(record)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse line {idx}: {e}", file=sys.stderr)
    
    print(f"✅ Loaded {len(candidates)} candidates from {path.name}")
    return candidates


def filter_reviewable_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter to candidates that have query_text.
    S4 entries with query_text=null are user-authored placeholders and excluded.
    """
    reviewable = [c for c in candidates if c.get("query_text") is not None]
    excluded = len(candidates) - len(reviewable)
    
    if excluded > 0:
        print(f"ℹ️  Excluded {excluded} placeholder candidates (S4 with query_text=null)")
    
    return reviewable


def build_goldset_record(candidate: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Build a schema-valid goldset record from a candidate.
    
    Phase A limitation: no pooling/annotation yet, so qrels array is empty.
    Human annotation remains the blocker for trusted relevance judgments.
    """
    query_id = f"q_gateb_{index:04d}"
    
    # Phase A: reviewer-ready scaffold without fabricated judgments
    record = {
        "schema_version": "1",
        "query_id": query_id,
        "query_text": candidate["query_text"],
        "qrels": [],  # Empty until human pooling+annotation
        "annotator_id": "phase_a_scaffold",
        "no_gold": True,  # Set to True until human annotation provides gold judgments
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Optional fields from candidate
    if candidate.get("stratum"):
        record["source_stratum"] = candidate["stratum"]
    
    if candidate.get("source_template_id"):
        record["source_template_id"] = candidate["source_template_id"]
    
    if candidate.get("original_query_id"):
        record["original_query_id"] = candidate["original_query_id"]
    
    # Add note about Phase A status
    record["notes"] = (
        f"Phase A scaffold: awaiting pooling and human annotation. "
        f"Priority: {candidate.get('priority', 'unspecified')}. "
        f"Original note: {candidate.get('note', 'none')}"
    )
    
    return record


def build_qrels_rows(goldset_records: List[Dict[str, Any]]) -> List[str]:
    """
    Build TREC-format qrels rows.
    
    Phase A: no human judgments yet, so this produces header-only TSV.
    Full qrels requires human pooling and annotation.
    """
    rows = ["query_id\titeration\tdoc_id\trelevance"]
    
    # Phase A: no judgment rows (empty qrels arrays)
    # After human annotation, this section will emit actual rows
    for record in goldset_records:
        for qrel in record.get("qrels", []):
            row = f"{record['query_id']}\t0\t{qrel['doc_id']}\t{qrel['relevance']}"
            rows.append(row)
    
    return rows


def write_goldset(records: List[Dict[str, Any]], output_path: Path):
    """Write goldset records to JSONL."""
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"✅ Wrote {len(records)} goldset records to {output_path}")


def write_qrels(rows: List[str], output_path: Path):
    """Write qrels rows to TSV."""
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(row + "\n")
    
    print(f"✅ Wrote {len(rows)} qrels rows (including header) to {output_path}")


def main():
    # Paths
    repo_root = Path(__file__).parent.parent
    input_path = repo_root / "artifacts" / "eval_audit" / "gateb_initial_candidates.jsonl"
    goldset_output = repo_root / "artifacts" / "eval_audit" / "gateb_goldset.jsonl"
    qrels_output = repo_root / "artifacts" / "eval_audit" / "gateb_qrels.tsv"
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Gate B Phase A: Build Trusted Canonical Inputs")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    
    # Load trusted source
    candidates = load_initial_candidates(input_path)
    
    # Filter to reviewable entries (exclude S4 placeholders)
    reviewable = filter_reviewable_candidates(candidates)
    print(f"✅ {len(reviewable)} candidates with query_text (reviewable)")
    print()
    
    # Build goldset records
    goldset_records = [
        build_goldset_record(candidate, idx)
        for idx, candidate in enumerate(reviewable, 1)
    ]
    
    # Build qrels rows
    qrels_rows = build_qrels_rows(goldset_records)
    
    # Write outputs
    write_goldset(goldset_records, goldset_output)
    write_qrels(qrels_rows, qrels_output)
    
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Phase A Status: Reviewer-Ready Scaffolds")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print("Strata distribution:")
    strata_counts = {}
    for rec in goldset_records:
        stratum = rec.get("source_stratum", "unknown")
        strata_counts[stratum] = strata_counts.get(stratum, 0) + 1
    
    for stratum in sorted(strata_counts.keys()):
        print(f"  {stratum}: {strata_counts[stratum]} queries")
    
    print()
    print("⚠️  BLOCKER: Human annotation required")
    print("   - Pooling: BM25 + Dense + Graph + RRF + Rerank + evidence_set")
    print("   - Annotation: relevance={0,1,2} judgments per doc in pool")
    print("   - After annotation: set no_gold=False, populate qrels arrays")
    print()
    print("📄 Next step: Review goldset records, proceed to pooling tool")


if __name__ == "__main__":
    main()
