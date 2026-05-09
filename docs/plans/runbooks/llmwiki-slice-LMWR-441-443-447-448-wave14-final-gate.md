# LLM-Wiki 集成切片 Runbook

> LMWR-441 / LMWR-443 / LMWR-447 / LMWR-448 · Wave 14 final gate

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-441、LMWR-443、LMWR-447、LMWR-448 |
| 简短描述 | 新增 zero-cost performance baseline、CI-friendly marker，并执行 Wave 14 收口验证。 |
| Wave | Wave 14 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T20:58:00+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-203528-llmwiki-wave14-fixtures-no-secret` |

---

## 2. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `tools/eval/wiki_wave14_performance_baseline.py` | LMWR-441：临时目录内运行 source compile -> query index -> query search，stdout 输出 JSON，不写 runtime artifacts。 |
| `pytest.ini` | LMWR-443：注册 `wiki_wave14` marker。 |
| `tests/wiki/test_evaluation.py` | LMWR-443：模块级 `pytestmark = pytest.mark.wiki_wave14`。 |

---

## 3. Performance Baseline

命令：

```powershell
& .\.venv-1\Scripts\python.exe tools\eval\wiki_wave14_performance_baseline.py --pretty
```

结果：

```json
{
  "compile_ms": 4.929,
  "created_pages": 2,
  "error_count": 0,
  "index_ms": 10.676,
  "mode": "zero_cost_temp_workspace",
  "query_hit_count": 1,
  "query_ms": 0.224,
  "schema_version": 1,
  "skipped_pages": 0,
  "updated_pages": 0
}
```

备注：首次运行发现 Windows 下临时 SQLite 文件句柄在 `TemporaryDirectory` 清理时未及时释放；已在脚本返回前显式 `gc.collect()`，复跑通过，并清理了失败遗留的 `%TEMP%\wiki-wave14-baseline-*` 目录。

---

## 4. 收口验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -m wiki_wave14 -q
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki workspace_tests\fixtures
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
```

| 检查项 | 结果 |
| ------ | ---- |
| `pytest tests/wiki -m wiki_wave14 -q` | PASS（11 passed / 276 deselected） |
| `pytest tests/wiki/test_evaluation.py -q` | PASS（11 tests） |
| `pytest tests --collect-only -q` | PASS（1618 tests collected） |
| `compileall literature_assistant/core/wiki tests/wiki workspace_tests/fixtures` | PASS |
| `pytest tests/wiki -q` | PASS（287 tests） |
| `run_literature_assistant.py paths` | PASS（canonical paths printed as JSON） |
| `system_verification.py --json` | PASS（23 passed / 0 failed / 0 warnings） |

---

## 5. Open / 后续

- Wave 14 is functionally closed for the planned zero-cost quality gates.
- Wave 15 remains paused until migration / release / MCP / long-term maintenance work starts.
- Full frontend build/test was not rerun in this Wave 14 backend/eval slice; last recorded Wave 12 frontend gate remains `54 passed` + build PASS.
