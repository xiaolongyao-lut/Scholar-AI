# LLM-Wiki 集成切片 Runbook 模板

> LMWR-224 · Wave 0 治理产物

本模板适用于每个 LLM-Wiki 集成代码切片的执行记录。每次新切片执行时，
在 `docs/plans/runbooks/` 下按 `llmwiki-slice-LMWR-NNN-<short-slug>.md` 命名复制并填写。

---

## 切片标识

| 字段 | 值 |
|------|----|
| 任务 ID | LMWR-NNN |
| 简短描述 | （一句话） |
| Wave | Wave N |
| 执行者 | Copilot/Claude/Human |
| 开始时间 | YYYY-MM-DDTHH:MM:SSZ |

---

## 1. 回档点

> **每个非平凡代码切片开始前必须创建。**

```powershell
# 在 repo 根目录执行
git stash push -m "pre-LMWR-NNN-rollback" --include-untracked
# 或
git diff HEAD > docs/plans/runbooks/.rollback-LMWR-NNN.patch
```

| 字段 | 值 |
|------|----|
| 回档命令 | （粘贴） |
| 恢复命令 | `git stash pop` 或 `git apply docs/plans/runbooks/.rollback-LMWR-NNN.patch` |
| 快照文件/stash ref | （填写） |

---

## 2. 成熟方案研究

> **每个架构/数据/接口/评测/治理切片开始前必须搜索成熟方案或读取本地参考项目。**

| 参考来源 | 路径 | 关键借鉴点 |
|----------|------|-----------|
| （示例）llm-wiki-compiler | `C:\Users\xiao\Downloads\llmwiki借鉴库\llm-wiki-compiler-main\src\` | two-phase compile, hash skip |
| （示例）本项目上游 | `literature_assistant/core/evidence_packer.py` | EvidenceReference.chunk_id 格式 |

---

## 3. 实现记录

### 新增文件

| 文件 | 目的 |
|------|------|
| （填写） | （填写） |

### 修改文件

| 文件 | 改动摘要 |
|------|----------|
| （填写） | （填写） |

---

## 4. 验证

```powershell
# focused tests
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q

# compileall
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant tests\wiki

# contract smoke（如适用）
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_<this_slice>.py -q
```

| 检查项 | 结果 |
|--------|------|
| compileall | PASS / FAIL |
| focused pytest | PASS / FAIL |
| 全量 pytest（可选） | PASS / FAIL |

---

## 5. 证据包

### Facts
- （已完成的可验证工作）

### Decision
- （本切片自决策的关键选择）

### Evidence
- （产物路径 + 验证输出）

### Rollback
- （如需回滚执行的命令）

### Open
- （遗留问题、后续切片依赖）

### Next
- LMWR-NNN+1：（下一个任务）

---

## 执行硬规则（copy from plan）

- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码。
- 产品代码优先放入 `literature_assistant/core/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链，不默认启用 rerank，不改变 corpus/goldset/qrels。
- 对外部资料源 Zotero/EndNote/Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference。
