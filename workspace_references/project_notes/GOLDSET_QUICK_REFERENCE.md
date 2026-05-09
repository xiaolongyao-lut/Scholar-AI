# Quick Reference: Goldset Schema & Validator

**For quick lookup while annotating.**

---

## Required Fields (Always Include)

```json
{
  "schema_version": "1",
  "query_id": "q_g0001",
  "query_text": "Your question here",
  "qrels": [{...}],
  "annotator_id": "your_id",
  "no_gold": false,
  "created_at": "2026-04-25T12:00:00Z"
}
```

---

## Qrels Structure (Each Item)

```json
{
  "doc_id": "mat_abc123def45",
  "relevance": 2,
  "source_hint": "bm25"
}
```

### Relevance Values
- `0` = Non-relevant (doesn't answer query)
- `1` = Marginally relevant (tangential, incomplete)
- `2` = Highly relevant (directly answers, strong evidence)

### Source Hint Values (Pick ONE)
```
"bm25"              ← keyword search
"dense"             ← embedding search
"rerank"            ← after reranking
"bm25+dense"        ← fusion
"bm25+graph"        ← keyword + graph
"evidence_set"      ← manual known-good
"unexpected_unknown_source"  ← other
```

---

## Optional Fields (Recommended)

```json
{
  "source_stratum": "S1",
  "source_template_id": "simple:1",
  "original_query_id": "q_orig_1",
  "reviewer_id": "reviewer_name",
  "notes": "Any annotation notes",
  "notes_for_future_tolf": "Graph structure hints",
  "pool_size": 10,
  "kappa_overlap_group": "batch_1",
  "judged_at": "2026-04-25T12:00:00Z"
}
```

### source_stratum Values
- `S1` = Simple keyword match
- `S2` = Moderate synthesis
- `S3` = Complex multi-paper reasoning
- `S4` = Free exploration / long-tail

---

## Validator Command

```bash
python gateb_schema_validator.py your_goldset.jsonl
```

**Output**: Errors (stop if any) + Warnings (info) + Statistics

---

## Common Validation Errors & Fixes

| Error | Fix |
|-------|-----|
| Missing required fields | Add: schema_version, query_id, query_text, qrels, annotator_id, no_gold, created_at |
| schema_version != "1" | Change to `"1"` |
| query_id is empty | Use non-empty string, e.g., `"q_g0001"` |
| query_text is empty | Use natural language question |
| relevance not in {0,1,2} | Use only 0 (non-relevant), 1 (marginal), 2 (relevant) |
| source_hint not in vocabulary | Use one of 7 values (see above) |
| no_gold=true but relevance>0 | If no_gold=true, all relevance must be 0 |
| pool_size < len(qrels) | Increase pool_size (must be ≥ number of qrels) |
| Invalid created_at | Use ISO 8601: `"2026-04-25T12:00:00Z"` |

---

## Coverage Checklist While Annotating

- [ ] Aim for ~20% simple (S1)
- [ ] Aim for ~40% moderate (S2)
- [ ] Aim for ~30% complex (S3)
- [ ] Aim for ~10% free exploration (S4)
- [ ] Relevance: 30–50% rel=0, 20–35% rel=1, 20–40% rel=2
- [ ] pool_size ≥ 10 for most queries
- [ ] No more than 5% with no_gold=true
- [ ] Each query has 1+ relevant doc (unless intentionally testing recall=0)

---

## Minimal Valid Record (Bare Minimum)

```json
{
  "schema_version": "1",
  "query_id": "q_g0001",
  "query_text": "What is laser welding?",
  "qrels": [{"doc_id": "mat_123", "relevance": 2, "source_hint": "bm25"}],
  "annotator_id": "you",
  "no_gold": false,
  "created_at": "2026-04-25T12:00:00Z"
}
```

**But you should also add** (strongly recommended):
```json
{
  "source_stratum": "S1",
  "pool_size": 5
}
```

---

## File Format

**JSONL** = JSON Lines (one JSON object per line, no commas between lines)

```
{"schema_version": "1", "query_id": "q_g0001", ...}
{"schema_version": "1", "query_id": "q_g0002", ...}
{"schema_version": "1", "query_id": "q_g0003", ...}
```

**NOT**:
```
[
  {...},
  {...}
]
```

---

## Annotation Tips

1. **Keep source_hint accurate** — helps understand where you found the doc
2. **Be realistic about relevance** — not everything is rel=2; most should be rel=0–1
3. **note the pool** — how many candidates did you consider? (pool_size)
4. **document ambiguity** — use `notes` field if judgment is unclear
5. **Validate early** — run validator after every 20–30 queries to catch format errors early

---

**Questions?** See the full goldset requirements package or ask Oracle.
