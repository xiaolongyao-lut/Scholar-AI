---
name: "data-validation"
description: "Validation patterns for extraction pipelines and data-oriented tasks"
domain: "data-engineering"
confidence: "medium"
source: "oracle-extraction-validation phase-5"
---

## Context

When validating data pipelines (extraction, transformation, filtering), establish reproducible test scenarios that exercise realistic data and measure correctness against explicit criteria.

## Patterns

### Multi-scenario validation strategy

Define at least 3-4 test scenarios that cover:
1. **High-relevance/high-recall case**: Data that should definitely match (domain keywords, common patterns)
2. **Specific/low-recall case**: Data with narrow, technical criteria (rare parameters, specific terms)
3. **Negative case**: Data that should NOT match (irrelevant keywords, out-of-domain concepts)
4. **Baseline case**: Full dataset with no filters, to establish upper bounds for comparison

**Example from extraction validation:**
- Scenario 1: ["laser", "nitriding", "surface"] → 3,584 items (25.7% of 13,926 baseline)
- Scenario 2: ["temperature", "hardness", "scanning speed"] → 1,317 items (9.5% of baseline)
- Scenario 3: ["PTFE"] → 0 items (correctly excluded)
- Baseline: None → 13,926 items (100% coverage)

### Item structure validation

For each extracted/transformed item, validate:
- **Required fields present**: content, content_type, provenance (or equivalent context)
- **Field types correct**: content is string, provenance is dict, metadata is dict (if present)
- **Provenance traceability**: source_file, path, or record_type to trace back to origin
- **Metadata completeness**: chunk_id, index, section, or equivalent granular identifiers

**Validation function pattern:**
```python
def validate_item_structure(item: dict[str, Any]) -> list[str]:
    """Return list of validation errors, empty if valid."""
    errors = []
    if "content" not in item or not isinstance(item["content"], str):
        errors.append("Missing or invalid 'content'")
    if "content_type" not in item:
        errors.append("Missing 'content_type'")
    if "provenance" not in item or not isinstance(item["provenance"], dict):
        errors.append("Invalid or missing 'provenance'")
    # ... more checks
    return errors
```

### Real-data sourcing first

- Prefer production/historical artifacts over synthetic fixtures
- Document the source folder, file count, record structure, and sampling method
- Establish a data inventory (file types, counts, schema samples)
- Run scenarios on the full real dataset if feasible; if too large, document sampling strategy

### Output metrics to track

For each scenario, report:
- **Total items**: Count of extracted/transformed records
- **Unique sources**: Number of distinct source files (to catch over-expansion)
- **Content type distribution**: Breakdown by item type (chunks vs. focus_points vs. titles, etc.)
- **Structure validity**: 100% should pass contract validation
- **Coverage ratios**: Percentage of baseline dataset matched (for filtering scenarios)

### Canonical artifact coherence gate

For long-running eval pipelines, validate **artifact chain coherence** before accepting results:
1. Required files must exist at the **contracted canonical paths** (do not accept alternate filenames as equivalent).
2. Progress evidence must terminate at the same `total_queries` as the accepted metrics file.
3. If a non-canonical metrics file is complete but canonical progress/metrics are partial, mark as reject until reconciled.
4. Apply threshold gates only after path and coherence gates pass, so pass/fail evidence is reproducible.
5. If a progress JSONL contains multiple appended runs, canonical evidence must keep **one monotonic completed run only** (typically the last coherent suffix ending at the expected total). Mixed-run progress logs are not reviewer-safe as-is.

### Interrupted-run evidence gate (anti money-burn)

For any run that may be interrupted, require two traces:
1. **Operational trace**: progress JSONL (`done/total/percent/last_query_id`) for heartbeat.
2. **Quality trace**: per-query JSONL with at least `query_id`, `recall_at_5`, `mrr`, `latency_ms`.

Acceptance rule:
- Interruption is reusable only if `last_progress.done == per_query_row_count` and partial metrics can be recomputed from persisted per-query rows.
- Progress-only artifacts are non-reusable for quality decisions and should be treated as failed evidence.

### Split-gate verdict pattern (contract vs quality)

When re-gating a revised evidence pack, report two explicit statuses:
1. **Contract/evidence-pack status** (artifact presence, naming, counts, required sections, monotonic completion).
2. **Quality-gate status** (threshold metrics such as Recall@5/MRR).

If contract passes but quality fails, keep overall verdict **REJECTED**, explicitly mark what is unblocked (contract checks) vs still blocked (quality acceptance) so downstream routing is deterministic.

### Filtering correctness pattern

When testing keyword/relevance filters:
1. Apply filter with keywords → measure filtered result count
2. Compare against baseline (no filter) → establish recall ratio
3. Test edge cases: rare keywords (should exclude files), common keywords (should be generous)
4. Verify non-matching files contribute zero items (efficiency goal)

### Provenance preservation checklist

For extraction pipelines, ensure every item retains:
- [ ] Source file path (absolute or relative)
- [ ] Record type (JSON type, file classification)
- [ ] Item-level identifiers (chunk_id, index, etc.)
- [ ] Section/context if applicable (section_title, document structure)
- [ ] Original source reference (PDF path, external link, etc.)

**Example:** Each chunk carries chunk_id, section_title, source_pdf, and source_file, allowing reconstruction of the original document structure.

### Reusability across similar pipelines

Document:
- File types encountered (JSON, JSONL, CSV, TXT)
- Schema variations handled (nested chunks, focus_points, metadata nesting)
- Encoding issues and how they were resolved (Unicode normalization, error handling)
- Edge cases found (malformed metadata, missing fields, type coercion)

These become regression tests and future validation baselines.

## Anti-Patterns

- Validating on toy/synthetic data only; miss real-world edge cases
- Running only happy-path scenarios; miss failure modes
- Checking only count; don't validate item schema correctness
- Forgetting to test with real folder structure and file organization
- Losing provenance; items that can't be traced back to origin are useless for retrieval
- Validating only one pass; establish baseline for comparison

## Example: Full Validation Script Structure

```python
def scenario_high_relevance():
    keywords = ["laser", "nitriding"]
    items = extract(keywords=keywords)
    return {
        "scenario": "High-relevance",
        "keywords": keywords,
        "total_items": len(items),
        "item_type_distribution": count_by_type(items),
        "structure_valid": validate_all(items),  # 100/100 items valid?
        "unique_sources": count_unique_sources(items),
    }

def scenario_negative():
    keywords = ["PTFE"]  # Not in dataset
    items = extract(keywords=keywords)
    assert len(items) == 0, "Should exclude non-matching files"

def scenario_baseline():
    items = extract(keywords=None)
    return {
        "total_items": len(items),
        "distribution": count_by_type(items),
    }

# Report
results = [
    scenario_high_relevance(),
    scenario_specific_params(),
    scenario_negative(),
    scenario_baseline(),
]
write_json("validation_results.json", results)
```

## References

- Real validation example: `.squad/discovery/oracle-extraction-validation-report.md`
- Test scripts: `validate_extraction.py`, `test_filtering.py`, `test_provenance.py` (my-project root)
