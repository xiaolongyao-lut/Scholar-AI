# Phase Plan

## Active Phase

Phase 1 — Core literature extraction and intelligent chat.

## Must Deliver

- Folder path input and traversal
- Support for realistic research folders such as Zotero-related directories and notebook folders
- Keyword-first relevance filtering before heavier extraction
- Extraction pipeline for relevant literature artifacts
- Intelligent chat grounded in the extracted literature base

## Engineering Priorities

1. Reliability of traversal and filtering
2. Correctness and robustness of retrieval / extraction algorithms
3. Clear frontend expression of retrieval state and chat behavior
4. Bug discovery from realistic user paths

## Non-Goals for This Phase

- Full writing assistant polish
- Large-scale feature sprawl from testing feedback
- Style rewrites or opportunistic refactors

## Done Criteria

- User can provide folders and keywords successfully
- System avoids unnecessary full extraction when relevance filtering can prune candidates
- Chat responses are grounded in retrieved literature context
- Core path is stable enough for repeated use
- Main workflows are testable and observable

## Hand-off Guidance

When uncertain, all agents should optimize for the current phase rather than future nice-to-haves.
