---
name: "rerank-provider-routing"
description: "Provider-aware rerank config for SiliconFlow and DashScope qwen3-vl-rerank"
domain: "retrieval"
confidence: "high"
source: "Trinity rerank switch"
---

## Pattern

- Resolve rerank provider from config signals instead of swapping one global default.
- Keep `SILICONFLOW_RERANK_*` on the SiliconFlow flat payload (`query`, `documents`, `top_n`).
- Use DashScope when `DASHSCOPE_*` is present or the model/url already points at DashScope.

## DashScope Text-Only Mode

- `qwen3-vl-rerank` can still be used for text-only rerank.
- Send the DashScope payload as:
  - `model: "qwen3-vl-rerank"`
  - `input.query: <string>`
  - `input.documents: [<string>, ...]`
  - `parameters.top_n`
- Parse results from `body["output"]["results"]`.

## Guardrail

- Do not silently point the SiliconFlow default URL at DashScope; preserve backward compatibility unless DashScope config is explicitly selected.

## Validity-first key selection

- When multiple rerank credentials coexist, keep provider/url/model resolution unchanged and change only the key-choice step.
- Trust an explicit caller-passed key immediately.
- For env-derived keys, probe candidates against the resolved `(base_url, model)` with a tiny one-doc request and cache the boolean result per process.
- If every probe fails, fall back to the old provider-specific static key order and emit a loud warning.
- Keep a rollback lever: `RERANK_KEY_PROBE_DISABLE=1` should restore pre-probe static key selection.
- Never log raw keys; on probe failure log only `key_len` and a masked suffix.
