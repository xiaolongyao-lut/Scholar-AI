# LLM-Wiki 集成切片 Runbook

> LMWR-473 · local wiki observability interface

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-473 |
| 简短描述 | 补齐 Wiki 本地可观测性：事件、指标、span 统一接口，默认本地 JSONL，无网络导出。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-05T00:45:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260505-001238-lmwr-473-wiki-observability-start` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260505-001238-lmwr-473-wiki-observability-start" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| Python logging HOWTO | `https://docs.python.org/3/howto/logging.html` | 使用标准 logger 做旁路诊断，不让日志路径改变业务语义。 |
| Python `time.perf_counter_ns` | `https://docs.python.org/3/library/time.html` | span duration 使用单调高精度计时，避免墙钟跳变影响耗时。 |
| OpenTelemetry Observability Primer | `https://opentelemetry.io/docs/concepts/observability-primer/` | 按 traces / metrics / logs 三类信号拆分；本轮只实现本地 facade，不接外部 exporter。 |
| 现有 recovery telemetry | `literature_assistant/core/recovery_telemetry.py` | 复用 span context manager 思路，但避免引入可选 OTel 依赖到 Wiki 切片。 |
| 现有 model gateway metrics | `literature_assistant/core/model_call_gateway.py` | JSONL 追加、fail-open、低耦合 metrics 记录模式。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `literature_assistant/core/wiki/observability.py` | 新增 `WikiObservabilitySink`、`emit_event`、`record_metric`、`start_span` / `trace_wiki_operation`，输出 `events.jsonl`、`metrics.jsonl`、`spans.jsonl`。 |
| `literature_assistant/core/project_paths.py` | 新增 `wiki_observability_path()`，路径落在 `workspace_artifacts/runtime_state/wiki/observability/`。 |
| `literature_assistant/core/wiki/query.py` | `WikiQueryIndex` 可注入 observability sink；search 记录 span 和 hit_count metric，不写原始 query。 |
| `literature_assistant/core/wiki/compiler.py` | `WikiCompiler` 可注入 observability sink；compile source/paper/project 记录完成事件、created/error metrics。 |
| `literature_assistant/core/wiki/doctor.py` | `WikiDoctor` 可注入 observability sink；doctor run 记录 span、完成事件和 check/error metrics。 |
| `tests/wiki/test_observability.py` | 覆盖 JSONL schema、脱敏、异常 span、禁用开关、路径 helper、query/compiler/doctor 集成。 |

---

## 4. 设计边界

- 默认本地：不联网、不引入 collector、不向外部 exporter 推送。
- 输出位置：`workspace_artifacts/runtime_state/wiki/observability/`。
- 输出文件：
  - `events.jsonl`
  - `metrics.jsonl`
  - `spans.jsonl`
- fail-open：磁盘写失败不阻断 query / compile / doctor。
- 脱敏规则：
  - `query` / `prompt` / `answer` / `text` / `body` / `path` / `api_key` / `token` 等 key 默认 redacted。
  - 长字符串、包含 secret pattern、包含私有路径形状、换行文本默认 redacted。
  - redacted payload 只保留 `hash`、`length`、`reason`，不回显原文。
- 可测注入：核心类只在传入 `observability_sink` 时写入，避免单元测试和离线批处理静默污染 runtime。

---

## 5. Verification

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_observability.py tests\wiki\test_query.py tests\wiki\test_compiler.py tests\wiki\test_doctor.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki\test_observability.py
```

| 检查项 | 结果 |
| ------ | ---- |
| observability + query/compiler/doctor focused pytest | PASS（61 passed） |
| compileall | PASS |

---

## 6. 结论

- LMWR-473 已落成统一本地观测接口，覆盖日志/事件、指标和追踪 span 三类信号。
- Wiki 的 query/compiler/doctor 可用同一 sink 记录本地 JSONL，且不会把用户 query、私有路径、API key、正文片段写入观测文件。
- 未引入新依赖、未改变默认 RAG 主链、未开启任何网络导出。

---

## 7. Open / 后续

- 若后续独立窗口需要诊断页，可只读展示 `events.jsonl` / `metrics.jsonl` / `spans.jsonl` 的聚合结果。
- LMWR-470 已完成只读复盘；下一 gate 是 cache/corpus manifest 对齐后再重跑 canary30 control。
