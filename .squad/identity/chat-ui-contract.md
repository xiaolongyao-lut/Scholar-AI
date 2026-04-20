# Chat UI Contract — Phase 5 Frontend

**Owner:** Switch  
**Status:** Draft for Morpheus review  
**Date:** 2026-04-20  
**References:** `intelligent-chat-plan.md`, `frontend-state-spec.md`, `interface-glossary.md`

---

## Purpose

This document defines the UI contract for the Intelligent Chat feature. It covers component structure, interaction patterns, and API response mappings. Trinity and Tank should treat this as the frontend specification during Phase 5 implementation.

---

## 1. Tier Selector — FAST / BALANCED / THOROUGH

### Design Decision

**Recommendation:** Segmented control (pill group), NOT dropdown.

**Why:**
- Users should see all 3 options at once — this is a speed/quality tradeoff, not a hidden setting.
- Dropdown hides the options behind a click; segmented control shows the choice context immediately.
- Mobile-friendly (tappable buttons), keyboard-navigable.

### Component Specification

```
┌──────────────────────────────────────────────────┐
│  Context Tier:  [FAST] [●BALANCED●] [THOROUGH]   │
└──────────────────────────────────────────────────┘
```

| State | Appearance |
|-------|------------|
| **Selected** | Solid fill, high contrast text (e.g., blue background, white text) |
| **Unselected** | Border only, muted text |
| **Disabled** | Greyed out (used when retrieval not ready) |

### Behavior

- Default selection: **BALANCED** (per product plan: reasonable cost/quality tradeoff)
- User may switch tiers mid-session; the new tier applies on the next query
- Tier change does NOT clear conversation history

### Tier Labels & Tooltips

| Tier | Label | Tooltip (on hover) |
|------|-------|--------------------|
| FAST | "Fast" | "Top 5 papers, ~2K tokens. Quick response but less context." |
| BALANCED | "Balanced" | "Top 10 papers, ~6K tokens. Good tradeoff for most questions." |
| THOROUGH | "Thorough" | "Top 15 papers, ~12K tokens. Comprehensive but slower and higher cost." |

### API Mapping

Frontend sends `tier` field to `/api/chat`:
```json
{
  "query": "What is the effect of laser power on surface hardness?",
  "session_id": "nightly_20260420_1530",
  "tier": "balanced"
}
```

---

## 2. Session History Component

### Design Decision

**Recommendation:** Vertical conversation thread with message bubbles (standard chat layout).

### Component Structure

```
┌─────────────────────────────────────────────────────────┐
│  [Session: nightly_20260420_1530]  [New Session ↺]      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ YOU: What papers discuss laser nitriding?         │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ ASSISTANT:                                        │  │
│  │ Based on your literature collection, 7 papers...  │  │
│  │                                                   │  │
│  │ ▾ Context used (5 chunks from 3 papers)          │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ YOU: Which of these uses pulsed laser?            │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ ASSISTANT: [typing...]                            │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  [────────────── Message input ──────────────] [Send]  │
│                                                         │
│  Context Tier: [FAST] [●BALANCED●] [THOROUGH]          │
└─────────────────────────────────────────────────────────┘
```

### Session Header

- Shows session ID (human-readable: date + time)
- "New Session" button starts a fresh context (clears history, keeps literature context)
- Session persists across page refreshes (stored server-side in SQLite)

### Message Bubbles

| Role | Alignment | Style |
|------|-----------|-------|
| User | Right | Light background, no border |
| Assistant | Left | Slightly darker background, subtle border |

### Response Metadata

Each assistant response may include:
- **Tier used** (badge: "Balanced")
- **Chunks used** (collapsible: "5 chunks from 3 papers")
- **Response time** (optional, subtle: "1.2s")

---

## 3. Context Chunk Disclosure

### Design Decision

**Recommendation:** Progressive disclosure — HIDDEN by default, EXPANDABLE on demand.

**Why:**
- Most users care about the answer, not which chunks were used.
- Power users and researchers want provenance to verify grounding.
- Showing all chunks by default adds visual noise and scrolling burden.
- Collapsible accordion pattern balances both needs.

### Component Specification

```
┌───────────────────────────────────────────────────────┐
│ ASSISTANT:                                            │
│ The most cited approach uses a continuous wave CO2   │
│ laser at 500W with a 0.5mm/s scan speed...           │
│                                                       │
│ ▸ Context used (5 chunks from 3 papers)              │
└───────────────────────────────────────────────────────┘

[Click ▸ to expand]

┌───────────────────────────────────────────────────────┐
│ ASSISTANT:                                            │
│ The most cited approach uses a continuous wave CO2   │
│ laser at 500W with a 0.5mm/s scan speed...           │
│                                                       │
│ ▾ Context used (5 chunks from 3 papers)              │
│   ┌─────────────────────────────────────────────────┐│
│   │ [1] Wang_2022_LaserNitriding.pdf                ││
│   │     "...continuous wave CO2 laser with power    ││
│   │     ranging from 400-600W demonstrated..."      ││
│   ├─────────────────────────────────────────────────┤│
│   │ [2] Zhang_2021_SurfaceTreatment.pdf             ││
│   │     "...the optimal scan speed was found to be  ││
│   │     0.5mm/s at 500W power input..."             ││
│   ├─────────────────────────────────────────────────┤│
│   │ [3] ...                                         ││
│   └─────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────┘
```

### Chunk Display Fields

| Field | Source | Notes |
|-------|--------|-------|
| Index | Generated | "[1]", "[2]", etc. |
| Source | `provenance.source_pdf` or `provenance.path` | Filename or relative path |
| Snippet | `content` (truncated) | First 150 chars with ellipsis |
| Full text | Expandable | Click to expand within chunk card |

### Keyword Highlighting

- If keyword marking is applied (per Phase 2 backend), highlighted terms appear in **bold** within snippets.
- Frontend receives `marked_content` field (if available) and renders markdown-style bold.

---

## 4. Chat State Machine (Frontend)

Per `frontend-state-spec.md`, the chat UI must reflect these states:

| State | Visual Indicator | Tier Selector | Input Field |
|-------|------------------|---------------|-------------|
| **unavailable** (no literature context) | Banner: "Load literature first" | Disabled | Disabled |
| **ready** (context loaded) | No banner | Enabled | Enabled |
| **responding** | Typing indicator in message area | Disabled | Disabled |
| **insufficient context** | Warning badge on response | Enabled | Enabled |
| **grounded answer** | Normal response display | Enabled | Enabled |
| **error** | Error banner + retry button | Enabled | Enabled |

### State Transitions

```
[unavailable] ─(literature loaded)─→ [ready]
[ready] ─(user sends query)─→ [responding]
[responding] ─(response received)─→ [ready] or [insufficient context]
[responding] ─(error)─→ [error]
[error] ─(retry or new query)─→ [responding]
```

---

## 5. API Response Mapping

Frontend expects this response shape from `/api/chat`:

```typescript
interface ChatResponse {
  response: string;              // LLM answer text
  session_id: string;            // Session identifier
  context_chunks_used: number;   // Number of chunks used
  tokens_used: {
    prompt: number;
    completion: number;
    total: number;
  };
  tier_used: "fast" | "balanced" | "thorough";
  
  // Optional metadata for progressive disclosure
  context_metadata?: {
    chunks: Array<{
      index: number;
      source: string;            // File path or paper identifier
      content: string;           // Snippet (possibly keyword-marked)
      relevance_score?: number;  // If available from rerank
    }>;
    truncated: boolean;
  };
}
```

---

## 6. Open Questions for Morpheus

1. **Insight Message**: The original plan mentions "occasionally offer a concise literature-grounded inspirational insight." Should this be:
   - Automatic (system decides when to show)?
   - User-triggered (button: "Give me an insight")?
   - Disabled for MVP?

2. **Session History Persistence**: The plan shows sessions stored at `.squad/memory/{session_id}/`. Should the frontend allow users to:
   - Browse past sessions?
   - Delete sessions?
   - Or is this backend-only for now?

3. **Mobile Layout**: Current design assumes desktop. Should I prepare a mobile-responsive variant, or is this deferred?

---

## 7. Implementation Notes for Trinity

- **Tier selector**: Can be implemented as 3 radio buttons styled as a pill group, or use a component library if available.
- **Chunk disclosure**: Standard `<details><summary>` HTML element works, or use a collapsible accordion component.
- **State management**: The tier selection and session_id should persist in local state (React state, Vue reactive, or equivalent).
- **Typing indicator**: Simple CSS animation on a "..." bubble while waiting for response.

---

## Approval Status

- [ ] Switch: Design complete
- [ ] Morpheus: Architecture aligned
- [ ] Trinity: Implementation feasible

**Next Step:** Morpheus review open questions; Trinity confirm API shape alignment.
