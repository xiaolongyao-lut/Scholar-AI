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
