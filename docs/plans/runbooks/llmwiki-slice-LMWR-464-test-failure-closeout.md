# LLM-Wiki 集成切片 Runbook

> LMWR-464 · remaining test failure closeout

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-464 |
| 简短描述 | 复核并修复剩余全量 pytest 失败，使 LLM-Wiki/RAG 补充任务测试状态与当前项目事实对齐。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T22:25:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-220759-llmwiki-lmwr464-full-pytest-triage` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-220759-llmwiki-lmwr464-full-pytest-triage" --confirm-restore
```

---

## 2. 成熟方案 / 本地证据

| 来源 | 借鉴点 |
| ---- | ---- |
| `docs/analysis/legacy-test-triage-20260503.md` | 原始失败从 59 -> 22 -> 约 4-6 的分类，剩余包含 legacy export 与 contextual validation。 |
| `docs/plans/active/gap-fix-status.md` | 最新文档事实已提示只剩 2 个失败，但主计划未同步。 |
| `AI_WORKSPACE_GUIDE.md` | 测试修复保持小范围，先 focused regression，再全量门禁。 |
| Python subprocess/json behavior | CLI wrapper 必须在脚本执行时输出 stdout JSON，不能只是 import shim。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `gateb_phase_b_pool_export.py` | 根目录 shim 新增 `main()` 和 `if __name__ == "__main__"`，脚本执行时转发 core CLI。 |
| `literature_assistant/core/gateb_phase_b_pool_export.py` | 兼容迁移后的 `workspace_tests/evaluation_data/` fixture 路径；默认输入路径改到当前 fixture 根；`_compute_file_hash()` 类型修正为 `str | None`。 |
| `tests/legacy_root/test_gateb_c6_repro.py` | 将 C6 reproducibility 测试改为临时目录 + tiny deterministic corpus，不再依赖真实 eval 数据或长耗时检索。 |
| `scripts/validate_contextual_miss.py` | validation-only contextual coverage 调用传入 `api_key="validation-only"`，确保缺 summary 时写入 validation miss log。 |

---

## 4. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m compileall -q gateb_phase_b_pool_export.py literature_assistant\core\gateb_phase_b_pool_export.py scripts\validate_contextual_miss.py tests\legacy_root\test_gateb_c6_repro.py tests\test_validate_contextual_miss.py
& .\.venv-1\Scripts\python.exe -m pytest tests\legacy_root\test_gateb_c6_repro.py tests\test_validate_contextual_miss.py -q
& .\.venv-1\Scripts\python.exe -m pytest tests -q
```

| 检查项 | 结果 |
| ------ | ---- |
| focused compileall | PASS |
| focused regression | PASS（5 passed） |
| full pytest | PASS（1632 passed, 3 skipped） |

---

## 5. Open / 后续

- LMWR-466 / LMWR-470 / LMWR-472 / LMWR-473 已按 `docs/plans/active/llmwiki-autonomy-authorization.md` 获得一次性授权。
- 继续前仍必须创建 checkpoint、搜索成熟方案、focused verification，并在修改/删除/评测基线演进前完成备份和恢复路径记录。
