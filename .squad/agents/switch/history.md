# Switch History

## Project Context

- Project: my-project
- Owner: xiao
- Preferred role: frontend design aligned with real functionality and backend algorithms

## Learnings

- Frontend work should be driven by actual user needs, not generic dashboards or decorative UI.
- This project needs a frontend that clearly expresses retrieval, relevance filtering, smart dialogue, and writing-assistant workflows.

### 2026-04-20: Chat UI Design for Intelligent Chat Phase 5

- **Tier selector**: Use segmented control (pill group) instead of dropdown. Speed/quality tradeoffs should be visible at a glance, not hidden behind a click. This aligns with product goal of making backend intelligence legible.

- **Context chunk disclosure**: Progressive disclosure is the right pattern. Most users want answers; researchers need provenance. Collapsible accordion solves both needs without visual clutter.

- **State machine alignment**: Frontend states must map to backend reality (unavailable → ready → responding → grounded/insufficient). The `frontend-state-spec.md` provides the canonical state list.

- **API response shape**: Frontend expects `context_metadata.chunks[]` for progressive disclosure. Coordinated with intelligent-chat-plan.md Phase 4 contract (`ChatResponse` model).

- **Open questions surfaced**: Insight Message UX, session history browsing, mobile layout — all flagged for Morpheus. These are product decisions, not UI decorations.

- **Artifacts produced**: `chat-ui-contract.md` (spec for Trinity), `switch-chat-ui-design.md` (decision note).

### 2026-04-20: Chat UI Contract & Design Delivery

- Created `.squad/identity/chat-ui-contract.md`: Spec for Trinity chat endpoint API response shape and frontend integration (tier selector, context chunks, state mapping)
- Created `.squad/agents/switch/switch-chat-ui-design.md`: Design rationale for tier selection (segmented pill group) and progressive context disclosure (accordion)
- **Design Insight:** Segmented control (not dropdown) makes speed/quality tradeoffs visible; aligns with product goal of legible backend intelligence
- **Design Insight:** Progressive disclosure via accordion lets most users ignore provenance while researchers can drill into sources
- **Open Questions Escalated:** Insight Message UX, session history loading, mobile responsiveness (awaiting Morpheus decision)
- **Status:** ✅ Ready for Morpheus Phase 1 design review (2026-04-25)
