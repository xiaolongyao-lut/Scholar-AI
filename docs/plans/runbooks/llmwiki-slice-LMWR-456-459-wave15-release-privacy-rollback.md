# LLM-Wiki 集成切片 Runbook

> LMWR-456 / LMWR-457 / LMWR-458 / LMWR-459 · Wave 15 release, privacy, rollback checklists

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-456、LMWR-457、LMWR-458、LMWR-459 |
| 简短描述 | 前端/后端发布清单、隐私安全清单、回滚清单。 |
| Wave | Wave 15 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:10:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-210800-llmwiki-wave15-release-checklists-start` |
| 恢复命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-210800-llmwiki-wave15-release-checklists-start" --confirm-restore` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 关键借鉴点 |
| ---- | ---- | ---- |
| Vite production build | `https://vite.dev/guide/build` | 发布前明确运行 production build，确认前端产物可生成。 |
| pytest good integration practices | `https://pytest.org/en/7.4.x/goodpractices.html` | 测试发现、focused tests、collect-only 作为发布门禁。 |
| OWASP Secrets Management | `https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html` | secret 不入日志、不入归档、不入 repo；使用专用流程处理凭据。 |
| OWASP Logging | `https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html` | 日志可能携带敏感信息，发布/导出前需要最小化和脱敏检查。 |
| SwarmVault STABILITY / CHANGELOG | `C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main\CHANGELOG.md` | stable surface、migration step、doctor structured JSON、MCP-facing version 同步。 |

---

## 3. LMWR-456：Frontend Release Checklist

发布前置：

- 已创建 rollback checkpoint。
- 已读取 Vite 官方生产构建说明或本 runbook 成熟方案记录。
- 不修改 `.env`、qrels/goldset、默认 RAG 链。
- 前端 wiki workbench 仍 default-off / backend contract-driven。

命令：

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend
npm run build
npm run test -- --run
```

可选 UI smoke：

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend
npm run dev
```

人工检查：

- Wiki workbench 能显示 disabled/status/doctor，不要求启用 wiki-first。
- Compile preview / readonly panels / citation warnings / evidence wiki links 不遮挡主聊天流。
- 没有把本机绝对路径、source text、secret、外部库路径显示到用户不需要看到的位置。

停止条件：

- build 失败。
- 任何测试需要联网或真实模型调用。
- 需要修改 OpenAPI 契约但未同步 backend/router/schema。

---

## 4. LMWR-457：Backend Release Checklist

发布前置：

- 已创建 rollback checkpoint。
- 已读取 pytest 官方实践或本 runbook 成熟方案记录。
- 不启用 `LITERATURE_ASSISTANT_WIKI_FIRST_RETRIEVAL` 作为默认。
- 不执行外部 Zotero/EndNote/Obsidian 写回。

命令：

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\__main__.py tests\wiki
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
```

API / CLI smoke：

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki status
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki doctor
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-release-smoke.zip
```

停止条件：

- `tests/wiki` 回归失败。
- collect-only 测试数量异常下降。
- CLI 输出不再是 JSON。
- system verification 出现 failed/warnings。

---

## 5. LMWR-458：Privacy / Security Checklist

发布前置：

- 已读取 OWASP Secrets / Logging 或本 runbook 成熟方案记录。
- 备份归档只写本地 `workspace_artifacts/backups/` 或用户显式指定路径。
- migration dry-run 不输出全文 source body。

检查命令：

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
rg -n --glob '!github/**' --glob '!C:\Users\xiao\Downloads\llmwiki借鉴库/**' "api[_-]?key|secret|password|token|BEGIN (RSA|OPENSSH|PRIVATE) KEY" docs\plans literature_assistant\core\wiki tests\wiki
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-privacy-smoke.zip
```

人工检查：

- 任何 runbook 中出现的绝对路径仅限本机项目路径、回档路径、只读参考路径。
- CLI JSON 不包含 `.env` 内容、provider key、完整文献正文。
- connector warning 使用 sanitized error，不泄露 private file path。
- backup manifest 可包含 artifact path/checksum，但不包含 source body。
- 外部参考库路径只记录为参考，不复制代码。

停止条件：

- 检测到 secret-like 字符串且无法证明为测试 fixture。
- backup 或 migration 把 source text/full prompt/full answer 放入 manifest。
- 需要写外部系统或上传备份。

---

## 6. LMWR-459：Rollback Checklist

回滚只在用户明确要求“回滚/恢复/撤销本次改动”时执行。

查看 checkpoint：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
```

恢复代码 checkpoint：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```

恢复 wiki artifact：

1. 找到备份 zip 和旁路 manifest。
2. 解压到临时目录，不直接覆盖。
3. 对比 manifest 中 `sha256`。
4. 停止相关进程后再替换：

```powershell
$repo = "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
$restore = "C:\path\to\unzipped\backup"
Copy-Item -LiteralPath "$restore\runtime\wiki.db" -Destination "$repo\workspace_artifacts\runtime_state\wiki\wiki.db" -Force
Copy-Item -LiteralPath "$restore\runtime\graph.json" -Destination "$repo\workspace_artifacts\runtime_state\wiki\graph.json" -Force
Copy-Item -LiteralPath "$restore\generated\wiki" -Destination "$repo\workspace_artifacts\generated\wiki" -Recurse -Force
```

恢复后验证：

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki doctor
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
```

---

## 7. 本轮验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\__main__.py tests\wiki docs\plans
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-wave15-smoke.zip
```

| 检查项 | 结果 |
| ------ | ---- |
| `pytest tests/wiki -q` | PASS（297 passed） |
| compileall | PASS |
| `run_literature_assistant.py paths` | PASS |
| `system_verification.py --json` | PASS（23 passed / 0 failed / 0 warnings） |
| wiki backup dry-run smoke | PASS（JSON 输出；当前无 runtime wiki artifacts，因此 `ok=false` 且 `would_write=false`，未写 zip） |

---

## 8. Next

- LMWR-460：用户使用指南草稿。
- LMWR-461：更新 master plan 状态引用。
- LMWR-462：端到端 dry-run 验收。
- LMWR-463：最终 gate 和证据包。
