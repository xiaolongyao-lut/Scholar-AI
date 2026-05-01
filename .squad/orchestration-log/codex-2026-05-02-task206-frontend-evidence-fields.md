# TASK-206 Frontend Evidence Fields

## Facts

- Rollback checkpoint created before edits: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-040542-continue-rag-task206-frontend-evidence-fields`.
- Mature solution pattern from TASK-204/TASK-205 remains applicable: result consumers should preserve source/provenance metadata through the UI surface, not degrade evidence to plain text or opaque IDs.
- Local gap: `frontend/src/lib/evidenceReferences.ts` parsed only `chunk_id/source_id/title/content/quote/score` as stable fields. Backend RAG evidence refs now emit `material_id`, `text`, `compressed_text`, `label`, `page`, `source`, `source_labels`, and `source_hint`.

## Decision

- Extend `EvidenceReference` typing and normalizer to include backend RAG provenance fields.
- Prefer `compressed_text` and then `text` in evidence bodies so compressed context is visible instead of falling back to `chunk_id`.
- Show `material_id` as source metadata when `source_id` is absent.
- Surface `source_labels` or `source_hint` in compact metadata so users can see whether evidence came from bm25, dense, graph, rerank, or fallback paths.
- Keep WritingCanvas layout unchanged; this is a data-display contract fix, not a redesign.

## Evidence

- Changed files:
  - `frontend/src/lib/evidenceReferences.ts`
  - `frontend/src/lib/evidenceReferences.test.ts`
  - `frontend/src/types/writing.ts`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
- Verification:
  - `npm run test -- src/lib/evidenceReferences.test.ts` -> `5 passed`
  - `npm run build` -> success

## Open

- No Playwright visual smoke was run for this micro-slice because layout structure did not change and the focused helper/build checks cover the data contract.
- If direct RAG answer UI is introduced later, reuse the same parser instead of creating a second evidence display path.

## Next

- Candidate next slices:
  - Inspect whether a direct RAG HTTP endpoint should expose the same result schema.
  - Prepare a guarded, default-off rerank/TOLF canary with reversible config and focused eval evidence.
