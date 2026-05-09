# Literature Data Map

Generated: 2026-04-20

## Scan Scope
- Extensions: .json, .jsonl, .csv, .txt
- Locations:
  - C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\output (historical extraction output)
  - D:\zotero\zoterodate\storage (Zotero library storage)
- Sampling approach:
  - Full extension scan for counts and file paths.
  - Structure sampling from:
    - output\batch_process_109papers_results.json (batch summary)
    - one representative item folder: output\batch_test_109papers\28PK8JFB\{paper-title}
    - one representative jasminum-outline.json in Zotero storage (all 83 are the same filename)

## Summary
- output: 895 files (894 .json, 1 .txt). Dominant structure is batch summary plus per-paper folders with multiple JSON artifacts.
- Zotero storage: 815 total files; mostly attachments (.pdf, .zotero-ft-cache, .zotero-reader-state, .html). Structured exports are limited to 83 jasminum-outline.json files (no .csv/.txt/.jsonl found).

## Output folder findings (historical extraction artifacts)

### batch_process_109papers_results.json
- Path: C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\output\batch_process_109papers_results.json
- Sample fields (first 5 lines): timestamp, total_attempted, success_count, error_count.
- Notes: run-level summary of batch extraction outcome.

### Per-paper artifacts
- Path pattern: C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\output\batch_test_109papers\<ZOTERO_KEY>\<PAPER_TITLE>\
- Files observed in a representative folder:
  - 01_full_extract.json
    - Sample fields: source_pdf, chunks[] (objects include chunk_id; chunk text likely deeper in file).
    - Keyword-prefilter relevance: chunks text is a likely target; source_pdf path includes title/year.
  - 02_hybrid_retrieval.json
    - Sample fields: status, focus_points[].
  - 02_writing_material_pack.json
    - Sample fields: goal, goal_profile (method_focus, image_focus, ...).
  - 03_academic_scoring.json
    - Sample fields: scoring.goal, scoring.llm_status, scoring.goal_profile.
  - 04_causal_dag.json
    - Sample fields: nodes[] with id text (sentence-like content).
  - project_view.json
    - Sample fields: schema_version, source_pdf, goal, stage_manifest.
  - human_view.md (not in scan extensions) appears alongside JSONs as a human-readable summary.
- Explicit title/abstract/keywords/authors/year fields were not visible in the first 5 lines of sampled JSONs; may exist deeper in the files.

### Miscellaneous text
- Path: C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\output\mempalace\identity.txt
- Contents are system identity notes, not literature metadata.

## Zotero storage findings (library attachments)

### jasminum-outline.json (83 files)
- Path pattern: D:\zotero\zoterodate\storage\<ITEM_KEY>\jasminum-outline.json
- Sample fields:
  - info: itemID, schema, jasminumVersion, baseFontSize
  - outline[] entries: level, title, page, x, y, children
- This appears to be a PDF outline/TOC structure; no abstract/keywords/authors/year fields visible in the sampled record.

### Attachment-heavy structure (explicit)
- The storage folder is dominated by attachments (PDFs and Zotero cache/reader-state files).
- Typical layout: D:\zotero\zoterodate\storage\<8-char-key>\{PDF/HTML/etc} plus optional jasminum-outline.json.

## Keyword-prefilter relevance callouts
- Best candidate fields for keyword prefilter in output artifacts:
  - 01_full_extract.json → chunks[] (likely text), source_pdf path.
  - 02_hybrid_retrieval.json → focus_points[] (keyword hints).
  - project_view.json → goal, stage_manifest (potential metadata map).
- Zotero jasminum-outline.json provides section titles only; useful for coarse outline cues, not full metadata (no abstract/keywords/authors/year in sample).
