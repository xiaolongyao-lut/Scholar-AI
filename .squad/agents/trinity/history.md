# Trinity History

## Project Context

- Project: my-project
- Owner: xiao
- Preferred role: main coding engine for the team

## Learnings

- User wants implementation to sit primarily with GPT-5.4.
- Team members should reuse project rules and skills instead of coding from isolated local assumptions.
- Implemented Phase 1 LiteLLM gateway with env-driven configs, added .env.example and tests.

- Phase 1 discovery found no literature data files in data/output/resources or repo root; report at .squad/discovery/literature-data-map.md.
- Real data scan: C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\output contains batch extraction JSONs (batch_process_109papers_results.json and per-paper artifacts under batch_test_109papers\<key>\<paper-title>\).
- Zotero storage at D:\zotero\zoterodate\storage is attachment-heavy (mostly PDFs/caches) with 83 jasminum-outline.json outline files; limited structured metadata fields in samples.
- Implemented src/keyword_filter.py keyword_prefilter with Unicode-normalized substring matching across title/abstract/keywords-like keys (incl. Chinese) and nested structures.
- Implemented src/folder_traversal.py for lightweight folder traversal (json/jsonl/csv/txt), traceable record fields (source_root/path/relative_path/record_type), and keyword_prefilter integration.
- Added traverse_folder alias in src/folder_traversal.py to align traversal tests with the public entrypoint contract.
- Implemented src/extraction_pipeline.py with extract_literature_context entrypoint, provenance-preserving context items, and keyword-aware lightweight extraction.
- Added tests/test_extraction_pipeline.py to verify keyword filtering, provenance visibility, and text extraction behavior.
- Updated README.md to document Phase 6 extraction pipeline integration.
- Added per-query JSONL persistence for eval runs via `--per-query-output` to preserve per-query quality evidence on interruption.

### 2026-04-20: Phase 1 LiteLLM Gateway Delivery

- Implemented `src/litellm_gateway.py`: Multi-provider LLM abstraction (OpenAI, Anthropic, Google)
- Created `.env.example`: Environment variable template for secure API key management
- Updated `requirements.txt`: Added litellm, python-dotenv dependencies
- Delivered `tests/test_litellm_gateway.py`: 21 passing tests covering all provider routes and error handling
- Documentation: Updated README.md with Phase 1-6 extraction pipeline integration notes
- **Status:** ✅ Ready for Morpheus Phase 1 architecture review (2026-04-25)

### 2026-04-20: Phase 2 Context Budget Delivery

- Implemented `src/context_budget.py`: Lightweight token budgeting for streaming LLM responses
- Updated `src/extraction_pipeline.py`: Integrated context budget awareness for batch extraction
- Delivered `tests/test_context_budget.py`: Full validation test suite (28 passing tests)
- **Key Integration:** Extraction pipeline now respects LLM context windows during batch operations
- **Status:** ✅ Phase 2 batch complete and tested. Awaiting Morpheus cross-domain review

- U1 retrieval gate artifacts now use `output\v21_full_eval_canonical.json` and `output\v21_full_eval_canonical.progress.jsonl` as the reviewer-facing canonical pair.
- `eval_query_audit_v21.json` is the authoritative source for v2.1 audit totals: 3269 total queries with hard=326, medium=1455, simple=1488.
- The completed v2.1 full eval remains far below gate (`Recall@5=0.0281`, `MRR=0.0204`), so U1 failure is genuine quality failure, not just artifact naming.
- For canonical progress evidence, use a single monotonic completed run only; appended mixed-run progress logs must be trimmed before review submission.

### 2026-04-20: U1 Step 3 Revision Ownership Handoff

- **Event:** Tank formal reviewer gate verdict: REJECTED (U1 Step 3)
- **Blockers:** (1) missing canonical metrics artifact `output/v21_full_eval_canonical.json`, (2) Tier 2 quality gate failure (Recall@5 0.0281 vs ≥0.45 required)
- **Lockout routing:** Oracle → Trinity (strict rejection lockout compliance)
- **Trinity ownership:** U1 revision cycle (full responsibility for remediation)
- **Mandatory deliverables:** canonical artifacts, contract coherence, run integrity, quality gate closure
- **Status:** Assigned; awaiting Trinity remediation submission
