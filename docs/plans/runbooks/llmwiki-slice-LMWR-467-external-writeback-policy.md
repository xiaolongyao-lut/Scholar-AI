# LLM-Wiki 集成切片 Runbook

> LMWR-467 · external knowledge-base write-back policy

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-467 |
| 简短描述 | 补充 Zotero / EndNote / Obsidian 外部知识库写回策略，明确默认不写回、触发条件、边界和回滚机制。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T22:05:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-215509-llmwiki-lmwr467-writeback-policy` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-215509-llmwiki-lmwr467-writeback-policy" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| Zotero Web API write requests | `https://www.zotero.org/support/dev/web_api/v3/write_requests` | 写操作需要官方 API、权限和版本/冲突控制；不能直接写本地 SQLite。 |
| Zotero Web API basics | `https://www.zotero.org/support/dev/web_api/v3/basics` | 远程写回应走官方 API 语义；当前 connector 不引入凭据和网络写入。 |
| Obsidian plugin API `Vault` | `https://docs.obsidian.md/Reference/TypeScript+API/Vault` | Obsidian 写入属于插件/应用级 mutation，不能由后台 agent 静默改 vault。 |
| Obsidian `Vault.modify` | `https://docs.obsidian.md/Reference/TypeScript+API/Vault/modify` | 未来如写 vault，必须是文件级、用户确认、可 diff 的显式改动。 |
| Wave 13 read-only connectors | `docs/plans/runbooks/llmwiki-slice-LMWR-419-433-wave13-connectors.md` | 继承 `read_only=true`、`writes_user_library=false`、`would_write=false`。 |

---

## 3. 核心落点

| 文件 | 覆盖 |
| ---- | ---- |
| `docs/plans/specs/external-knowledge-writeback-policy.md` | 新增写回策略：默认不写回、future trigger、字段白名单/黑名单、rollback boundary、future data contract。 |
| `docs/plans/runbooks/llmwiki-slice-LMWR-467-external-writeback-policy.md` | 记录本切片回档、成熟方案、验证和后续边界。 |
| `docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md` | 标记 LMWR-467 完成，补充风险缓解和证据。 |
| `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md` | 更新 D13 外部写回策略决策。 |

---

## 4. 实现事实

- 本切片没有引入任何写回代码。
- Zotero / EndNote / Obsidian 仍为 read-only / spec-only / no-write 方向。
- 任何 future write-back 都必须先产生 dry-run diff、backup/export、operation journal，并经过用户显式确认。
- Codex checkpoint restore 只能回滚项目文件，不能自动回滚已经同步到外部工具的数据；该限制已写入 spec。

---

## 5. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m compileall -q docs\plans literature_assistant\core\wiki\connectors tests\wiki\test_connectors.py
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_connectors.py -q
```

| 检查项 | 结果 |
| ------ | ---- |
| docs/connectors compileall | PASS |
| connector focused pytest | PASS（10 passed） |

---

## 6. Open / 后续

- LMWR-466 前端 E2E 测试框架仍未完成。
- LMWR-471/472/473 性能、安全、可观测性仍可继续长跑。
- 任何直接写外部工具的实现都必须另开任务，并先停下请求用户授权。
