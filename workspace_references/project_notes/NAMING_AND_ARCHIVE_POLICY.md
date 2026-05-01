# Naming And Archive Policy

This document defines the repository-wide naming rules and historical-document rules for human contributors, Gemini, Copilot, Codex, and any other automation.

## 1. Mandatory pre-change guardrails

Before creating, renaming, moving, or deleting any code or documentation file:

1. Create a rollback snapshot under `.rollback_snapshots/<task>-<timestamp>/`.
2. Search official or primary sources before making structural decisions.
3. Prefer updating an existing canonical file over creating a new one.

Recommended primary references:

- [PEP 8](https://peps.python.org/pep-0008/)
- [Python importlib documentation](https://docs.python.org/3/library/importlib.html)
- [Python Packaging guidance](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

## 2. Root directory policy

The repository root is reserved for:

- active runtime entrypoints
- active shared configuration
- active evergreen documentation
- active tests that are intentionally root-level

The repository root is **not** for:

- one-off execution reports
- temporary handoff notes
- phase summaries
- prompt drafts
- ad hoc verification output
- transient error logs
- duplicated “final” / “latest” / “new” variants

## 3. Code naming rules

### 3.1 Python files

- Use lowercase `snake_case`.
- Name files by responsibility, not chronology.
- Allowed examples:
  - `batch_controller.py`
  - `word_generator.py`
  - `system_verification.py`
  - `memory_policy.py`
- Disallowed patterns:
  - `00_*.py`
  - `01_*.py`
  - `phase_*.py`
  - `*_final.py`
  - `*_latest.py`
  - `*_new.py`
  - `*_temp.py`
  - versioned names like `*_v3.py` or `*_v40.py`

### 3.2 Test files

- Use `test_<feature>_<behavior>.py`.
- Test names must describe what is verified, not when it was added.
- Allowed examples:
  - `test_pipeline_router_association.py`
  - `test_word_docx_smoke.py`
- Disallowed examples:
  - `test_p3_final.py`
  - `test_h41_final_hardening.py`

### 3.3 Documentation files

Active evergreen documentation may stay in the root, but only if it matches one of these roles:

- `README.md`
- `GETTING_STARTED.md`
- `DEVELOPER_GUIDE.md`
- `ARCHITECTURE.md`
- `NAMING_AND_ARCHIVE_POLICY.md`
- explicitly active design docs such as `FOCUS_REGISTRY_DESIGN.md`

New active docs must use stable, role-based names:

- `GETTING_STARTED.md`
- `DEVELOPER_GUIDE.md`
- `ARCHITECTURE.md`
- `<DOMAIN>_DESIGN.md`
- `<DOMAIN>_POLICY.md`

Do not create new root docs with:

- `PHASE_*`
- `HARNESS_*`
- `SESSION_*`
- `*_REPORT`
- `*_SUMMARY`
- `*_CHECKLIST`
- `*_PROMPT`
- `*_ROADMAP`
- `*_PLAN`
- version suffixes such as `v2`, `v3`, `v40`

## 4. Historical document rules

If a document is specific to one execution, one phase, one handoff, or one troubleshooting session, it is a historical document and must be archived under `docs/history/`.

### 4.1 Historical categories

Use these subdirectories:

- `docs/history/phase/`
- `docs/history/harness/`
- `docs/history/reports/`
- `docs/history/plans/`
- `docs/history/sessions/`
- `docs/history/diagnostics/`

If a new category is truly needed, add it deliberately and document it in `docs/history/README.md`.

### 4.2 What belongs in history

Archive any file that is:

- a phase delivery report
- a one-off completion report
- an execution summary
- a temporary checklist for a single task
- an AI prompt bundle for one run
- a troubleshooting dump or error log
- a benchmark output snapshot
- a session-by-session note
- a “final handoff” for a now-completed step

### 4.3 Historical naming format

For newly created historical docs, prefer:

- `<YYYY-MM-DD>_<topic>.md`
- `<YYYY-MM-DD>_<topic>.txt`

Examples:

- `2026-04-12_association-bundle-hardening.md`
- `2026-04-12_pipeline-smoke-errors.txt`

When moving legacy historical docs that already exist, preserving the original filename is acceptable during archive migration.

## 5. Document creation limits for AI agents

For one implementation task, Gemini/Copilot/Codex should create at most:

- one canonical active spec or guide update
- one archived report if a report is actually needed
- one archived diagnostics file only if raw diagnostics must be preserved

Do **not** create separate files for all of these at once unless explicitly requested:

- report
- summary
- handoff
- checklist
- prompt
- completion note
- final note

If the information can be merged into an existing canonical document, update that document instead.

## 6. Canonical-vs-archive decision rule

Use this test before creating a document:

- If the document should still matter in 30 days and be the default place a maintainer reads, it is canonical.
- If the document only explains one run, one experiment, one phase, or one handoff, it is historical.

Canonical documents belong in the root or another stable active location. Historical documents belong in `docs/history/`.

## 7. Move-and-reference rules

When archiving or renaming documents:

1. Move the file physically.
2. Update active references in:
   - `README.md`
   - active guides
   - verification scripts
   - smoke tests
   - CI files
3. Run a residual search for the old path.
4. Do not leave the repository internally pointing at the old name.

## 8. Verification requirements

After changing naming or archive structure:

1. Run a residual search for old names.
2. Run `py_compile` for changed Python files.
3. Run affected smoke commands such as:
   - `integrated_pipeline.py --help`
   - `batch_controller.py --help`
   - `word_generator.py --help`
   - `system_verification.py --help`
4. Run the core regression suite when active paths or documentation references change.

## 9. Prompt block for Gemini / Copilot / Codex

Use this block whenever asking an AI assistant to implement repository changes:

```text
Before making changes:
1. Create a rollback snapshot under `.rollback_snapshots/<task>-<timestamp>/`.
2. Search official or primary sources relevant to naming, packaging, or architecture before deciding structure.

Naming rules:
- Code files use lowercase snake_case and responsibility-based names.
- Do not create numbered, phase-based, final, latest, temp, or version-suffixed filenames.
- Prefer updating an existing canonical document over creating a new one.

Historical document rules:
- One-off reports, summaries, prompts, checklists, diagnostics, and phase notes must go under `docs/history/`.
- Use the correct history subdirectory: `phase`, `harness`, `reports`, `plans`, `sessions`, or `diagnostics`.
- Do not create multiple overlapping historical docs for the same task unless explicitly requested.

After changes:
1. Search for residual references to old names.
2. Run compile checks and the relevant regression tests.
3. Report what was renamed, what was archived, and what still remains as debt.
```

## 10. Enforcement summary

- Root stays clean and canonical.
- History lives under `docs/history/`.
- Names describe function, not phase or version.
- Every structural change requires rollback, primary-source check, residual scan, and regression verification.
