# LLM-Wiki 集成切片 Runbook

> LMWR-439 · Wave 14 compile cost guard

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-439 |
| 简短描述 | 为 wiki compiler 增加 hard compile budget guard，超预算拒绝写入。 |
| Wave | Wave 14 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T20:52:00+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-203528-llmwiki-wave14-fixtures-no-secret` |

---

## 2. 参考目录

| 来源 | 参考点 | 本轮借鉴 |
| ---- | ------ | -------- |
| `literature_assistant/core/wiki/llm_gateway.py` | `calculate_token_budget()` / `truncate_to_budget()` 已有 token budget helper | Compiler guard 使用 source chunks 的 chars/token 粗估，先拒绝超预算输入。 |
| `literature_assistant/core/wiki/compiler.py` | 当前 compile source/paper/project 均为 deterministic/stub 路径 | Guard 放在 `compile_source()` 写页面前，避免未来 LLM-backed prompt 构建越界。 |
| `tests/wiki/test_compiler.py` | dry-run 与 real compile 都要求不写盘可验证 | 超预算 real/dry-run 都返回 skipped + error，不写 page store。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `literature_assistant/core/wiki/compiler.py` | 新增 `CompileBudget`、`CompileBudgetCheck`、`check_compile_budget()`；`WikiCompiler` 接受 optional budget；`compile_source()` 在写入前执行 hard guard。 |
| `tests/wiki/test_compiler.py` | 新增超 chunks、超 chars、budget estimate focused tests。 |

---

## 4. 实现事实

- 默认 budget：`max_source_chunks=100`、`max_total_chunk_chars=50000`、`max_estimated_tokens=12500`、`chars_per_token=4.0`。
- 超预算时 `compile_source()` 返回 `CompileResult(created=0, updated=0, skipped=1, errors=[...])`。
- dry-run 遇到超预算也报告 refusal，不假装可创建页面。
- Guard 不改变小输入旧行为；原 compiler focused tests 继续通过。

---

## 5. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_compiler.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki\compiler.py tests\wiki\test_compiler.py
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_compiler.py tests\wiki\test_llm_gateway.py tests\wiki\test_evaluation.py tests\wiki\test_doctor.py tests\wiki\test_graph.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki workspace_tests\fixtures
```

| 检查项 | 结果 |
| ------ | ---- |
| compiler focused tests | PASS（13 tests） |
| compiler compileall | PASS |
| compiler/llm/eval/doctor/graph focused group | PASS（55 tests） |
| wiki package/test/fixture compileall | PASS |

---

## 6. Open / 后续

- `LMWR-441` performance baseline 仍未实现。
- `LMWR-443` CI-friendly test subset marker 仍未实现。
- `LMWR-447` / `LMWR-448` collect-only / workspace verification 仍未收口。
