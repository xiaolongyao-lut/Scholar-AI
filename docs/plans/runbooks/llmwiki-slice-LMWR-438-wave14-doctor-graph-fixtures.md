# LLM-Wiki 集成切片 Runbook

> LMWR-438 · Wave 14 doctor / graph smoke fixtures

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-438 |
| 简短描述 | 新增 duplicate / orphan / broken-link doctor graph fixtures。 |
| Wave | Wave 14 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T20:47:00+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-203528-llmwiki-wave14-fixtures-no-secret` |

---

## 2. 参考目录

| 来源 | 参考点 | 本轮借鉴 |
| ---- | ------ | -------- |
| `literature_assistant/core/wiki/doctor.py` | `check_graph()` 输出 broken/orphan/duplicate metrics | Fixture 锁定这三个指标的组合回归。 |
| `literature_assistant/core/wiki/graph.py` | path-based node id、wikilink edge、duplicate candidate 规则 | Fixture 使用两个相似 concept page 与一个 missing wikilink。 |
| `tests/wiki/test_doctor.py` | 临时目录 doctor graph focused 测试 | 新增 workspace fixture 版本，防止后续示例数据漂移。 |

---

## 3. 文件落点

| 文件 | 覆盖 |
| ---- | ---- |
| `workspace_tests/fixtures/wiki_graph_doctor_smoke/pages/concepts/alpha-model.md` | broken-link source page。 |
| `workspace_tests/fixtures/wiki_graph_doctor_smoke/pages/concepts/alpha-models.md` | duplicate candidate + orphan page。 |
| `tests/wiki/test_doctor.py` | fixture-based doctor graph assertion。 |

---

## 4. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_doctor.py tests\wiki\test_graph.py tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki workspace_tests\fixtures
```

| 检查项 | 结果 |
| ------ | ---- |
| doctor/graph/evaluation focused group | PASS（27 tests） |
| wiki package/test/fixture compileall | PASS |

---

## 5. Open / 后续

- `LMWR-439` compile cost guard 仍未做。
- `LMWR-443` CI-friendly test subset marker 仍未做。
- `LMWR-447` / `LMWR-448` collect-only / workspace verification 仍未收口。
