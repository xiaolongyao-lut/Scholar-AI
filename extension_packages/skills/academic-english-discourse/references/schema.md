# Academic English Discourse Database Schema

The builder writes all generated data to:

```text
workspace_artifacts/generated/output/english_discourse/
```

## `manifest.json`

Build-level metadata.

Required fields:

- `schema_version`: current schema version.
- `built_at`: UTC ISO timestamp.
- `builder_version`: script version.
- `sources`: source-level metadata.
- `counts`: record counts.
- `outputs`: generated file paths.
- `settings`: chunking and extraction settings.

Expected output keys:

- `chunks_jsonl`
- `phrases_jsonl`
- `discourse_frames_json`
- `academic_english_habits_json`
- `sqlite`
- `manifest`
- `report`

## `chunks.jsonl`

One JSON object per discourse chunk.

Required fields:

- `chunk_id`: stable SHA-256-derived id.
- `source_id`: source record id.
- `source_type`: `pdf`, `ocr_pdf`, `text`, or `phrasebank`.
- `title`: source title.
- `locator`: page, URL, or local section locator.
- `section`: detected local section label.
- `text`: cleaned local chunk text unless `--distilled-only` was used.
- `summary`: compact rule-based summary for search previews.
- `rhetorical_moves`: detected discourse moves.
- `features`: detected academic style features.
- `keywords`: compact keyword list.
- `char_count`: character count.
- `word_count`: whitespace token count.

## `phrases.jsonl`

One JSON object per reusable academic wording pattern.

Required fields:

- `phrase_id`: stable SHA-256-derived id.
- `source_id`: source record id.
- `source_type`: `pdf`, `ocr_pdf`, `text`, or `phrasebank`.
- `text`: phrase or sentence pattern.
- `normalized`: lowercase normalized phrase.
- `move`: primary discourse move.
- `features`: style features.
- `section`: source section or inferred function.
- `locator`: page, URL, or local section locator.
- `adaptation_note`: Chinese note describing how to adapt the pattern.

## `discourse_frames.json`

Curated move-level guidance. Each item includes:

- `move`
- `cn_name`
- `purpose`
- `when_to_use`
- `translation_strategy`
- `quality_checks`
- `starter_patterns`

These starter patterns are generic writing frames. The database search should still retrieve local examples before final rewriting.

## `academic_english_habits.json`

Distilled academic-English knowledge used before phrase retrieval. This file is local abstract guidance, not copied source text.

Required fields:

- `schema_version`: current schema version.
- `knowledge_type`: always `academic_english_habits`.
- `policy_markdown`: full text of `english_discourse_habits.md`, used as the authoritative runtime policy.
- `policy_source`: relative source path for policy provenance.
- `policy_loaded`: whether the build successfully read the Markdown policy.
- `purpose`: short description of how the knowledge should be used.
- `source_principles`: move-first planning, old-to-new information flow, evidence scoping, certainty calibration, terminology stability, and synthesis over listing.
- `sentence_diagnostics`: checks to apply before accepting a generated sentence.
- `translation_rewrite_rules`: Chinese-to-English restructuring rules.
- `paragraph_protocols`: paragraph-level workflows for literature review, translation, and discussion prose.
- `lexical_calibration`: verb and modality groups by evidence strength.
- `quality_floor`: minimum acceptance requirements for generated prose.

Suggested loading order:

0. Read `policy_markdown`; it is the authoritative strategy text for this knowledge file.
1. Read `academic_english_habits.json`.
2. Select one or more moves from `discourse_frames.json`.
3. Retrieve matching examples from SQLite, `chunks.jsonl`, or `phrases.jsonl`.
4. Generate adapted language and run `sentence_diagnostics`.

## SQLite

`academic_english_discourse.sqlite3` mirrors the JSONL files.

Tables:

- `sources`
- `chunks`
- `phrases`
- `build_meta`
- `chunks_fts`, when SQLite FTS5 is available
- `phrases_fts`, when SQLite FTS5 is available

Suggested retrieval:

```sql
SELECT chunk_id, title, locator, section, summary
FROM chunks_fts
JOIN chunks USING(rowid)
WHERE chunks_fts MATCH ?
LIMIT 8;
```

If FTS5 is unavailable, use `LIKE` over `chunks.text`, `chunks.summary`, and `phrases.text`.
