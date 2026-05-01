# Harness V2 Requirements and Checklist (English)

## Phase Map

- Roadmap Phase 5 = V2-Phase A: Durable Kernel
- Roadmap Phase 6 = V2-Phase B: Canonical Event Stream
- Roadmap Phase 7 = V2-Phase C: Memory Policy Engine
- V2-Phase D = Fact Store
- Roadmap Phase 8 = V2-Phase E: Memory-Aware Planner
- Roadmap Phase 9 = V2-Phase F: Recovery Console
- Roadmap Phase 10 = follow-on multi-agent expansion after the V2 core is stable

## Global Non-Negotiables

- Preserve the existing production baseline and evolve it incrementally.
- Keep `writing_resources.py` as the source of business truth.
- Keep MemPalace as durable project memory, not the truth source.
- Keep audit storage logically separate from session state and long-term memory.
- Keep current `python_adapter_server.py` compatibility stable.
- Do not remove unrelated logic or silently rewrite stable flows.
- Do not write full raw artifacts into durable memory by default.
- Add complete Python type hints, defensive input validation, and concise public docstrings.
- Add or update tests for every behavioral change.

## Mandatory Entry Checklist for Any Phase

- Create a rollback snapshot under `.rollback_snapshots`.
- Back up every file that may be modified in this round.
- Review the current phase definition in:
  - `HARNESS_V2_INTEGRATED_AI_MEMORY_PLAN.md`
  - `HARNESS_AI_MEMORY_UPGRADE_ROADMAP.md`
- Review mature external references before editing:
  - LangGraph memory docs
  - Zep / Graphiti temporal memory design
  - Temporal workflow history / durable execution docs
- Identify whether the change affects:
  - runtime state
  - resource truth
  - audit
  - durable project memory
  - temporal facts
  - public API compatibility

## Mandatory Exit Checklist for Any Phase

- Run `py_compile` for touched Python modules.
- Run relevant `unittest` or `pytest` coverage.
- Run at least one real smoke path.
- If memory behavior changed, verify one real write and one real retrieval.
- Confirm the change does not let memory overwrite resource truth.
- Confirm the change does not bypass audit or approval boundaries.
- Record the rollback snapshot path.
- Record the mature references reviewed and the repository-specific takeaways.

## V2-Phase A Checklist: Durable Kernel

Requirements:
- Add `harness_store.py`.
- Persist sessions, jobs, events, artifacts, and approvals.
- Replace placeholder export/import behavior with real persistence.
- Add runtime rehydrate capability.
- Preserve existing external behavior.

Checks:
- Restart the process and restore previous sessions and jobs.
- Rebuild job status from persisted history rather than process-local state only.
- Confirm artifacts and approvals remain attached to the correct jobs and sessions.
- Confirm memory sync still works after rehydration.

## V2-Phase B Checklist: Canonical Event Stream

Requirements:
- Add `harness_event_stream.py`.
- Define a canonical event envelope.
- Route runtime, audit, and resource mutations through canonical events.
- Move memory triggering toward event-driven flow.

Checks:
- A single job can be followed across approval, execution, artifact creation, and resource mutation.
- Events preserve correlation IDs and timestamps.
- Existing audit behavior still works, but now maps into the canonical stream.
- Resource mutations remain traceable back to the source action or job.

## V2-Phase C Checklist: Memory Policy Engine

Requirements:
- Add `memory_policy.py`.
- Define explicit policy categories for skip, durable memory, fact store, and wake-up refresh.
- Use canonical events and resource diffs as policy inputs.
- Remove direct ad hoc runtime decisions about durable memory writes.

Checks:
- Stable decisions and verified fixes are written to durable memory.
- Session scratch data is not written to durable memory.
- Audit-only data remains out of durable memory.
- Memory noise does not increase after the change.

## V2-Phase D Checklist: Fact Store

Requirements:
- Add `memory_fact_store.py`.
- Persist temporal facts with validity windows.
- Support current state queries and historical state queries.
- Track source event IDs for traceability.

Checks:
- The system can answer "what is true now".
- The system can answer "when did this become true".
- Replaced or invalidated facts are not returned as currently active facts.
- Facts and durable semantic memory remain separate.

## V2-Phase E Checklist: Memory-Aware Planner

Requirements:
- Add scoped wake-up injection on session or job creation where appropriate.
- Bind memory namespaces or scopes for jobs.
- Route RAG, skills, and pipeline execution through a shared retrieval policy.
- Keep retrieval evidence attributable.

Checks:
- Memory augmentation works outside `main_rag_workflow.py`.
- Historical context improves repeated-task execution.
- Retrieval does not override current business truth.
- Execution paths remain deterministic when memory is unavailable.

## V2-Phase F Checklist: Recovery Console

Requirements:
- Add replay and inspection APIs.
- Add canonical event inspection APIs.
- Add memory sync inspection paths.
- Add fact invalidation and wake-up rebuild paths.
- Add runtime rehydrate or restore APIs.

Checks:
- Operators can inspect why a memory item exists.
- Operators can inspect which event produced a fact.
- Operators can invalidate a bad fact or rebuild wake-up context.
- Recovery behavior does not require private scripts.

## AI Memory-Specific Guardrails

- Durable project memory stores validated historical context, not current truth.
- Temporal facts store active and historical facts with time boundaries.
- Session memory stores transient execution context.
- Audit logs remain compliance and replay records.
- Do not store entire artifacts unless policy explicitly allows a minimal excerpt.
- Deduplicate durable memory writes when the semantic content is unchanged.
- Preserve source traceability from memory or fact back to event or artifact.

## Evidence Package to Require from Each Implementation Round

- Implemented phase name
- Files changed
- Rollback snapshot path
- Mature references reviewed
- Validation commands run
- Validation results
- Smoke-path result
- Memory write/retrieval result if memory was touched
- Remaining blockers or deferred work

## Reference Links

- [LangGraph Memory Docs](https://docs.langchain.com/oss/python/langgraph/memory)
- [Zep Temporal Knowledge Graph Paper](https://blog.getzep.com/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf)
- [Temporal Docs](https://docs.temporal.io/)
