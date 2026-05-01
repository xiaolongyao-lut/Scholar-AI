# Morpheus Diagnostic — Key Resolution Regression Audit

- **Date:** 2026-04-25
- **Author:** Morpheus (Squad 4.7 Coordinator, this session)
- **Scope:** Cross-validate that the user directive "重点识别 key,不识别 siliconflow"
  is fully satisfied across **both** rerank and embedding call paths.
- **Trigger:** `/squad long-run --supervised` — user green-lit autonomous investigation
  of the 401 blocker that currently gates plans §3.3 / §3.6 / §3.7 / §3.5.5 in
  `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` and the full-v2.1 recall
  collapse in `docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md`.
- **Status:** Findings only. No code touched. This file is a decision input for
  the next executor (whoever picks up the fix — Copilot or Squad worker role).

---

## 1. Scope Reminder

User's operating principle, verbatim:

> "不要只识别 siliconflow,重点识别 key。"

Translation for engineering: the resolver must select credentials **by what the key
can actually do at the target endpoint**, never by the provider-name hint in the env
variable. This principle applies **symmetrically** to rerank AND embedding paths —
it is not a rerank-only rule.

---

## 2. Rerank Side — Compliant

`reranker_client.py:71-231` already implements the validity-first probe per
`.claude_squad/decisions/2026-04-24-rerank-key-resolution-redesign.md` (Path B).

| Spec requirement | Code location | Status |
|---|---|---|
| Live 2xx probe before selection | L71-113 | ✅ |
| Per-process result cache | L47, L81-84 | ✅ |
| Log only `key_len` + last-4 on failure | L105-112 | ✅ |
| Explicit caller key bypasses probe | L210-211 | ✅ |
| `RERANK_KEY_PROBE_DISABLE=1` kill switch | L213-216 | ✅ |
| All-fail → loud WARN + static fallback | L223-228 | ✅ |
| Candidate order: `*_RERANK_*` > legacy > generic `*_API_KEY` | L130-141 | ✅ |

**Verdict — rerank:** No further action required here. The user's principle is
satisfied on the rerank call path.

---

## 3. Embedding Side — Non-Compliant (Symmetric Gap)

`runtime_env.py:83-170` `resolve_embedding_config` is **not** validity-first. Three
concrete gaps, each of which can reproduce the original 401 story in mirror form:

### 3.1 Gap A — No live probe

```python
# runtime_env.py:83-101 (excerpt)
def _select_embedding_provider():
    if env_value("SILICONFLOW_EMBEDDING_API_KEY", "SILICONFLOW_API_KEY"):
        return "siliconflow"   # picked on mere presence, not capability
    if env_value("JINA_API_KEY"):
        return "jina"
```

If `SILICONFLOW_API_KEY` happens to be a rerank-only key (mirror of the historical
embedding-only-key-misused-for-rerank bug), the embedding path 401s at first call.
No probe, no pre-flight, no cache — it will fail every cold start.

### 3.2 Gap B — `RERANK_API_KEY` pollutes embedding candidate list

```python
# runtime_env.py:152-160 (excerpt)
_clean(api_key) or env_value(
    "SILICONFLOW_EMBEDDING_API_KEY",
    "SILICONFLOW_API_KEY",
    "EMBEDDING_API_KEY",
    "RERANK_API_KEY",     # ← exact mirror of the 2026-04-24 rerank bug
    "API_KEY",
)
```

This line permits a rerank key to be submitted to an embedding endpoint.
This is the literal mirror image of the original bug the user ratified the fix for.
"重点识别 key" requires that a rerank-capable key never be offered to an embedding
endpoint purely because the embedding-scoped env slot is empty.

### 3.3 Gap C — String-replace provider inference

```python
# runtime_env.py:146-150 (excerpt)
if resolved_base_url and "embeddings" not in resolved_base_url:
    if "siliconflow" in resolved_base_url.lower():
        resolved_base_url = resolved_base_url.replace("/v1/rerank", "/v1/embeddings")...
```

This heuristic picks endpoint shape from substring match on provider name —
directly contradicting §2 of the rerank decision doc:
"Don't identify by provider name; identify by whether the key actually works."

### 3.4 Evidence this matters right now

- `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md §3.5.5` — the canary30
  post-reslice rebuild "被无效 embedding API key 凭证 (HTTP 401) 阻塞".
- `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md §3.6 Step 4` — gateway
  embedding acceptance "因 embedding credentials 仍返回 HTTP 401 未执行".
- `docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md §2026-04-24`
  — "embedding / rerank 401 根因已定位,但重设计待 Copilot 执行".

The rerank half of that sentence has shipped (§2 above). The embedding half has not.

---

## 4. Regression Risk Judgment

| Call path | Validity-first | Kill switch | Test coverage | Regression risk |
|---|---|---|---|---|
| Rerank (`reranker_client.py`) | ✅ yes | ✅ yes | ✅ yes | **Low** |
| Embedding (`runtime_env.py`) | ❌ no | ❌ no | ⚠️ env-presence only (`tests/test_embedding_provider_resolution.py`) | **High** |

The existing embedding tests assert **env-presence routing** (correct under a happy
path), but do not assert **capability-based routing**. If both `SILICONFLOW_API_KEY`
and `JINA_API_KEY` are present and the SiliconFlow one happens to be rerank-only,
current tests pass and production 401s.

---

## 5. Recommended Next Executor Action (Spec, not Code)

Mirror the rerank design onto the embedding resolver. Keep it proportional — the
embedding probe is cheaper than rerank (the request body is literally one short
string), so cost is not a blocker.

### 5.1 Minimal required surface

1. Add `_probe_embedding_key(api_key, base_url, model, *, timeout)` helper.
   Payload: `{"model": model, "input": "probe"}`. Success = HTTP 2xx. Same
   log-safety rules as `_probe_rerank_key` (no raw key logging).
2. Add `_KEY_PROBE_CACHE_EMBED: dict[tuple[str, str, str], bool]` — mirror of
   the rerank cache. Per-process, no disk.
3. Rewrite `resolve_embedding_config` so the key-selection loop probes each
   candidate in priority order, first 2xx wins, all-fail fires WARN and returns
   first candidate as static fallback.
4. **Candidate order for embedding** (mirror of rerank, but embedding-first):
   - `SILICONFLOW_EMBEDDING_API_KEY` — embedding-specific
   - `JINA_API_KEY` — jina has no rerank/embedding split, so same slot
   - `EMBEDDING_API_KEY` — legacy
   - `SILICONFLOW_API_KEY` — generic
   - **Do NOT include** `RERANK_API_KEY` in this list (closes Gap B).
5. Add `EMBEDDING_KEY_PROBE_DISABLE=1` kill switch — same escape hatch as rerank.
6. Drop the `.replace("/v1/rerank", "/v1/embeddings")` heuristic (Gap C). If the
   caller misconfigures `SILICONFLOW_EMBEDDING_BASE_URL` as a rerank URL, the
   probe will catch it loudly instead of silently rewriting URLs.

### 5.2 Test requirements (mirror of rerank §5.1-§5.4)

- Explicit key bypasses probe
- Validity-first picks the working key when multiple are present and one is
  rerank-only
- Kill switch restores static behavior
- All-probe-fail → WARN + fallback to first candidate
- Existing `test_embedding_provider_resolution.py` must still pass

### 5.3 DoD (mirrors rerank DoD §6)

1. `resolve_embedding_config()` returns first probe-OK key.
2. Explicit `api_key` bypasses probe.
3. `EMBEDDING_KEY_PROBE_DISABLE=1` works.
4. All-fail logs WARN with "All embedding key probes failed".
5. No raw key in logs.
6. Probe cached per process.
7. Live canary: `.env` with a rerank-only SiliconFlow key + a valid Jina key →
   resolver selects Jina, not SiliconFlow. `output/<run>.metrics.json`
   `embedding_api_avg_ms > 0` and no 401 in run log.

### 5.4 Explicit out-of-scope

- Do **not** remove `SILICONFLOW_API_KEY` env var — embeddings still need a
  generic-named key for users who haven't migrated.
- Do **not** touch `resolve_llm_config` — the LLM 401 path is separate and
  goes through `model_call_gateway`.
- Do **not** touch `reranker_client.py` — that side is already compliant.

---

## 6. Why This Unblocks Four Other Plans

Closing Gap A+B+C removes the single shared blocker cited in:

| Plan | Blocked DoD | Unblocks |
|---|---|---|
| `cost-and-defaults.md §3.3` | Phase 6 E1-E4 contextual comparison | Decision on whether to flip `use_contextual` default |
| `cost-and-defaults.md §3.5.5` | canary30 post-reslice A/B | Confirmation that reslice did not hurt recall |
| `cost-and-defaults.md §3.6 Step 4` | Gateway embedding cache hit DoD | Proof that §3.6 achieves the ≥60% rerank-call reduction |
| `cost-and-defaults.md §3.7` | Precompute 109-paper contextual summaries | Close §3.7 DoD and retire online contextual LLM calls |
| `advanced-retrieval.md §2026-04-24` | Full v2.1 vs canary recall gap root cause | Resume Phase 5/6 gate decisions |

**One fix, five unblocks.** ROI dominates every other item currently in the backlog.

---

## 7. Execution Hand-off

This memo is a **design input**, not an implementation. The next executor should:

1. Read this memo in full.
2. Read `.claude_squad/decisions/2026-04-24-rerank-key-resolution-redesign.md` for
   the shape of the rerank fix (literally mirror it).
3. Apply the changes specified in §5.1-§5.3 above.
4. Leave a completion note in `.squad/decisions/inbox/` per the rerank precedent.
5. Update `OPEN_THREADS.md` → close A11.E1 capability gap.

If the executor is a fresh Claude Code session, they can resume by reading this
file and the rerank redesign doc — no further Morpheus input needed.

---

## 8. What Morpheus Did NOT Do (by Design)

- Did not edit `runtime_env.py` — execution happens in a later step.
- Did not edit `.env` — this fix does not require env changes.
- Did not run live probes — that burns real API quota; the next executor does it
  only once during acceptance.
- Did not open the embedding probe cache in shared storage — per-process cache
  is sufficient and matches rerank precedent.
- Did not bundle this with any §5 A-tier upgrade (Redis/Postgres/etc.) — this is
  a B-tier normal fix per `cost-and-defaults.md §5.1.1`.

---

## 9. Traceability

- User directive (long-run session): "你直接推进,自决策" (2026-04-25)
- Principle ratified: "重点识别 key,不识别 siliconflow" (2026-04-24)
- Rerank-side precedent: `.claude_squad/decisions/2026-04-24-rerank-key-resolution-redesign.md`
- Rerank code (compliant): `reranker_client.py:71-231`
- Embedding code (non-compliant): `runtime_env.py:83-170`
- Embedding tests (env-presence only): `tests/test_embedding_provider_resolution.py`
- Blocked plans: see §6 above
