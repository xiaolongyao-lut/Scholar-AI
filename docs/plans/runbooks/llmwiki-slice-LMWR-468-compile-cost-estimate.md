# LLM-Wiki 集成切片 Runbook

> LMWR-468 · Wiki compile dry-run token/cost estimate

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-468 |
| 简短描述 | 在 Wiki compiler dry-run / API / 前端工作台中显示 token 估算、成本估算、pricing source 和 budget checks。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:45:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-213109-llmwiki-lmwr468-cost-estimate-align` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-213109-llmwiki-lmwr468-cost-estimate-align" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| OpenAI API pricing | `https://platform.openai.com/docs/pricing/` | 模型价格按时间变化，不能把当前价格硬编码进 compiler；必须由显式配置或模型网关传入。 |
| 本地 LLM gateway | `literature_assistant/core/wiki/llm_gateway.py` | 已有 `tokens_used` / `cost_usd=0.0` stub contract；compiler dry-run 延续“估算不是账单”的边界。 |
| 本地 model call gateway | `literature_assistant/core/model_call_gateway.py` | 已有 `budget_estimate_tokens` 进入 gateway metrics；compiler 使用同类 token planning 字段。 |
| 本地 cost router | `literature_assistant/core/routers/llm_cost_router.py` | 真实账单/运行统计来自日志聚合，compile estimate 不伪装成实际 cost log。 |
| Wave 14 cost guard | `docs/plans/runbooks/llmwiki-slice-LMWR-439-wave14-compile-cost-guard.md` | 继承 `CompileBudget` / `CompileBudgetCheck` hard guard，把估算结果暴露给 dry-run。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `literature_assistant/core/wiki/compiler.py` | 新增 `CompilePricing`、`CompileCostEstimate`、`estimate_compile_cost()`、`compile_pricing_from_env()`；`CompileResult` 增加 `budget_checks` 和 `cost_estimate`。 |
| `literature_assistant/core/routers/wiki_router.py` | `/api/wiki/compile` 在 registry 存在时执行 read-only compiler dry-run，返回 `created/updated/skipped`、`budget_summary`、`budget_checks`、`errors`；缺 registry 时不创建 DB。 |
| `frontend/src/services/wikiApi.ts` | strict parser 增加 budget summary / checks / created / skipped / errors。 |
| `frontend/src/types/wiki.ts` | 增加 compile budget summary/check 类型。 |
| `frontend/src/components/wiki/WikiCompileDryRunPanel.tsx` | Dry-run console 增加 tokens、cost、pricing source、configured 状态展示。 |
| `frontend/openapi/modular-pipeline-openapi.json`、`frontend/src/generated/openapi.ts` | 重新生成 OpenAPI schema/types。 |
| `tests/wiki/test_compiler.py`、`tests/wiki/test_wiki_router.py`、`frontend/src/services/wikiApi.test.ts` | 覆盖 cost estimate、env pricing、API payload、frontend parser。 |

---

## 4. 配置

默认不硬编码任何线上模型价格，因此 `estimated_cost_usd=0.0` 且 `pricing_configured=false`。如需在 dry-run 中显示当日模型价，先核对官方 pricing，再显式配置：

```powershell
$env:LITERATURE_ASSISTANT_WIKI_COMPILE_INPUT_USD_PER_1M_TOKENS = "<input-rate>"
$env:LITERATURE_ASSISTANT_WIKI_COMPILE_OUTPUT_USD_PER_1M_TOKENS = "<output-rate>"
$env:LITERATURE_ASSISTANT_WIKI_COMPILE_ESTIMATED_OUTPUT_TOKENS = "<reserved-output-tokens>"
$env:LITERATURE_ASSISTANT_WIKI_COMPILE_PRICING_SOURCE = "manual-verified-YYYY-MM-DD"
```

---

## 5. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_compiler.py tests\wiki\test_wiki_router.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki\compiler.py literature_assistant\core\routers\wiki_router.py tests\wiki\test_compiler.py tests\wiki\test_wiki_router.py
cd frontend
npm run test -- --run src/services/wikiApi.test.ts
npm run build
npm run generate:openapi
cd ..
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_compiler.py tests\wiki\test_wiki_router.py tests\wiki\test_wave15_end_to_end.py -q
```

| 检查项 | 结果 |
| ------ | ---- |
| compiler/router focused pytest | PASS（28 passed） |
| compileall | PASS |
| frontend wikiApi focused Vitest | PASS（11 passed） |
| frontend build | PASS |
| OpenAPI regenerate | PASS |
| compiler/router/Wave15 E2E focused pytest | PASS（29 passed） |

---

## 6. Open / 后续

- 真实模型价格仍需按当日官方 pricing 或 provider billing config 显式注入，不允许自动猜价。
- 当前 compile API 仍只允许 dry-run；non-dry-run 继续返回 400。
- `project_id` 仍是 forward-compatible 字段，当前实际计划以 wiki registry/source 为准。
