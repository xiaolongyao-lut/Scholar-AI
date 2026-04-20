# Oracle History

## Project Context

- Project: my-project
- Owner: xiao
- Preferred role: data generation, label work, and benchmark support

## Learnings

- User explicitly wants a dedicated data specialist for tasks like generating structured batches or evaluation datasets.
- Data work should be routed early instead of being treated as cleanup after implementation.

### Phase 4: Real-Record Validation (2026-04-20)
- **Key discovery:** "Record" in extraction pipeline context means a single chunk, not a full paper. Each chunk retains source PDF and paper title as metadata.
- **Sampling insight:** Introduction chunks are meta-heavy (journal headers, conference markers). Full-paper validation would need chunks from body and methods sections for complete keyword coverage.
- **Filter confidence:** `keyword_prefilter.py` correctly implements OR semantics, case-insensitive substring matching, and Unicode normalization. Tested against 10 real samples across 3 scenarios; zero false positives, appropriate recall rate (70% on high-relevance keywords, 10% on specific parameters, 0% on rare technologies).
- **Unicode handling:** Mixed English/Chinese titles, chunk text, and PDFs processed without encoding errors. NFKC normalization is working as intended.
- **Next-phase readiness:** Function is production-ready for retrieval pipeline. Recommend chunk-level granularity for search (not full-paper aggregation) to maximize precision.

### Phase 5: Real-Data Extraction Validation (2026-04-21)
- **Scope:** Validated `extract_literature_context()` on 109 laser-processing papers (13,926 chunks total)
- **High-relevance keywords test:** ["laser", "nitriding", "surface"] → 3,584 items from 282 files (25.7% of baseline). Content distribution: 95% chunks, 3% focus_points, 2% titles.
- **Technical parameters test:** ["temperature", "hardness", "scanning speed"] → 1,317 items from 97 files (9.5% of baseline). Higher precision due to parameter-specific matching.
- **Irrelevant keyword test:** ["PTFE"] → 0 items extracted. Confirmed files without matches are NOT expanded (efficiency goal met).
- **Provenance preservation:** 100% of 2,835+ sampled items retain full provenance (source_file, relative_path, chunk_id, section_title). All items conform to output schema.
- **Unicode coverage:** Zero encoding failures on mixed English/Chinese text; NFKC normalization working correctly across all 109 papers.
- **Content type distribution:** full_extract (94%), hybrid_retrieval (5%), writing_material_pack (1%) across entire dataset.
- **Item schema:** All extracted items include content, content_type, provenance (source_root, path, record_type), and metadata (chunk_id, chunk_index where applicable).
- **Production readiness:** Function is PASS for retrieval pipeline. Recommend adding ranking layer in next phase for result ordering.

### Phase U1: Eval Audit + Full-Run Kickoff (2026-04-20)
- **Canonical query count:** `eval_queries_v2.1.jsonl` currently contains 3,269 queries, not the stale `414q` wording in `docs/superpowers/plans/2026-04-20-latest-unified-plan.md`.
- **Audit result:** Reproduced `output/eval_query_audit_v21.json` and `output/eval_query_audit_v21_template_flags.jsonl`; both are non-empty and report `matched=3269`, `missing=0`.
- **Validation command:** `pytest tests\test_eval_dataset_audit.py tests\test_eval_runtime.py -q` passed `17/17`, confirming audit + template-bucket eval wiring before the long run.
- **Execution pattern:** Full eval should be launched with explicit metrics output plus heartbeat logging: `python eval_retrieval_runtime.py --queries eval_queries_v2.1.jsonl --template-flags output/eval_query_audit_v21_template_flags.jsonl --output output/v21_full_eval_canonical.json --progress output/v21_full_eval_canonical.progress.jsonl --progress-every 25`.
- **Operational caveat:** For persistence, the first attached run was replaced by a detached run; the shared progress file now contains both stopped-run and live-run heartbeats, so future monitoring must read the newest timestamps only.

### U1 Step 2 & 3 Checkpoint (2026-04-20)
- **U1 Step 2 COMPLETE:** Canonical audit artifacts finalized and validated; all wiring tests pass.
- **U1 Step 3 IN PROGRESS:** Full eval launched as detached background job with `--progress` and `--progress-every 25` flags for observability.
- **Oracle responsibilities:** Monitor `output/v21_full_eval_canonical.progress.jsonl` for heartbeat freshness; validate metrics JSON when written; extract Recall@5, MRR, per_template_bucket for Tank approval.
- **Tank approval gate:** 11-point checklist (A1–A11) including artifact presence, query count match (3269), Tier 2 gate pass (Recall@5 ≥ 0.45, MRR ≥ 0.30), and run integrity verification.
- **Critical path:** Awaiting metrics file completion; 60-min hard timeout enforced; single-process ownership required per supervision rule.
