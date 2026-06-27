---
id: "academic-english-discourse"
name: "Academic English Discourse"
version: "0.2.0"
kind: "style"
description: "Academic English discourse database and writing guidance for literature review drafting and EN/CN translation in Scholar AI."
entry_mode: "assistant"
ui_visibility: "skill_assisted"
display_group: "writing"
experimental: false
supported_scopes:
  - "selection"
  - "paragraph"
  - "section"
  - "full_draft"
tags:
  - "academic-writing"
  - "translation"
  - "literature-review"
  - "phrasebank"
permissions:
  model.llm: true
  retrieval.read: true
  draft.read: true
  draft.write: true
  files.read: true
  files.write: true
  network: true
  script.execute: true
  storage: true
script_policy:
  has_scripts: true
  safe_to_execute: false
model_policy:
  allow_llm: true
  allow_embedding: false
root_policy:
  allowed_roots:
    - "skill_root"
    - "project_root"
privacy_notes: "The generator writes source-derived chunks only to the local workspace_artifacts tree. Do not paste bulk source text into prompts or public artifacts."
rollback_hint: "Restore the package from .rollback_snapshots or delete workspace_artifacts/generated/output/english_discourse and rebuild from the original local sources."
---

# Academic English Discourse

Use this skill when Scholar AI needs to improve English academic writing, revise literature reviews, normalize scholarly terminology, or translate between Chinese and English while preserving disciplinary stance.

## Core Intent

This is a database-backed writing skill, not an agent workflow. It supplies a local discourse database and a compact writing protocol so Scholar AI can:

- choose the right rhetorical move before choosing wording;
- rewrite Chinese thought into English academic argument structure;
- make literature review prose more cautious, connective, and evidence-bound;
- keep translated terms stable across a draft;
- avoid generic "AI-polished" prose that sounds fluent but academically vague.

## Required Database

Build or refresh the local database with:

```powershell
& .\.venv-1\Scripts\python.exe .\extension_packages\skills\academic-english-discourse\scripts\build_discourse_db.py --downloads-preset --include-phrasebank --ocr-engine auto
```

The generated artifacts live under:

```text
workspace_artifacts/generated/output/english_discourse/
```

Expected outputs:

- `academic_english_discourse.sqlite3`
- `chunks.jsonl`
- `phrases.jsonl`
- `discourse_frames.json`
- `academic_english_habits.json`
- `manifest.json`
- `build_report.md`

PDFs with no selectable text are rendered page-by-page and passed through Windows OCR when `--ocr-engine auto` is used on Windows. The resulting records use `source_type="ocr_pdf"` so they remain auditable.

After editing `references/english_discourse_habits.md`, rebuild the database so `academic_english_habits.json.policy_markdown` contains the latest official policy text.

## Runtime Use

Load the knowledge in this order:

0. `academic_english_habits.json.policy_markdown` as the authoritative strategy text.
1. `academic_english_habits.json` structured fields for machine-readable checks.
2. `discourse_frames.json` for move-specific writing frames.
3. SQLite/JSONL records for source-derived examples and phrase patterns.

When revising or translating, first map the user request to a discourse function:

- `territory`: establish the research area.
- `gap`: identify an unresolved problem or limitation.
- `aim`: state what the paper or section does.
- `method`: describe design, materials, data, or procedure.
- `result`: report findings without overclaiming.
- `interpretation`: explain what a result means.
- `comparison`: compare studies, theories, datasets, or outcomes.
- `causality`: express mechanisms and causal relations cautiously.
- `limitation`: mark scope, uncertainty, or boundary conditions.
- `implication`: state contribution, usefulness, or future work.
- `transition`: move between claims or sections.
- `citation`: attribute claims and synthesize sources.

Then retrieve matching chunks or phrases from the local database and produce adapted language. Do not copy a phrase mechanically if it does not match the claim, tense, certainty, evidence type, or discipline.

## English Academic Habits

Use `references/english_discourse_habits.md` as the human-readable policy for this skill. The core habits are:

- choose the discourse move before choosing wording;
- order information from known context to new claim;
- bind every claim to evidence and scope;
- calibrate certainty through verbs and modality;
- keep technical terms stable across the draft;
- synthesize relations among studies instead of listing sources.

For Chinese-to-English work, rewrite the argument before polishing the surface. Typical conversions include:

- "说明/表明/证明" -> `suggests`, `indicates`, `shows`, or `demonstrates` by evidence strength;
- "研究不足" -> a specific gap in population, method, mechanism, dataset, theory, or context;
- "具有重要意义" -> a concrete implication rather than generic importance;
- "有研究表明" -> a reporting verb plus a source relation.

## Translation Protocol

For Chinese to English academic translation:

1. Identify the discourse move before translating sentence by sentence.
2. Convert Chinese topic-comment order into English claim-support order when needed.
3. Preserve hedging and evidence boundaries; add caution only when the Chinese claim is underspecified.
4. Stabilize key terms across the paragraph and avoid synonym drift for technical nouns.
5. Prefer active scholarly verbs for argumentation and passive/nominalized forms only when the method or object should be foregrounded.

For English to Chinese translation:

1. Preserve the rhetorical relation, not only the literal connector.
2. Keep terms stable and record alternative translations only when the field genuinely uses both.
3. Do not flatten hedging; distinguish "may", "might", "suggest", "indicate", "demonstrate", and "show".

## Output Discipline

Good output should be:

- move-aware: the sentence has an identifiable academic function;
- evidence-bound: claims are scoped to the cited study, dataset, or review;
- cautious but not weak: hedge uncertainty, not established facts;
- cohesive: old information leads to new information;
- terminologically stable: one concept keeps one English form unless a distinction is needed.

See `prompts/main.txt` for the full prompt, `references/english_discourse_habits.md` for the distilled habits, and `references/schema.md` for the database schema.
