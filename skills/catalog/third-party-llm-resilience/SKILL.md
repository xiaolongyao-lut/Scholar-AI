---
name: third-party-llm-resilience
description: Use when calling third-party Claude / OpenAI-compatible / Gemini proxies, debugging LLM stalls, 502/504/overloaded_error, mid-stream drops, "task feels dumb / forgets context" symptoms, or hardening any HTTP-based LLM client.
---

# Third-Party LLM Resilience

## Why this exists

Direct vendor APIs (`api.anthropic.com`, `api.openai.com`) are usually stable. Third-party proxies are not. They commonly:

- Truncate `max_tokens` silently (answer cuts off mid-sentence).
- Strip `tool_use` / function-calling / extended-thinking blocks (model "feels dumb").
- Time out after 60–90s even for legitimate long generations.
- Return `502 / 503 / 504 / 529` or Anthropic `overloaded_error` under load.
- Drop the TCP connection mid-stream with no clean SSE close.
- Return a 200 response with `content: []` (empty content blocks) instead of an error.

Single-shot `httpx.post(..., timeout=120)` with no retry will collapse on all of the above.

## The five rules

1. **Timeout ≥ 180s for non-streaming chat, ≥ 600s for batched/agent calls.** 120s is too short for proxies that buffer the entire Claude response before forwarding.
2. **Retry transient failures with exponential backoff + jitter.** Retryable: connection error, `408 / 409 / 425 / 429 / 500 / 502 / 503 / 504 / 529`, Anthropic `overloaded_error`, `api_error`. Default 2 retries, base 1.5s.
3. **Prefer streaming (SSE) for any answer > ~500 tokens.** Streaming surfaces partial output before the proxy times out, and lets the client detect mid-stream drops.
4. **Cap `max_tokens` per call and chunk long generations.** Many proxies hard-cap at 4096 even when the model supports 8192+. If you need more, split the task.
5. **Validate the response shape before treating it as success.** `200 OK` with empty `content` / `choices[0].message.content == ""` is a silent failure — log it and retry once.

## Knobs in this repo

Backend (`routers/chat_router.py` `/chat/ask`) honors:

| Env var                  | Default | Meaning                                       |
| ------------------------ | ------- | --------------------------------------------- |
| `LLM_HTTP_TIMEOUT`       | `180`   | httpx total timeout in seconds                |
| `LLM_HTTP_RETRIES`       | `2`     | Retry count on transient failures             |
| `LLM_HTTP_BACKOFF_BASE`  | `1.5`   | Base seconds for exponential backoff          |

Frontend (`frontend/src/services/chatApi.ts`):

- `askChatWithConfig({ timeoutMs })` defaults to 120000 ms; bump to 180000+ for Claude through proxies.
- `isConnectivityOrModelError` already catches `408/429/5xx`, network errors, `model_not_found`, and `InvalidEndpointOrModel.NotFound` for the Copilot fallback path.

## Provider-specific quirks

**Claude (Anthropic format)**
- Always send `anthropic-version: 2023-06-01` header (already done).
- For long-context use add `anthropic-beta: prompt-caching-2024-07-31` (saves money on repeated system prompts).
- `system` is a top-level field, NOT a message — already handled.
- Empty `content: []` after a 200 = silently truncated — treat as retryable.

**OpenAI-compatible proxies (OpenRouter, DeepSeek, Moonshot, etc.)**
- They often re-map model names. Always log `data.model` returned by the proxy.
- `tool_calls` may be dropped entirely. If you depend on tools, verify the response actually contains them, otherwise fall back to JSON-mode + manual parse.

**Gemini direct**
- Long-running calls fine, but cold-starts can take 10–30s — do not retry too aggressively or you'll DDoS yourself.

## Symptoms → root cause table

| Symptom                              | Likely cause                                | Action                                          |
| ------------------------------------ | ------------------------------------------- | ----------------------------------------------- |
| "Model feels dumb / forgets context" | Proxy stripped tool_use or extended-thinking | Switch to direct vendor; or disable thinking    |
| Answer cut off mid-sentence          | `max_tokens` capped by proxy                | Lower per-call ask, chunk task, or change proxy |
| Random 502 every few minutes         | Proxy backend overloaded                    | Retry with backoff (already on)                 |
| `content: []` 200 OK                 | Silent truncation / model refusal           | Retry once, then surface error to user          |
| Connection reset after 60s           | Proxy timeout < server timeout              | Use streaming, or shorter prompts               |

## Anti-patterns

- ❌ Single `httpx.post` with no retry on a proxy URL.
- ❌ Catching `Exception` and returning empty string ("silent failure" — violates §4 of repo guidance).
- ❌ Setting `max_tokens = 32768` and hoping the proxy honors it.
- ❌ Hard-coding `timeout=60` in any LLM client path.
- ❌ Treating HTTP 200 as automatic success without inspecting the body shape.

## Related skills

- `systematic-debugging` — apply Phase 1 root-cause investigation before blaming "the model".
- `long-task-checkpoint` (prompt) — when a long agent run goes through a flaky proxy, write checkpoints so you can resume mid-task.
- `windows-shell-discipline` — Windows users hitting LLM CLIs through Bash often see "command not found" that masquerades as an LLM failure.
