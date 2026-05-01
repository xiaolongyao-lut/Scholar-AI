# Project Brief

## Product

A local-first literature assistant / research-writing pipeline for real research workflows. The long-term architecture target is **TOLF**; standard RAG is the transition reference frame and comparison baseline, not the final product identity.

## Core Goal

Help users search, extract, evaluate, converse with, and eventually package literature-grounded writing materials from their own document folders without processing everything blindly.

## Primary User Workflow

1. User selects one or more literature folders.
2. The system traverses those folders, including Zotero-related directories, notebook folders, and other user-provided literature repositories.
3. User provides keywords.
4. The system performs relevance-oriented traversal first, filtering candidates before full extraction.
5. The system builds usable literature context for intelligent dialogue.
6. The assistant can answer questions and occasionally offer a concise literature-grounded inspirational insight.

## Current Scope

- Folder traversal
- Keyword-based relevance scanning
- Literature extraction
- Intelligent dialogue over the literature base
- Evaluation credibility and retrieval/rerank quality gates
- Delivery artifacts under docs/artifacts/output that downstream tools can read

## Deferred Scope

- Full end-to-end writing assistant workflows as the default surface
- AI review / AI suggestions as a primary product surface
- Broad UX redesigns unrelated to core retrieval and chat
- Replacing the default main chain with TOLF before dedicated TOLF evaluation passes

## Product Constraints

- Do not extract everything when keyword filtering can narrow the search space first.
- Do not call the project “just RAG”; TOLF is the target architecture, RAG is the current comparison/control frame.
- Treat 109-paper/canary30/full evaluation口径 as gate-sensitive; never mix artifacts across runs.
- Preserve current frontend design style unless Morpheus approves a redesign or refactor.
- Preserve current backend code style unless Morpheus approves a refactor.
- Refactors require backup plus recorded backup location.

## Success Signal for Phase 1

A user can point the system at a folder, give keywords, get relevant literature extracted, and have a useful intelligent conversation over the resulting literature context.

## Current Scale / Modality Notes

- Current baseline: 109-paper corpus plus canary query sets.
- Target direction: 1000-paper scale, cross-disciplinary expansion, Chinese/English mixed literature.
- Multimodal status: text/table/figure/caption/image-manifest paths exist; formula extraction remains a known gap.
