# LLM-Wiki 集成切片 Runbook

> LMWR-419 ~ LMWR-433 · Wave 13 read-only connectors

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-419、LMWR-420、LMWR-421、LMWR-422、LMWR-423、LMWR-424、LMWR-425、LMWR-426、LMWR-427、LMWR-428、LMWR-429、LMWR-430、LMWR-431、LMWR-432、LMWR-433 |
| 简短描述 | 收口 Zotero / EndNote / Obsidian 只读 connector 设计、最小代码骨架、focused tests 与 compileall。 |
| Wave | Wave 13 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T20:28:00+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-201749-llmwiki-wave13-connectors-resume` |

恢复只允许在用户明确要求“回滚/恢复/撤销本次改动”后执行。

---

## 2. 成熟方案 / 参考目录

| 来源 | 参考点 | 本轮借鉴 |
| ---- | ------ | -------- |
| `github/Knowledge-Base-Gateway-1.2.2026.10009/README.md` | Obsidian / Zotero / EndNote 本地知识库路径、只读安装边界、deep/default 模式分层 | 只读 connector，不修改用户 Zotero/EndNote/Obsidian，不提前读真实数据库。 |
| `C:\Users\xiao\Downloads\llmwiki借鉴库\keppi-master\keppi\parser\markdown.py` | Markdown vault 扫描、frontmatter/heading/title、排除 `.obsidian` / `.git` / templates / `.excalidraw.md` | MarkdownConnector 使用相对路径 metadata，排除私有/模板目录，避免把 vault 根路径写进 public report。 |
| `C:\Users\xiao\Downloads\llmwiki借鉴库\keppi-master\keppi\parser\config.py` | vault path、extensions、exclude_dirs、exclude_patterns 的配置模型 | 将 exclude defaults 放在 connector 初始化参数，后续可接 env/config。 |
| Python pathlib 官方文档 | `Path.resolve()` / `relative_to()` 的路径归一化语义 | `ensure_path_within_allowed_roots()` 与 `path_to_safe_relative_string()` 先 resolve 再做边界判断。 |
| LlamaIndex / LangChain directory-loader 思路 | 目录 loader 输出文档内容与 metadata，按扩展名扫描 | 当前保持轻量，不引新依赖，只实现 list/read/metadata/dry-run contract。 |

---

## 3. 核心代码落点

| 文件 | 任务覆盖 |
| ---- | -------- |
| `literature_assistant/core/wiki/connectors/base.py` | LMWR-419、LMWR-425、LMWR-426、LMWR-427、LMWR-428：ReadOnlyConnector protocol、ConnectorSource、ConnectorScanReport、ConnectorSpec、ConnectorFieldSpec、路径白名单、source_id namespace、dry-run no-write report、错误脱敏。 |
| `literature_assistant/core/wiki/connectors/markdown.py` | LMWR-421：Obsidian-like Markdown 只读扫描、读取、metadata、hidden/private/template 排除、slug collision 后缀。 |
| `literature_assistant/core/wiki/connectors/pdf_folder.py` | LMWR-422：PDF 文件夹 skeleton，只列相对路径/size/title metadata，明确拒绝 PDF text extraction。 |
| `literature_assistant/core/wiki/connectors/zotero.py` | LMWR-423：Zotero spec-only readable fields，不读 `zotero.sqlite`。 |
| `literature_assistant/core/wiki/connectors/endnote.py` | LMWR-424：EndNote spec-only readable fields，不读 `.enl` / `.Data`。 |
| `literature_assistant/core/wiki/connectors/__init__.py` | connector public exports。 |
| `tests/wiki/test_connectors.py` | LMWR-429、LMWR-430、LMWR-431、LMWR-432、LMWR-433：focused connector tests。 |

---

## 4. 实现事实

- 已修复 `test_pdf_folder_connector_lists_metadata_without_content_extraction` 中 `with pytest.raises(...)` 块缩进问题。
- Markdown connector 现在会跳过 `.obsidian`、`.git`、`.trash`、`templates` 与 `*.excalidraw.md`。
- Connector scan report 仍为 dry-run，只返回 counts/source_ids/warnings，不写 registry、page store 或外部知识库。
- Source ID 使用 namespace 前缀；同 namespace slug collision 时只追加短 hash 后缀。
- Error sanitization 对 OSError/Permission/FileNotFound/UnicodeDecodeError 不暴露本地完整路径。
- Zotero / EndNote 当前只是 spec-only contract：字段结构可被后续实现引用，但不会读取真实库。

---

## 5. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_connectors.py" -q
& .\.venv-1\Scripts\python.exe -m compileall -q "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\literature_assistant\core\wiki\connectors" "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_connectors.py"
```

| 检查项 | 结果 |
| ------ | ---- |
| connector focused pytest | PASS（10 tests） |
| connector compileall | PASS |

---

## 6. Open / 后续

- Wave 13 暂不实现真实 Zotero SQLite / EndNote database parser；需要下一轮先写导入 dry-run contract 和隐私提示。
- Markdown connector 还未解析 frontmatter、wikilinks、tags；可在 Wave 15 或后续增强时借鉴 keppi parser。
- PDF connector 当前不抽全文；后续如启用 parser，需要单独评估 PyMuPDF / pypdf / OCR 依赖、错误脱敏和成本边界。

---

## 7. 下一步命令模板

```powershell
# 1. 回档
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "llmwiki-wave14-eval-gates"

# 2. 搜索/读取成熟方案
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\AI_WORKSPACE_GUIDE.md" -TotalCount 260
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\docs\plans\active\2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md" -Tail 220
# 如涉及 eval 设计，再搜索/读取 LightRAG evaluation、paper-qa eval、现有 workspace_tests/evaluation_scripts。

# 3. 实现
# 只改 Wave 14 评测/质量门禁相关文件，不碰 github/ 和下载参考库。

# 4. 验证
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py workspace_tests\evaluation_scripts
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q

# 5. 回滚，仅用户明确要求时
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```
