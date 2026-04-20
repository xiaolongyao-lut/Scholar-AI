# EXECUTION NOTICE — Intelligent Chat Phase 5 (GO-AHEAD)

**Date:** 2026-04-20  
**Status:** ✅ APPROVED FOR IMMEDIATE EXECUTION  
**Owner:** User (Product Lead)  
**Decision:** Hard-stop decisions locked; team may proceed with Phase 1 immediately  

---

## Decision Summary

All 4 hard-stop decisions for Intelligent Chat are now **LOCKED** based on user feedback:

| Decision | Choice | Why |
| --- | --- | --- |
| **LLM Framework** | LiteLLM | Support 3 providers (embedding + rerank + chat) with flexible switching |
| **API Key Management** | `.env` (existing) | Leverage current setup; minimal integration risk |
| **Context Budget** | Effect-first (Top 15) + user tiers | Support 100-paper literature base; keyword-marking per latest research |
| **Conversation Memory** | Long-term local SQLite | Multi-turn dialogue with persistent `.squad/memory/` storage |

---

## Team Action Items (Immediate)

### Trinity (Implementation Lead)

**START NOW: Phase 1 - LiteLLM Integration**

You have full authority to:
1. Add `litellm>=1.0.0` to `requirements.txt`
2. Create `litellm_gateway.py` with the unified gateway pattern from the plan
3. Create `test_litellm_gateway.py` with 3 provider tests
4. Push `.env` configuration structure for all 3 API keys

**Deadline:** Friday EOD (Week 1)

**Reference Document:** `.squad/identity/intelligent-chat-plan.md` → Phase 1 section

**Approval Path:** Once Phase 1 tests pass, loop Morpheus for architecture sign-off before Phase 2

---

### Tank (QA Lead)

**START NOW: Test Scenario Authoring**

You have full authority to:
1. Prepare test dataset: real 100-paper corpus from user Zotero library (or synthetic equivalent)
2. Define test cases for all 3 context tiers (FAST / BALANCED / THOROUGH)
3. Create validation checklist for Phase 2-4 (context budget, session memory, chat endpoint)
4. Coordinate with Trinity on test data shape

**Deadline:** By Monday morning (before Phase 2 starts)

**Reference Document:** `.squad/identity/intelligent-chat-plan.md` → Test Scenarios section

**Collaboration:** Tag Trinity once your test dataset is ready

---

### Switch (Frontend Lead)

**START PLANNING: UI/UX for Chat**

You have full authority to:
1. Review `.squad/identity/intelligent-chat-plan.md` Phase 5 (frontend) section
2. Sketch tier selector UI (FAST / BALANCED / THOROUGH dropdown)
3. Plan session history component
4. Decide: show context chunks to user or hide them?
5. Coordinate design with Morpheus for final review

**Deadline:** Sketch ready by Wednesday (before Phase 3 ends)

**Reference Document:** `.squad/identity/intelligent-chat-plan.md` → Phase 5 section

**Collaboration:** No blocking; you can proceed in parallel; Trinity will ping when Phase 4 ready

---

### Morpheus (Architecture Reviewer)

**STANDBY FOR PHASE REVIEWS**

You have full authority to:
1. Review Trinity's Phase 1 code + tests (will land Friday)
2. Approve before Phase 2 start
3. Review Tank's test methodology on Monday
4. Review context budget strategy (Phase 2)
5. Final architecture sign-off before Phase 4 chat endpoint goes live

**Review Criteria:** All phases must include:
- Test coverage of main flow
- `.env` secrets handling (no hardcoded keys)
- Error handling for all 3 LLM providers
- Clear escalation path if issues discovered

**Decision Authority:** If any phase hits blocker, Morpheus decides: proceed / iterate / escalate to user

---

## Execution Timeline

```
WEEK 1 (Apr 21-25)
├─ Mon-Wed: Trinity Phase 1 code (LiteLLM)
├─ Wed: Tank test dataset ready
├─ Thu: Phase 1 tests pass + Morpheus review
└─ Fri: Phase 1 approved ✓

WEEK 2 (Apr 28-May 2)
├─ Mon: Phase 2 starts (Context Budget)
├─ Tue-Wed: Tank validation on 100-paper dataset
├─ Wed: Switch UI/UX design ready
├─ Thu: Phase 2 tests pass
├─ Fri: Phase 3 starts (Session Memory)

WEEK 3 (May 5-9)
├─ Mon-Wed: Phase 3 code (SQLite + JSONL)
├─ Thu: Phase 3 tests + Morpheus review
├─ Fri: Phase 4 starts (Chat Endpoint integration)

WEEK 4 (May 12-16)
├─ Mon-Wed: Phase 4 full pipeline
├─ Thu: All phase tests pass
├─ Fri: Phase 4 Morpheus approval + Phase 5 (Frontend) ready to go
```

---

## Team Norms for This Execution

### Code

- All code must be committed to feature branch (naming: `feature/chat-phase-{N}`)
- Morpheus must review before merge to main
- Tests must pass before PR submission
- No hardcoded secrets; all API keys via `.env`

### Communication

- Daily 5-min standup: Slack 10:00 UTC
- Weekly sync: Monday 14:00 UTC (30 min)
- Blockers: ping Morpheus immediately (don't wait for weekly)
- Test results: share in #qa-results after each phase

### If Issues Arise

If during Phase N you discover:

1. **LiteLLM not working with a provider** → Stop; escalate to Morpheus + user
2. **Context budget insufficient for 100 papers** → Stop; evaluate chunking strategy
3. **Session memory SQLite scaling issue** → Stop; Morpheus decides Redis vs. local
4. **Token costs unexpectedly high** → Stop; may revert tier default

**No unilateral decisions to revert the hard-stop decisions.** All escalations go to Morpheus.

---

## File Locations (Reference)

- **Main Plan:** `.squad/identity/intelligent-chat-plan.md` (read this entire document)
- **Phase 1 Code Template:** Section "LiteLLM Integration & API Key Wiring"
- **Phase 2 Code Template:** Section "Context Window Budget & Tier System"
- **Phase 3 Code Template:** Section "Conversation Memory (Local SQLite)"
- **Phase 4 Integration:** Section "Chat Endpoint (Full Integration)"
- **Phase 5 Frontend:** Section "Frontend Integration"

---

## First Commit Instructions

**For Trinity (immediate):**

```bash
git checkout -b feature/chat-phase-1-litellm
# Add litellm to requirements.txt
# Create litellm_gateway.py
# Create test_litellm_gateway.py
git add .
git commit -m "Phase 1: LiteLLM gateway for 3 providers (embedding + rerank + chat)"
# Open PR, request Morpheus review
```

**For Tank (immediate):**

```bash
# Prepare 100-paper test corpus in ./test_data/100_papers/
# Create test/test_scenarios_100papers.md
# List all test cases by phase
git add .
git commit -m "Test: 100-paper corpus + phase test scenarios"
# Ping Trinity: dataset ready
```

---

## Success Signal

When this execution is complete:

- ✅ Trinity: All 4 phases shipped + Morpheus approved
- ✅ Tank: Full test suite passes with 100-paper dataset
- ✅ Switch: Chat UI with tier selector designed + approved
- ✅ Morpheus: Architecture consistent across all phases
- ✅ User: Can open `/api/chat` and ask a question about their literature → gets answer with context metadata

---

## Approval & Sign-Off

- **User (Product Lead):** Approved ✅ (2026-04-20)
- **Morpheus (Architecture):** Approved ✅ (pending Trinity Phase 1 code review)
- **Trinity (Implementation):** Ready to start ✅
- **Tank (QA):** Ready to support ✅
- **Switch (Frontend):** Ready to plan ✅

---

## Next Communication

- **Trinity:** Share Phase 1 code in PR by Friday (2026-04-25)
- **Tank:** Share 100-paper dataset readiness by Monday (2026-04-28)
- **All:** Weekly sync Monday 14:00 UTC to review progress

---

**Questions?** Post in #chat-phase-5 channel or escalate to Morpheus.

**Go-Ahead Status:** 🟢 **GO** — Execute immediately.
