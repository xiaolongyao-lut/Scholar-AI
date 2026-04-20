# Intelligent Chat Implementation Plan

**Status:** READY FOR EXECUTION (Hard-Stop Decisions Made)  
**Date:** 2026-04-20  
**Owner:** Trinity (implementation lead); Morpheus (architecture review)  
**Phase:** Phase 5 completion gate

---

## Decision Summary

These 4 decisions are locked and will define the entire chat module architecture:

| Item | Decision | Rationale |
|------|----------|-----------|
| **LLM Framework** | LiteLLM | Support 3 AI providers (embedding, rerank, chat) with flexible model switching |
| **API Key Management** | `.env` (existing) | Leverage current setup; prepare for later platform Secret integration |
| **Context Window Budget** | Effect-first (Top 15+) + User-selectable tiers | Support 100-paper literature base; keyword-marking strategy per latest research |
| **Conversation Memory** | Long-term local storage | Multi-turn dialogue with persistent session state in `.squad/memory/` |

---

## Architecture Overview

```
┌─────────────────┐
│  Retrieval API  │  extract_literature_context(query, top_k=15)
│  (Phase 4)      │  → returns chunks + scores
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Context Preparation Layer      │
│  - Keyword marking (latest lit) │
│  - Truncation + tier selection  │
│  - Budget enforcement           │
└────────┬────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│  LiteLLM Unified API Gateway         │
│  (embedding + rerank + chat)         │
│  .env → model_mapping               │
└────────┬─────────────────────────────┘
         │
         ├─→ Embedding: extract_literature_context support
         ├─→ Rerank: score context relevance
         └─→ Chat: generate response with context
         │
         ▼
┌──────────────────────────────────────┐
│  Session Memory Manager              │
│  (local SQLite + JSONL log)          │
│  .squad/memory/{session_id}/         │
└──────────────────────────────────────┘
```

---

## Implementation Roadmap

### Phase 1: LiteLLM Integration & API Key Wiring (Week 1)

**Owner:** Trinity  
**Deliverable:** All 3 LLM providers callable via unified LiteLLM interface

1. **Dependency Addition**
   - Add `litellm>=1.0.0` to `requirements.txt`
   - Install: `pip install litellm`

2. **Configuration Structure** (`.env`)
   ```env
   # Embedding provider
   EMBEDDING_PROVIDER=openai
   EMBEDDING_MODEL=text-embedding-3-small
   OPENAI_API_KEY_EMBEDDING=sk_...
   
   # Rerank provider (could be same as embedding or different)
   RERANK_PROVIDER=openai
   RERANK_MODEL=gpt-4-mini
   OPENAI_API_KEY_RERANK=sk_...
   
   # Chat/response provider
   CHAT_PROVIDER=openai
   CHAT_MODEL=gpt-4-turbo
   OPENAI_API_KEY_CHAT=sk_...
   
   # Optional: Multi-model support
   LITELLM_MODEL_FALLBACK=true
   ```

3. **LiteLLM Wrapper Module** (new file: `litellm_gateway.py`)
   ```python
   # Location: ./litellm_gateway.py
   
   from litellm import completion, embedding
   from typing import List, Dict
   import os
   
   class LLMGateway:
       """Unified LiteLLM gateway for embedding, rerank, chat"""
       
       def __init__(self):
           self.embedding_config = {
               "model": os.getenv("EMBEDDING_MODEL"),
               "api_key": os.getenv("OPENAI_API_KEY_EMBEDDING"),
           }
           self.rerank_config = {
               "model": os.getenv("RERANK_MODEL"),
               "api_key": os.getenv("OPENAI_API_KEY_RERANK"),
           }
           self.chat_config = {
               "model": os.getenv("CHAT_MODEL"),
               "api_key": os.getenv("OPENAI_API_KEY_CHAT"),
           }
       
       def embed_text(self, text: str) -> List[float]:
           """Call embedding model via LiteLLM"""
           response = embedding(
               model=self.embedding_config["model"],
               input=text,
           )
           return response["data"][0]["embedding"]
       
       def rerank_chunks(self, query: str, chunks: List[Dict]) -> List[Dict]:
           """Score chunks relevance using rerank model"""
           # Implementation: call rerank model, return sorted chunks
           pass
       
       def chat_with_context(
           self, 
           query: str, 
           context_chunks: List[Dict],
           session_id: str,
       ) -> str:
           """Generate response with context via chat model"""
           # Will be detailed in Phase 3
           pass
   ```

4. **Validation Task**
   - Test all 3 providers can be called (no actual API call needed in test, can mock)
   - Verify `.env` parsing is correct
   - Create `test_litellm_gateway.py` with 3 test cases

**Exit Criteria:** `pytest test_litellm_gateway.py` passes; all 3 provider configs are loadable

---

### Phase 2: Context Window Budget & Tier System (Week 2)

**Owner:** Trinity + Tank (test scenarios)  
**Deliverable:** Context preparation layer with 3 user-selectable tiers

1. **Context Budget Manager** (new file: `context_budget.py`)
   ```python
   # Location: ./context_budget.py
   
   from enum import Enum
   from typing import List, Dict, Tuple
   
   class ContextTier(Enum):
       """User-selectable quality tiers for context"""
       FAST = ("fast", 5, 2000)          # Top 5, ~2K tokens
       BALANCED = ("balanced", 10, 6000) # Top 10, ~6K tokens
       THOROUGH = ("thorough", 15, 12000)  # Top 15, ~12K tokens
   
   class ContextBudgetManager:
       """
       Prepares retrieval results for LLM consumption.
       - Keyword marking (highlights relevance)
       - Truncation to budget
       - Tier enforcement
       """
       
       def __init__(self, tier: ContextTier = ContextTier.THOROUGH):
           self.tier = tier
           self.top_k, self.max_tokens = tier.value[1], tier.value[2]
       
       def prepare_context(
           self, 
           query: str,
           retrieved_chunks: List[Dict],
       ) -> Tuple[str, Dict]:
           """
           Prepare context string for chat model.
           
           Returns:
               - context_str: formatted, keyword-marked chunks
               - metadata: {tier, actual_tokens, chunk_count, truncated}
           """
           # Step 1: Apply keyword marking (latest research approach)
           marked_chunks = self._mark_keywords(query, retrieved_chunks[:self.top_k])
           
           # Step 2: Format and truncate to budget
           context_str = self._format_chunks(marked_chunks)
           actual_tokens = self._estimate_tokens(context_str)
           
           if actual_tokens > self.max_tokens:
               context_str = self._truncate_to_budget(context_str, self.max_tokens)
               truncated = True
           else:
               truncated = False
           
           metadata = {
               "tier": self.tier.value[0],
               "max_tokens": self.max_tokens,
               "actual_tokens": actual_tokens,
               "chunk_count": len(marked_chunks),
               "truncated": truncated,
           }
           
           return context_str, metadata
       
       def _mark_keywords(self, query: str, chunks: List[Dict]) -> List[Dict]:
           """
           Mark keywords in chunks using latest literature method:
           - Extract query terms
           - Highlight in chunk text
           - Return annotated chunks
           
           Reference: Latest keyword-marking research (e.g., DPR, ColBERT approach)
           """
           # Implementation: keyword extraction + marking
           pass
       
       def _format_chunks(self, chunks: List[Dict]) -> str:
           """Format chunks into readable context string"""
           # Implementation: format as "Chunk 1: [...]\n\nChunk 2: [...]\n..."
           pass
       
       def _truncate_to_budget(self, context_str: str, max_tokens: int) -> str:
           """Truncate context to fit token budget"""
           # Implementation: smart truncation preserving readability
           pass
       
       def _estimate_tokens(self, text: str) -> int:
           """Estimate token count for text"""
           # Implementation: use tiktoken or similar
           pass
   ```

2. **Integration with Retrieval API**
   - Modify `extract_literature_context()` to return scores + raw chunks
   - Pass to `ContextBudgetManager.prepare_context()`
   - Return formatted context string ready for LLM

3. **Test Scenarios** (Tank's responsibility)
   - Test all 3 tiers with 100-paper dataset
   - Verify keyword marking is visible in output
   - Measure token counts for each tier
   - Verify truncation doesn't break readability
   - Scenario: "Does a 100-paper search fit in THOROUGH tier?"

**Exit Criteria:** Tank's test suite passes; all 3 tiers tested with real retrieval output; Token estimates are accurate

---

### Phase 3: Conversation Memory (Local SQLite + Session Logging) (Week 2-3)

**Owner:** Trinity  
**Deliverable:** Multi-turn conversation persistence in `.squad/memory/`

1. **Session Memory Schema** (new file: `session_memory.py`)
   ```python
   # Location: ./session_memory.py
   
   from datetime import datetime
   from typing import List, Dict
   import sqlite3
   import json
   import os
   
   class SessionMemory:
       """
       Persistent conversation memory (multi-turn).
       Storage: `.squad/memory/{session_id}/`
       DB: `conversation.db`
       Logs: `session.jsonl`
       """
       
       def __init__(self, session_id: str, base_path: str = ".squad/memory"):
           self.session_id = session_id
           self.session_dir = f"{base_path}/{session_id}"
           self.db_path = f"{self.session_dir}/conversation.db"
           self.log_path = f"{self.session_dir}/session.jsonl"
           
           # Create directory + init DB
           os.makedirs(self.session_dir, exist_ok=True)
           self._init_db()
       
       def _init_db(self):
           """Initialize SQLite schema"""
           conn = sqlite3.connect(self.db_path)
           conn.execute("""
               CREATE TABLE IF NOT EXISTS turns (
                   turn_id INTEGER PRIMARY KEY,
                   timestamp TEXT NOT NULL,
                   user_query TEXT,
                   retrieved_chunks JSON,
                   context_metadata JSON,
                   llm_response TEXT,
                   model_used TEXT,
                   tokens_used JSON,
                   tier_used TEXT,
               )
           """)
           conn.commit()
           conn.close()
       
       def add_turn(
           self,
           user_query: str,
           retrieved_chunks: List[Dict],
           context_metadata: Dict,
           llm_response: str,
           model_used: str,
           tokens_used: Dict,
           tier_used: str,
       ):
           """Log one conversation turn"""
           timestamp = datetime.utcnow().isoformat()
           
           conn = sqlite3.connect(self.db_path)
           conn.execute("""
               INSERT INTO turns 
               (timestamp, user_query, retrieved_chunks, context_metadata, llm_response, model_used, tokens_used, tier_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           """, (
               timestamp,
               user_query,
               json.dumps(retrieved_chunks),
               json.dumps(context_metadata),
               llm_response,
               model_used,
               json.dumps(tokens_used),
               tier_used,
           ))
           conn.commit()
           conn.close()
           
           # Also log to JSONL for readability
           with open(self.log_path, "a") as f:
               f.write(json.dumps({
                   "timestamp": timestamp,
                   "type": "turn",
                   "user_query": user_query,
                   "response_preview": llm_response[:100] + "..." if len(llm_response) > 100 else llm_response,
                   "model": model_used,
                   "tier": tier_used,
               }) + "\n")
       
       def get_recent_turns(self, count: int = 5) -> List[Dict]:
           """Fetch most recent N turns for multi-turn context"""
           conn = sqlite3.connect(self.db_path)
           cursor = conn.execute("""
               SELECT turn_id, timestamp, user_query, llm_response, model_used, tier_used
               FROM turns
               ORDER BY turn_id DESC
               LIMIT ?
           """, (count,))
           
           turns = [
               {
                   "turn_id": row[0],
                   "timestamp": row[1],
                   "user_query": row[2],
                   "llm_response": row[3],
                   "model": row[4],
                   "tier": row[5],
               }
               for row in cursor.fetchall()
           ]
           conn.close()
           return list(reversed(turns))  # Return chronological order
       
       def get_session_summary(self) -> Dict:
           """Get session-level stats"""
           conn = sqlite3.connect(self.db_path)
           cursor = conn.execute("SELECT COUNT(*), SUM(json_extract(tokens_used, '$.total')) FROM turns")
           row = cursor.fetchone()
           conn.close()
           
           return {
               "session_id": self.session_id,
               "total_turns": row[0] or 0,
               "total_tokens": row[1] or 0,
           }
   ```

2. **Multi-Turn Chat Prompt Builder**
   ```python
   # Location: ./multi_turn_prompt.py
   
   class MultiTurnPromptBuilder:
       """
       Constructs LLM prompt with:
       - Current question
       - Retrieved context
       - Recent conversation history
       """
       
       def build_prompt(
           self,
           current_query: str,
           context_str: str,
           recent_turns: List[Dict],
           system_prompt: str = None,
       ) -> str:
           """
           Build full prompt for LLM.
           
           Structure:
           [System]
           [Recent turns as reference]
           [Current context]
           [Current query]
           """
           
           if system_prompt is None:
               system_prompt = """You are an intelligent literature research assistant.
   Your role is to answer questions about the user's literature collection with precision and clarity.
   Cite specific papers and sections when you provide information."""
           
           # Build recent history section
           history_section = ""
           if recent_turns:
               history_section = "\n\nRecent conversation history:\n"
               for turn in recent_turns[:-1]:  # Exclude current query
                   history_section += f"User: {turn['user_query']}\nAssistant: {turn['llm_response']}\n\n"
           
           prompt = f"""{system_prompt}

{history_section}

Context from literature base:
{context_str}

User question: {current_query}

Please provide a thoughtful answer based on the literature context above."""
           
           return prompt
   ```

3. **Session Lifecycle**
   - Session created on first chat: `session_id = nightly_{YYYYMMDD}_{HHMM}`
   - All turns logged to local SQLite + JSONL
   - On new chat session: summarize previous, initialize new memory
   - Persist indefinitely in `.squad/memory/{session_id}/`

**Exit Criteria:** Multi-turn conversation can be logged and retrieved; recent turns visible in prompt; session summary accurate

---

### Phase 4: Chat Endpoint (Full Integration) (Week 3)

**Owner:** Trinity  
**Deliverable:** `/api/chat` endpoint with full pipeline

1. **Chat Router** (new file: `routers/chat_router.py`)
   ```python
   # Location: ./routers/chat_router.py
   
   from fastapi import APIRouter, HTTPException
   from pydantic import BaseModel
   from litellm_gateway import LLMGateway
   from context_budget import ContextBudgetManager, ContextTier
   from session_memory import SessionMemory
   from multi_turn_prompt import MultiTurnPromptBuilder
   
   router = APIRouter(prefix="/api/chat", tags=["chat"])
   
   class ChatRequest(BaseModel):
       query: str
       session_id: str  # or generate if not provided
       tier: str = "balanced"  # fast, balanced, thorough
   
   class ChatResponse(BaseModel):
       response: str
       session_id: str
       context_chunks_used: int
       tokens_used: Dict
       tier_used: str
   
   llm_gateway = LLMGateway()
   
   @router.post("/chat", response_model=ChatResponse)
   async def chat(request: ChatRequest):
       """
       Full chat endpoint with multi-turn memory.
       
       Flow:
       1. Retrieve relevant chunks
       2. Prepare context (tier selection, keyword marking)
       3. Load recent conversation history
       4. Build full prompt with context + history
       5. Call LLM
       6. Log turn to session memory
       7. Return response
       """
       
       # Step 1: Retrieve
       from pipeline_core import run_pipeline  # existing
       retrieval_result = run_pipeline(request.query, num_results=15)
       chunks = retrieval_result["chunks"]
       
       # Step 2: Prepare context
       tier = ContextTier[request.tier.upper()]
       budget_mgr = ContextBudgetManager(tier)
       context_str, context_metadata = budget_mgr.prepare_context(request.query, chunks)
       
       # Step 3: Load session memory
       memory = SessionMemory(request.session_id)
       recent_turns = memory.get_recent_turns(count=5)
       
       # Step 4: Build prompt
       prompt_builder = MultiTurnPromptBuilder()
       full_prompt = prompt_builder.build_prompt(
           current_query=request.query,
           context_str=context_str,
           recent_turns=recent_turns,
       )
       
       # Step 5: Call LLM
       response = llm_gateway.chat_with_context(
           messages=[{"role": "user", "content": full_prompt}],
           model=os.getenv("CHAT_MODEL"),
           max_tokens=2048,
       )
       
       llm_response = response["choices"][0]["message"]["content"]
       tokens_used = response.get("usage", {})
       
       # Step 6: Log turn
       memory.add_turn(
           user_query=request.query,
           retrieved_chunks=chunks[:context_metadata["chunk_count"]],
           context_metadata=context_metadata,
           llm_response=llm_response,
           model_used=os.getenv("CHAT_MODEL"),
           tokens_used=tokens_used,
           tier_used=request.tier,
       )
       
       # Step 7: Return
       return ChatResponse(
           response=llm_response,
           session_id=request.session_id,
           context_chunks_used=context_metadata["chunk_count"],
           tokens_used=tokens_used,
           tier_used=request.tier,
       )
   ```

2. **Test Scenarios** (Tank)
   - Single-turn chat: query → response
   - Multi-turn: 3+ turns in same session
   - Tier switching: verify different tier produces different context
   - Session persistence: verify recent turns are loaded
   - Edge cases: empty query, no results, malformed session_id

**Exit Criteria:** `/api/chat` works end-to-end; Tank's test suite passes; multi-turn conversation visible in response

---

### Phase 5: Frontend Integration (Switch's responsibility, post-plan-approval)

**Owner:** Switch  
**Deliverable:** Chat UI with tier selector, session persistence

1. **Chat component** receives response + tier info
2. **Tier selector** UI: dropdown (fast/balanced/thorough)
3. **Session UI**: shows conversation history
4. **Context display** (optional): show which papers were used

---

## Team Roles & Responsibilities

| Role | Task | Deliverable | Deadline |
|------|------|-------------|----------|
| **Trinity** | LiteLLM integration (P1) | `litellm_gateway.py` + tests | Week 1 end |
| **Trinity** | Context budget manager (P2) | `context_budget.py` | Week 2 mid |
| **Trinity** | Session memory (P3) | `session_memory.py` | Week 2 end |
| **Trinity** | Chat endpoint (P4) | `/api/chat` working | Week 3 end |
| **Tank** | Test scenarios (P2-P4) | Test suite + 100-paper validation | Each phase end |
| **Switch** | Frontend (P5) | Chat UI with tier selector | After P4 approval |
| **Morpheus** | Architecture review | Approve each phase | At phase close |

---

## Dependency Chain

```
Phase 1 (LiteLLM) ✓ required before Phase 2
    ↓
Phase 2 (Context Budget) ✓ required before Phase 4
    ↓
Phase 3 (Session Memory) ✓ required before Phase 4
    ↓
Phase 4 (Chat Endpoint) ✓ can proceed to Phase 5
    ↓
Phase 5 (Frontend) ✓ final integration
```

---

## Decision Lock & Escalation

If during implementation we discover:

- **LiteLLM limitations** → escalate to Morpheus; backup plan: fallback to direct OpenAI SDK
- **Context budget insufficient for 100-paper case** → escalate; may need to implement chunking strategy
- **Session memory scaling issues** → escalate; may need Redis instead of local SQLite
- **Token cost exceeds expectations** → escalate; may need to revert to BALANCED tier default

All escalations must reference this plan and propose alternative with tradeoffs.

---

## Success Criteria

- ✅ All 3 LLM providers callable via unified LiteLLM interface
- ✅ Context tiers working: FAST (5 papers) / BALANCED (10) / THOROUGH (15)
- ✅ Keyword marking visible in context output
- ✅ Multi-turn conversation persists for 100+ turns in local SQLite
- ✅ `/api/chat` endpoint returns response + metadata in <3 sec
- ✅ Tank's full test suite passes with 100-paper dataset
- ✅ Session memory location: `.squad/memory/{session_id}/` is standard
- ✅ No production secrets in code (all via `.env`)

---

## Next Steps

1. **Morpheus approval** of this plan (or request changes)
2. **Trinity starts Phase 1** (LiteLLM integration)
3. **Tank prepares test datasets** (100-paper corpus)
4. **Weekly sync:** Monday 10:00 UTC to review phase progress

**Plan Owner:** Morpheus  
**Plan Status:** READY FOR MORPHEUS REVIEW  
**Last Updated:** 2026-04-20 12:00 UTC
