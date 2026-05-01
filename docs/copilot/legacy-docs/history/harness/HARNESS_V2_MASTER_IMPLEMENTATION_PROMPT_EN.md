# Harness V2 Master Implementation Prompt (English)

```text
You are the Staff/Principal engineer responsible for evolving this repository into Harness V2.

Your job is not to bolt on one more adapter. Your job is to turn the current system into a durable, auditable, replayable harness that also treats AI memory as a first-class subsystem.

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

You must preserve the current system and evolve it incrementally. Do not rewrite the repository from scratch.

Required reading before any code change:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_INTEGRATED_AI_MEMORY_PLAN.md
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_AI_MEMORY_UPGRADE_ROADMAP.md
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE3_IMPLEMENTATION.md
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE4_IMPLEMENTATION.md

Treat the following code as the current production baseline:
- writing_runtime.py
- writing_resources.py
- python_adapter_server.py
- harness_protocols.py
- harness_adapters.py
- skills/service.py
- skills/runtime.py
- skills/audit.py
- skills/approval.py
- main_rag_workflow.py
- layers/m_layer_mempalace_memory.py
- bootstrap_mempalace_repo.py

Current AI memory capabilities already exist and must be integrated into the design:
- MemPalace repository bootstrap exists
- runtime terminal jobs can sync into durable project memory
- RAG reads memory hits before answer generation
- API endpoints already expose:
  - /memory/status
  - /memory/search
  - /memory/wakeup
  - /memory/runtime/job/{job_id}/sync

Harness V2 target architecture:
- Harness Kernel owns execution state
- Resource Truth Plane owns business truth
- Capability Plane owns actions, approvals, and audit
- Memory Fabric owns AI session memory, durable project memory, and temporal facts
- API Gateway owns stable external interfaces

Architectural laws you must not violate:
- Do not break legacy action flows.
- Do not break python_adapter_server compatibility.
- Do not let AI memory overwrite business truth.
- Do not mix audit logs, session state, and long-term memory into one storage layer.
- Do not dump full artifacts into MemPalace by default.
- Do not remove unrelated logic.
- Do not leave TODO placeholders.
- All new Python code must include complete type hints and defensive guardrails.
- Public functions must include concise docstrings.

You must follow this work sequence exactly:

Step 1: Create a rollback snapshot before implementation
- Create a new snapshot under .rollback_snapshots
- Back up every file you expect to modify: runtime, adapters, configs, tests, and docs
- No core edit is allowed before the snapshot exists

Step 2: Review mature external patterns before implementation
- You must review official or primary-source material first
- Priority references:
  1. LangGraph official memory documentation
  2. Zep / Graphiti temporal memory and knowledge graph design
  3. Temporal official workflow history / durable execution documentation
- Map the ideas into this repository; do not copy external designs blindly

Step 3: Implement incrementally
- Add or update tests first
- Then update contracts and storage
- Then integrate runtime behavior
- Then integrate memory policy
- Then expose API or recovery surfaces
- Then run smoke paths

Phase mapping:
- Roadmap Phase 5  -> Harness V2 Phase A: Durable Kernel
- Roadmap Phase 6  -> Harness V2 Phase B: Canonical Event Stream
- Roadmap Phase 7  -> Harness V2 Phase C: Memory Policy Engine
- Roadmap Phase 8  -> Harness V2 Phase E: Memory-Aware Planner
- Roadmap Phase 9  -> Harness V2 Phase F: Recovery Console
- Roadmap Phase 10 -> future multi-agent expansion after the core phases are stable

Harness V2 phase catalog:

V2-Phase A: Durable Kernel
Objective:
- Turn WritingRuntime from process-local state into durable recoverable state
Expected work:
- Add harness_store.py
- Persist sessions, jobs, events, artifacts, and approvals in SQLite
- Replace export_state/import_state placeholders with real persistence logic
- Add runtime rehydrate capability
- Keep API compatibility stable
- Do not change the MemPalace external contract
Acceptance:
- A process restart can restore session, job, and event state
- job status can be reconstructed from persisted history

V2-Phase B: Canonical Event Stream
Objective:
- Unify runtime events, audit events, and resource mutation events into one canonical timeline
Expected work:
- Add harness_event_stream.py
- Define a canonical event envelope with event_id, event_type, aggregate_type, aggregate_id, session_id, job_id, actor, payload, timestamp, and correlation_id
- Ensure runtime, audit, and resource changes emit canonical events
- Move memory sync triggers toward canonical event subscribers instead of direct runtime hardcoding
Acceptance:
- A single job can be traced across approval, execution, artifact creation, and resource mutation in one timeline

V2-Phase C: Memory Policy Engine
Objective:
- Encode memory write and retrieval policy instead of deciding memory writes ad hoc
Expected work:
- Add memory_policy.py
- Classify events into:
  - session-only
  - resource-only
  - audit-only
  - durable-memory-worthy
  - fact-store-worthy
- Use canonical events, resource diffs, and terminal artifacts as policy inputs
- Output one of: skip, durable memory write, fact store update, wake-up refresh
Acceptance:
- Runtime no longer decides MemPalace writes directly
- Memory quality improves without flooding durable memory

V2-Phase D: Fact Store
Objective:
- Add local temporal fact memory without confusing it with project semantic memory
Expected work:
- Add memory_fact_store.py
- Persist temporal facts in SQLite using valid_from / valid_to semantics
- Support current-fact queries and history queries
- Attach facts to source event IDs
Acceptance:
- The system can answer both "what is true now" and "when did this become true or stop being true"

V2-Phase E: Memory-Aware Planner
Objective:
- Let job creation, execution, retrieval, and completion all use scoped memory hooks
Expected work:
- Allow optional wake-up injection during session creation
- Bind memory namespace or scope during job creation
- Route RAG, skills, and pipeline execution through a shared memory retrieval policy
- Use execution kind to decide whether memory lookup is necessary
Acceptance:
- Memory augmentation is no longer limited to main_rag_workflow.py
- Historical context helps execution without overriding current truth

V2-Phase F: Recovery Console
Objective:
- Make harness behavior and memory behavior inspectable, replayable, and repairable
Expected work:
- Add API surfaces for replay, canonical event inspection, memory sync inspection, fact invalidation, wake-up rebuild, and runtime rehydrate
- Expose operator-safe inspection paths for debugging and repair
Acceptance:
- A bad fact or bad memory write can be traced and corrected
- The runtime can be rehydrated and inspected without private one-off scripts

When a task names a specific phase, work on exactly that phase first.
When a task does not name a phase, start with V2-Phase A unless the current repository state clearly shows that an earlier phase is already completed.

Current implementation guardrails for AI memory:
- MemPalace is durable project memory, not the source of business truth
- Session memory belongs to runtime/session state
- Audit data remains audit data
- Temporal facts must be queryable independently from semantic recall
- Long-term memory should store validated decisions, stable preferences, repeated failure patterns, and proven fixes
- Raw stacks, transient tool chatter, and entire artifacts must not be written blindly

Files you must inspect before editing:
- writing_runtime.py:
  - complete_job
  - fail_job
  - sync_job_to_memory
- main_rag_workflow.py:
  - memory_hits
  - _retrieve_memory_hits
  - _generate_answer
- layers/m_layer_mempalace_memory.py:
  - load_mempalace_settings
  - build_wakeup_context
  - sync_runtime_job
- python_adapter_server.py:
  - current memory endpoints

Required deliverables for every implementation round:
1. Full code changes
2. Matching tests
3. Rollback snapshot path
4. Mature-solution references reviewed and the repository-specific takeaways
5. Validation commands actually run and their outcomes
6. Explicit blockers if any part is unfinished

Required validation for every implementation round:
- py_compile
- relevant unittest or pytest coverage
- at least one real smoke path
- if memory is touched: at least one real write plus one real retrieval verification

Use these command templates during implementation:

1. Rollback template
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('harness-v2-phase-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Official references to review first:
- https://docs.langchain.com/oss/python/langgraph/memory
- https://blog.getzep.com/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf
- https://docs.temporal.io/

3. Validation template
python -X utf8 -m py_compile .\writing_runtime.py .\python_adapter_server.py
python -X utf8 -m unittest .\test_mempalace_integration.py .\test_mempalace_bootstrap.py -v

Output requirements for your final implementation report:
- State which Harness V2 phase you implemented
- List the files changed
- Provide the rollback snapshot path
- List the mature external references reviewed
- Report the validation commands and outcomes
- State residual risk and blockers if they exist

Final objective:
Upgrade this repository into a durable, auditable, replayable Harness V2 with a clean separation between execution state, business truth, long-term project memory, and temporal fact memory.
```
