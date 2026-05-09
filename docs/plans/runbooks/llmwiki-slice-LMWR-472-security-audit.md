# LLM-Wiki 集成切片 Runbook

> LMWR-472 · local lightweight wiki security gate

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-472 |
| 简短描述 | 按用户授权补齐本地轻量安全门禁：路径越界、输入校验、只读边界、绝对路径泄露防护。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-05T00:20:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-235259-lmwr-472-wiki-security-audit-start` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-235259-lmwr-472-wiki-security-audit-start" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| OWASP ASVS / Cheat Sheets | `https://owasp.org/` | 本轮聚焦输入校验、路径遍历、错误/日志最小泄露、访问控制边界。 |
| OWASP LLM / RAG 风险分类 | `https://owasp.org/` | 用户授权中的 RAG/LLM evidence boundary 落成“网络内容不能静默进入本地知识链”。 |
| FastAPI security guidance | `C:\Users\xiao\.codex\skills\security-best-practices\references\python-fastapi-web-server-security.md` | 路由参数必须 schema 化、拒绝不支持字符、错误信息最小暴露。 |
| React security guidance | `C:\Users\xiao\.codex\skills\security-best-practices\references\javascript-typescript-react-web-frontend-security.md` | 前端不应暴露不必要的本地私有路径；深链路径必须显式规范化。 |
| 现有本地安全基线 | `literature_assistant/core/wiki/connectors/base.py`、`frontend/src/lib/evidenceReferences.ts` | 已有 connector allowed-root 和前端 wiki path normalize，可在 router / backup 继续补齐。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `literature_assistant/core/routers/wiki_router.py` | 新增 filter token / identifier / page path 校验；status 路径脱敏；review filter 非法值改为 400；compile source/project id 非法字符改为 400。 |
| `literature_assistant/core/wiki/backup.py` | backup 只收集留在声明 allowed root 内的真实文件；越界文件标记 `outside_allowed_root`，不写入 zip。 |
| `tests/wiki/test_wiki_router.py` | 增加非法 `kind/status`、路径逃逸、非法 `source_id`、status path 脱敏等用例。 |
| `tests/wiki/test_backup.py` | 增加 generated 文件越 allowed root 时不打包的测试；Windows 无 symlink 权限时 skip。 |

---

## 4. 落地门禁

### 4.1 输入校验

- `/api/wiki/pages` 的 `kind` / `status` 现在只接受简单 lowercase token，非法形状返回 400。
- `/api/wiki/review` 的 `status` / `kind` 非法值不再冒成 500，而是明确 400。
- `/api/wiki/compile` 的 `source_id` / `project_id` 现在拒绝空白和不支持字符。
- `/api/wiki/pages/{page_path}` 现在拒绝绝对路径、`..`、控制字符和非 markdown 扩展。

### 4.2 私有路径最小泄露

- `/api/wiki/status` 不再把真实绝对路径直接返回前端。
- repo 内路径显示为相对仓库路径。
- repo 外路径显示为 `<external>/<name>`，只保留最小定位信息。

### 4.3 只读边界 / 备份边界

- `build_wiki_backup_plan()` 收集文件时会验证真实解析后的文件仍在声明的 allowed root 内。
- 指向 allowed root 外的文件不会被打进 archive，报告里记为 `outside_allowed_root`。
- 这条规则用于防止 symlink / junction / alias 把备份收集器带出目标根目录。

---

## 5. Verification

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_wiki_router.py tests\wiki\test_backup.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\wiki_router.py literature_assistant\core\wiki\backup.py tests\wiki\test_wiki_router.py tests\wiki\test_backup.py
```

| 检查项 | 结果 |
| ------ | ---- |
| router + backup focused pytest | PASS（19 passed, 1 skipped） |
| compileall | PASS |

`1 skipped` 原因：
- 当前 Windows 环境没有创建 symlink 的权限，越界 symlink 测试自动 skip；不影响本轮逻辑门禁。

---

## 6. 结论

- LMWR-472 本轮按用户授权落成“本地轻量安全门禁”，不是外部渗透测试。
- 已覆盖最直接的输入越界、私有路径泄露、review/filter 500 误报和 backup 越根目录打包风险。
- 没有引入任何联网扫描、账号动作或外部库写回。

---

## 7. Open / 后续

- 仍可继续补一版更系统的 no-secret trace / doctor report scan，把 query trace、doctor report、frontend error string 纳入统一脱敏检查。
- LMWR-473 可继续把 query/compile/doctor 日志、指标和 trace contract 统一起来。
- LMWR-470 仍待对 chunk 参数 200/8 做备份后的对照评测复核。
