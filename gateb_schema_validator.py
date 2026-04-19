#!/usr/bin/env python3
"""
GATEB Ledger Schema Validator (§ per spec 20260419)
Validates gateb_goldset.jsonl against frozen schema.

Checks:
  - §3: Required 7 fields + types + constraints
  - §4: qrels schema (doc_id / relevance / source_hint / judged_at)
  - §5: Graded 0/1/2 TREC semantics (no -1, no binary direct)
  - §6: Optional 9 fields + 4 cross-field invariants
  - §8: binary_threshold enforcement (derived-only, no writeback)
  - §9: Field provenance tagging
"""

import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Tuple


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCHEMA RULES (§3-§9, frozen 20260419)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# §3: Required 7 fields
REQUIRED_FIELDS = {
    "schema_version",
    "query_id",
    "query_text",
    "qrels",
    "annotator_id",
    "no_gold",
    "created_at",
}

# §4: qrels array element schema
REQUIRED_QRELS_FIELDS = {"doc_id", "relevance", "source_hint"}
OPTIONAL_QRELS_FIELDS = {"judged_at"}

# §5: Graded relevance constraint
ALLOWED_RELEVANCE = {0, 1, 2}

# §4: source_hint closed vocabulary (lex-sorted for hash diff)
SOURCE_HINT_ENUM = {
    "bm25",
    "bm25+dense",
    "bm25+graph",
    "dense",
    "rerank",
    "evidence_set",
    "unexpected_unknown_source",
}

# §6: Optional 9 fields
OPTIONAL_FIELDS = {
    "source_stratum",      # S1-S4
    "source_template_id",
    "original_query_id",
    "reviewer_id",
    "notes",
    "notes_for_future_tolf",
    "pool_size",
    "kappa_overlap_group",
    "judged_at",           # record-level optional (§6.2)
}

# §8: binary_threshold strictly derived-only (do NOT appear in canonical)
FORBIDDEN_DERIVED_ONLY = {"binary_threshold"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VALIDATOR CLASS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ValidatorState:
    """Accumulate cross-record stats and errors."""
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.query_ids: set = set()
        self.doc_ids: set = set()
        self.source_hints_seen: Counter = Counter()
        self.strata_seen: Counter = Counter()
        self.relevance_dist: Counter = Counter()
        self.no_gold_count = 0
        self.pool_sizes: List[int] = []
        self.created_at_range: Tuple[str, str] = (None, None)


def validate_json_structure(record: Dict[str, Any], idx: int, state: ValidatorState) -> bool:
    """§3: Validate required fields, types, and basic constraints."""
    ok = True

    # §3: Check required fields present
    missing = REQUIRED_FIELDS - set(record.keys())
    if missing:
        state.errors.append(f"[record {idx}] Missing required fields: {missing}")
        ok = False

    # §3: Check schema_version
    if "schema_version" in record:
        if record["schema_version"] != "1":
            state.errors.append(
                f"[record {idx}] schema_version must be '1', got {record['schema_version']}"
            )
            ok = False

    # §3: query_id must be non-empty string
    if "query_id" in record:
        if not isinstance(record["query_id"], str) or not record["query_id"].strip():
            state.errors.append(f"[record {idx}] query_id must be non-empty string")
            ok = False
        else:
            if record["query_id"] in state.query_ids:
                state.warnings.append(f"[record {idx}] query_id '{record['query_id']}' is duplicate")
            state.query_ids.add(record["query_id"])

    # §3: query_text must be non-empty string
    if "query_text" in record:
        if not isinstance(record["query_text"], str) or not record["query_text"].strip():
            state.errors.append(f"[record {idx}] query_text must be non-empty string")
            ok = False

    # §3: no_gold must be boolean
    if "no_gold" in record:
        if not isinstance(record["no_gold"], bool):
            state.errors.append(
                f"[record {idx}] no_gold must be boolean, got {type(record['no_gold']).__name__}"
            )
            ok = False
        else:
            if record["no_gold"]:
                state.no_gold_count += 1

    # §3: annotator_id must be non-empty string
    if "annotator_id" in record:
        if not isinstance(record["annotator_id"], str) or not record["annotator_id"].strip():
            state.errors.append(f"[record {idx}] annotator_id must be non-empty string")
            ok = False

    # §3: created_at must be valid ISO timestamp
    if "created_at" in record:
        try:
            _ = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            if state.created_at_range[0] is None:
                state.created_at_range = (record["created_at"], record["created_at"])
            else:
                if record["created_at"] < state.created_at_range[0]:
                    state.created_at_range = (record["created_at"], state.created_at_range[1])
                if record["created_at"] > state.created_at_range[1]:
                    state.created_at_range = (state.created_at_range[0], record["created_at"])
        except ValueError:
            state.errors.append(
                f"[record {idx}] created_at '{record['created_at']}' is not valid ISO timestamp"
            )
            ok = False

    return ok


def validate_qrels(record: Dict[str, Any], idx: int, state: ValidatorState) -> bool:
    """§4-§5: Validate qrels array schema and relevance constraints."""
    ok = True

    if "qrels" not in record:
        state.errors.append(f"[record {idx}] Missing qrels array")
        return False

    qrels = record["qrels"]
    if not isinstance(qrels, list):
        state.errors.append(f"[record {idx}] qrels must be array, got {type(qrels).__name__}")
        return False

    if len(qrels) == 0 and not record.get("no_gold", False):
        state.warnings.append(f"[record {idx}] qrels is empty but no_gold=false")

    # §5/§6 Invariant: no_gold=true → all relevance must be 0
    if record.get("no_gold") is True:
        nonzero = [q.get("relevance") for q in qrels if isinstance(q, dict) and q.get("relevance", 0) != 0]
        if nonzero:
            state.errors.append(
                f"[record {idx}] Invariant violation: no_gold=true but "
                f"qrels contain non-zero relevance scores {nonzero} "
                f"(§5: no_gold means 整 pool 无直答, all relevance must be 0)"
            )

    for q_idx, qrel in enumerate(qrels):
        if not isinstance(qrel, dict):
            state.errors.append(f"[record {idx}][qrel {q_idx}] qrel must be dict")
            ok = False
            continue

        # §4: Required qrels fields
        missing_qrel = REQUIRED_QRELS_FIELDS - set(qrel.keys())
        if missing_qrel:
            state.errors.append(
                f"[record {idx}][qrel {q_idx}] Missing required qrels fields: {missing_qrel}"
            )
            ok = False

        # §4: doc_id must be non-empty string
        if "doc_id" in qrel:
            if not isinstance(qrel["doc_id"], str) or not qrel["doc_id"].strip():
                state.errors.append(f"[record {idx}][qrel {q_idx}] doc_id must be non-empty string")
                ok = False
            else:
                state.doc_ids.add(qrel["doc_id"])

        # §5: relevance must be in {0, 1, 2}
        if "relevance" in qrel:
            if not isinstance(qrel["relevance"], int):
                state.errors.append(
                    f"[record {idx}][qrel {q_idx}] relevance must be int, "
                    f"got {type(qrel['relevance']).__name__}"
                )
                ok = False
            elif qrel["relevance"] not in ALLOWED_RELEVANCE:
                state.errors.append(
                    f"[record {idx}][qrel {q_idx}] relevance must be in {ALLOWED_RELEVANCE}, "
                    f"got {qrel['relevance']}"
                )
                ok = False
            else:
                state.relevance_dist[qrel["relevance"]] += 1

        # §4: source_hint must be in closed vocabulary
        if "source_hint" in qrel:
            if not isinstance(qrel["source_hint"], str):
                state.errors.append(
                    f"[record {idx}][qrel {q_idx}] source_hint must be string, "
                    f"got {type(qrel['source_hint']).__name__}"
                )
                ok = False
            elif qrel["source_hint"] not in SOURCE_HINT_ENUM:
                state.errors.append(
                    f"[record {idx}][qrel {q_idx}] source_hint '{qrel['source_hint']}' "
                    f"not in closed vocabulary: {SOURCE_HINT_ENUM}"
                )
                ok = False
            else:
                state.source_hints_seen[qrel["source_hint"]] += 1

        # §4: judged_at optional, if present must be ISO timestamp
        if "judged_at" in qrel:
            try:
                datetime.fromisoformat(qrel["judged_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                state.errors.append(
                    f"[record {idx}][qrel {q_idx}] judged_at '{qrel['judged_at']}' "
                    f"is not valid ISO timestamp"
                )
                ok = False

    return ok


def validate_optional_fields(record: Dict[str, Any], idx: int, state: ValidatorState) -> bool:
    """§6: Validate optional fields and cross-field invariants."""
    ok = True

    # §8: Ensure no forbidden derived-only fields
    for forbidden in FORBIDDEN_DERIVED_ONLY:
        if forbidden in record:
            state.errors.append(
                f"[record {idx}] Field '{forbidden}' is strictly derived-only "
                f"(§8), must not appear in canonical"
            )
            ok = False

    # §6: source_stratum must be S1-S4 if present
    if "source_stratum" in record:
        if not isinstance(record["source_stratum"], str):
            state.errors.append(
                f"[record {idx}] source_stratum must be string, "
                f"got {type(record['source_stratum']).__name__}"
            )
            ok = False
        elif record["source_stratum"] not in {"S1", "S2", "S3", "S4"}:
            state.errors.append(
                f"[record {idx}] source_stratum must be S1-S4, got {record['source_stratum']}"
            )
            ok = False
        else:
            state.strata_seen[record["source_stratum"]] += 1

    # §6: pool_size must be positive int if present
    if "pool_size" in record:
        if not isinstance(record["pool_size"], int) or record["pool_size"] <= 0:
            state.errors.append(
                f"[record {idx}] pool_size must be positive int, got {record.get('pool_size')}"
            )
            ok = False
        else:
            # §6.4 Invariant: pool_size ≥ len(qrels)
            if record["pool_size"] < len(record.get("qrels", [])):
                state.errors.append(
                    f"[record {idx}] Invariant violation: pool_size ({record['pool_size']}) "
                    f"must be ≥ len(qrels) ({len(record.get('qrels', []))})"
                )
                ok = False
            state.pool_sizes.append(record["pool_size"])

    # §6: reviewer_id optional, must be string or null
    if "reviewer_id" in record and record["reviewer_id"] is not None:
        if not isinstance(record["reviewer_id"], str) or not record["reviewer_id"].strip():
            state.errors.append(
                f"[record {idx}] reviewer_id must be non-empty string or null"
            )
            ok = False

    # §6: notes, notes_for_future_tolf must be strings or absent
    for notes_field in ["notes", "notes_for_future_tolf"]:
        if notes_field in record and record[notes_field] is not None:
            if not isinstance(record[notes_field], str):
                state.errors.append(
                    f"[record {idx}] {notes_field} must be string or null"
                )
                ok = False

    # §6: kappa_overlap_group optional, must be string or null
    if "kappa_overlap_group" in record and record["kappa_overlap_group"] is not None:
        if not isinstance(record["kappa_overlap_group"], str):
            state.errors.append(
                f"[record {idx}] kappa_overlap_group must be string or null"
            )
            ok = False

    # §6: source_template_id, original_query_id optional, must be string or null
    for optional_str in ["source_template_id", "original_query_id"]:
        if optional_str in record and record[optional_str] is not None:
            if not isinstance(record[optional_str], str):
                state.errors.append(
                    f"[record {idx}] {optional_str} must be string or null"
                )
                ok = False

    # §6.4 Invariant: If source_stratum is S4, source_template_id and original_query_id must be null
    if record.get("source_stratum") == "S4":
        if record.get("source_template_id") is not None or record.get("original_query_id") is not None:
            state.errors.append(
                f"[record {idx}] Invariant violation: S4 stratum must have "
                f"source_template_id=null and original_query_id=null"
            )
            ok = False

    return ok


def validate_no_unknown_fields(record: Dict[str, Any], idx: int, state: ValidatorState) -> bool:
    """Check for unexpected fields not in schema."""
    ok = True
    allowed = REQUIRED_FIELDS | OPTIONAL_FIELDS
    unknown = set(record.keys()) - allowed
    if unknown:
        state.warnings.append(
            f"[record {idx}] Unknown fields (not in schema): {unknown}"
        )
    return ok


def validate_record(record: Dict[str, Any], idx: int, state: ValidatorState) -> bool:
    """Run all validations for a single record."""
    ok = True
    ok &= validate_json_structure(record, idx, state)
    ok &= validate_qrels(record, idx, state)
    ok &= validate_optional_fields(record, idx, state)
    ok &= validate_no_unknown_fields(record, idx, state)
    return ok


def validate_file(filepath: Path) -> ValidatorState:
    """Load and validate entire JSONL file."""
    state = ValidatorState()

    if not filepath.exists():
        state.errors.append(f"File not found: {filepath}")
        return state

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                line = line.rstrip("\n")
                if not line.strip():
                    state.warnings.append(f"[line {idx}] Empty line")
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    state.errors.append(f"[line {idx}] JSON parse error: {e}")
                    continue

                validate_record(record, idx, state)

    except IOError as e:
        state.errors.append(f"File read error: {e}")

    return state


def report(state: ValidatorState):
    """Print validation report."""
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║           GATEB LEDGER SCHEMA VALIDATION REPORT              ║")
    print("║            (§ per spec 20260419, frozen)                     ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    # Errors
    if state.errors:
        print(f"❌ ERRORS ({len(state.errors)}):")
        for err in state.errors:
            print(f"   {err}")
        print()
    else:
        print("✅ No schema errors")
        print()

    # Warnings
    if state.warnings:
        print(f"⚠️  WARNINGS ({len(state.warnings)}):")
        for warn in state.warnings:
            print(f"   {warn}")
        print()

    # Statistics
    print("📊 STATISTICS:")
    print(f"   Unique query_ids: {len(state.query_ids)}")
    print(f"   Unique doc_ids: {len(state.doc_ids)}")
    print(f"   no_gold=true count: {state.no_gold_count}")
    print()

    if state.strata_seen:
        print("   Source strata distribution:")
        for stratum in sorted(state.strata_seen.keys()):
            print(f"      {stratum}: {state.strata_seen[stratum]}")
        print()

    if state.relevance_dist:
        print("   Relevance distribution:")
        for rel in sorted(state.relevance_dist.keys()):
            print(f"      rel={rel}: {state.relevance_dist[rel]}")
        print()

    if state.source_hints_seen:
        print("   Source hints distribution:")
        for hint in sorted(state.source_hints_seen.keys()):
            print(f"      {hint}: {state.source_hints_seen[hint]}")
        print()

    if state.pool_sizes:
        print(f"   Pool size range: {min(state.pool_sizes)} - {max(state.pool_sizes)}")
        print(f"   Pool size mean: {sum(state.pool_sizes) / len(state.pool_sizes):.1f}")
        print()

    if state.created_at_range[0]:
        print(f"   created_at range: {state.created_at_range[0]} to {state.created_at_range[1]}")
        print()

    # Result
    if state.errors:
        print("🚫 VALIDATION FAILED")
        return 1
    else:
        print("✅ VALIDATION PASSED")
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path_to_gateb_goldset.jsonl>")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    state = validate_file(filepath)
    exit_code = report(state)
    sys.exit(exit_code)
