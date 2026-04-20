# Morpheus History

## Project Context

- Project: my-project
- Owner: xiao
- Team pattern: architecture → implementation → testing → data
- Preferred responsibility: review cross-domain changes before they land

## Learnings

- User prefers a model-specialized team rather than generic role rotation.
- Team members should honor the same Copilot rules, skills, and shared conventions as the main session.
- Startup self-check pattern: read SESSION_SNAPSHOT → OPEN_THREADS → requirement-pool; close drift items with file evidence; update DECISION_TRAIL before any implementation begins.
- SESSION_SNAPSHOT Open section had two items that were already resolved in prior sessions but never closed — always verify Open items against actual file state before trusting them.
- Key file paths for self-check: `.squad/memory/SESSION_SNAPSHOT.md`, `.squad/memory/OPEN_THREADS.md`, `.squad/identity/requirement-pool.md`, `.squad/memory/DECISION_TRAIL.md`.
- Phase close procedure: DECISION_TRAIL append → SESSION_SNAPSHOT Next update → OPEN_THREADS review → checkpoint copy `.squad/memory/` → `.squad/backups/checkpoint-phaseX-<timestamp>/`. Decision inbox note if team-relevant.
- Phase 2 close observation: keyword_filter.py is a pure function with no I/O, no deps, 73 field-name variants (EN+CN). This means Tank can unit-test it in isolation without mocking. The field-name set covers output/ artifact field names — integration with existing data is zero-friction.
- Phase 1 discovery result: no pre-existing literature data files in the repo. This is expected — the system design centers on runtime ingestion from user-provided folders, not bundled datasets.
- OPEN_THREADS should only gain entries for genuine downstream blockers; "no data files found" is an architectural fact, not a blocker when the design already anticipates runtime ingestion.
- **Phase 1 refreshed conclusion (2026-04-20):** Real data sources confirmed externally. `output/` = 894 JSON historical extraction artifacts (multi-stage pipeline outputs). `D:\zotero\zoterodate\storage` = 815 files (PDFs + 83 jasminum-outline.json outlines). User clarified: output/ is historical extraction product, Zotero storage is the literature library.
- **Data structure insight:** output/ per-paper artifacts follow a numbered stage pattern (01_full_extract → 02_hybrid_retrieval → 03_academic_scoring → 04_causal_dag → project_view). This is a strong design reference for Phase 2 pipeline architecture.
- **Metadata gap:** jasminum-outline.json only contains PDF TOC structure (level/title/page), not structured metadata (abstract/keywords/authors/year). This is a genuine constraint for any phase requiring structured bibliographic metadata.
- **Phase close refresh pattern:** When discovery data is corrected, update all four memory files, create a new timestamped checkpoint, and record the correction explicitly in DECISION_TRAIL. Old checkpoints are preserved for audit trail.
- **Phase 3 test quality observation:** Tests that include explicit assertion messages documenting contract assumptions (e.g., "Contract is OR-based; AND is not required.") serve double duty as executable specification and integration-readiness documentation. Worth encouraging in future test reviews.
- **Pure function testing advantage:** keyword_prefilter's pure function design (no I/O, no deps, no state) allowed 6 tests to run in 0.05s with zero setup. This validates the Phase 2 design decision to keep the module stateless.
- **Phase 3 checkpoint:** `.squad/backups/checkpoint-phase3-20260420-0349/`
- **Phase 4 validation outcome:** Oracle validated keyword_prefilter against 10 real extraction records (3 scenarios). All PASS. No new constraints. The module is triple-confirmed (impl → unit test → real data) and ready for pipeline integration.
- **Validation report quality:** Oracle's report includes clear scenario hypotheses, match counts, per-record analysis, and explicit strength/edge-case sections. This format is worth reusing for future validation tasks.
- **Phase 4 checkpoint:** `.squad/backups/checkpoint-phase4-20260420-0352/`
- **Phase 5 close procedure:** Verified that README.md and DECISION_TRAIL.md already contained integrated Phase 1-4 content before marking Phase 5 complete. Phase close = confirm deliverables → update memory files → checkpoint → inbox note. No implementation work needed when documentation was already done by the executing agent.
- **Documentation baseline pattern:** When a documentation phase closes, record in SESSION_SNAPSHOT Next that future modules should update the same README section as they land. This prevents documentation drift from accumulating across phases.
- **Phase 5 checkpoint:** `.squad/backups/checkpoint-phase5-20260420-0356/`
- **Phase 6 close observation:** The real-shape regression test bridges the gap between simplified dict unit tests and Oracle's real-data validation. It exercises recursive descent on nested structures (chunks, focus_points, stage_manifest) using shapes that mirror actual output/ artifacts. This is the pattern documented in `project-conventions/SKILL.md` under "Mirror real record shapes in regressions."
- **Phase 6 checkpoint:** `.squad/backups/checkpoint-phase6-20260420-0359/`
- **Five-layer validation chain:** keyword_prefilter now has implementation → unit tests → real-data validation → documentation integration → real-shape regression. This chain pattern is worth reusing for future pipeline modules.
- **Phase close loop discipline:** After Phase 6, the Next pointer in SESSION_SNAPSHOT should direct to the next phase-plan deliverable that is safe for autonomous execution. Folder traversal is the clear next candidate — it's within phase scope, requires no refactor, and has no new dependencies.
- **Folder traversal close (2026-04-20):** `src/folder_traversal.py` implements `collect_folder_records` (alias `traverse_folder`). Recognizes 7 real artifact types. Integrates keyword_prefilter when keywords supplied. 4/4 tests pass; joint with keyword_filter = 11/11 green (0.07s). Checkpoint: `.squad/backups/checkpoint-phase6-traversal-20260420-0408/`.
- **Pipeline front-end complete:** keyword_prefilter + folder_traversal = the first two stages of the retrieval pipeline are integrated, tested, and documented. No new dependencies needed.
- **Next task routing:** "Extraction pipeline" from phase-plan needs scope clarification before dispatch — if it requires PDF parsing libs, it's a hard-stop dependency decision. Safe alternatives: Tank tests or Oracle real-data validation for folder_traversal.
- **Extraction pipeline close (2026-04-20):** `src/extraction_pipeline.py` implements `extract_literature_context(folder_paths, keywords=None, allowed_extensions=None)`. Three-layer orchestration: folder_traversal → keyword_prefilter → segment-level extraction. Content priority: chunks > focus_points > abstract > title. Segment-level keyword re-matching via `_segment_matches`. 2/2 tests pass; joint suite = 13/13 green (0.08s). No new dependencies. Checkpoint: `.squad/backups/checkpoint-phase6-extraction-20260420-0414/`.
- **Extraction scope decision:** extraction_pipeline does NOT include PDF parsing. Scope is limited to orchestrating existing modules over already-loaded records (JSON/JSONL/CSV/TXT). PDF parsing would require new dependencies (hard-stop class).
- **Pipeline completion:** All three Must Deliver pipeline modules done: keyword_prefilter + folder_traversal + extraction_pipeline = 13/13 green. The remaining Must Deliver ("Intelligent chat") requires LLM integration — hard-stop decision domain.
- **Next safe tasks after extraction:** (1) Tank edge-case tests for extraction_pipeline (2) Oracle real-data validation for extraction_pipeline (3) README update with extraction pipeline section. All three are dependency-free and non-refactor.
- **Night-shift final closure (2026-04-20):** All safe autonomous work completed. Tank added 3 boundary tests (16/16 total). Oracle validated on 109 real papers (4 scenarios, PASS). README updated with extraction validation chapter + corrected test counts. HARD-STOP escalated: "Intelligent chat" requires LLM dependency — WAITING FOR USER.
- **Production readiness chain:** The full validation chain for the retrieval pipeline is: implementation → unit tests → boundary tests → real-data validation (109 papers) → documentation integration. This five-layer pattern should be the standard for future modules.
- **Final checkpoint:** `.squad/backups/checkpoint-phase6-final-20260420-0418/`
- **Oracle validation report format:** The extraction validation report is significantly more detailed than the prefilter validation report (4 scenarios, provenance analysis, schema validation, item shape contract, limitations section). This format is the new gold standard for module validation reports.
- **Unified-plan dispatch rule (2026-04-20):** Before dispatching from a merged plan, reconcile plan wording against repo-local artifacts. For U1, `eval_queries_v2.1.jsonl` is 3269 lines, prior Wave 1 audit artifacts already exist under `artifacts/eval_audit\`, and the real missing step is canonicalizing/rerunning outputs into `output\` plus refreshed full-eval evidence.
- **Unified-plan gate rule (2026-04-20):** Treat conversation persistence U2 as a storage/API hard-stop even when the design doc is complete. `.modular/sessions/index.sqlite3`, transcript/checkpoint/blob layout, and new session endpoints must be gated before any frontend U3 work starts.
