# Project Brief

## Product

A multimodal RAG literature assistant for real research workflows.

## Core Goal

Help users search, extract, and converse with literature from their own document folders without processing everything blindly.

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

## Deferred Scope

- Full writing assistant workflows
- AI review / AI suggestions as a primary product surface
- Broad UX redesigns unrelated to core retrieval and chat

## Product Constraints

- Do not extract everything when keyword filtering can narrow the search space first.
- Preserve current frontend design style unless Morpheus approves a redesign or refactor.
- Preserve current backend code style unless Morpheus approves a refactor.
- Refactors require backup plus recorded backup location.

## Success Signal for Phase 1

A user can point the system at a folder, give keywords, get relevant literature extracted, and have a useful intelligent conversation over the resulting literature context.
