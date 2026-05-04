# LLM-Wiki 文献助手使用指南草稿

> LMWR-460 · 面向用户/执行者的 wiki-first、query-save、review、doctor 操作说明

## 使用前置

Wiki 能力仍是 default-off。未显式开启前，默认 RAG/TOLF 主链不变。

每次执行代码或迁移前先做两件事：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "llmwiki-user-operation"
Start-Process "https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"
```

## 常用诊断

路径诊断：

```powershell
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
```

Wiki 状态：

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki status
```

Wiki doctor：

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki doctor
```

## Evidence Refs 迁移 Dry-Run

输入可以是 EvidenceReference JSONL，也可以是每行包含 `evidence_refs` 数组的 JSONL。

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki migration-dry-run --input workspace_artifacts\generated\some_evidence_refs.jsonl
```

输出关注字段：

- `would_write=false`：确认没有写 registry/page store。
- `candidate_count`：可导入候选数量。
- `already_registered_count`：当前 registry 中已存在的 chunk。
- `skipped[]`：重复、坏 JSON、缺少 chunk/material id 的行。

## Wiki 备份

只预览：

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-backup.zip
```

实际创建本地 zip：

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-backup.zip --write
```

备份范围：

- `workspace_artifacts/runtime_state/wiki/wiki.db`
- `retrieval_manifest.json`
- `graph.json`
- `graph.db`
- `wiki_query_index.db`
- `review_queue.jsonl`
- `workspace_artifacts/generated/wiki/**/*.md`

## Query-Save / Review / Doctor 工作流

当前建议的安全顺序：

1. 正常提问，保留 RAG `evidence_refs`。
2. 用 migration dry-run 检查 evidence refs 是否能映射到 wiki registry。
3. 用 compile dry-run 或 query-save draft 生成草稿。
4. 运行 doctor，查看 citation、graph、review、retrieval 状态。
5. 人工检查 draft/review 页面。
6. 只有人工确认后，才允许进入 final。

## 不要做的事

- 不写回 Zotero / EndNote / Obsidian。
- 不自动 finalize。
- 不修改 `.env` 或 secret。
- 不改 qrels/goldset/eval queries。
- 不把 wiki-first retrieval 改成默认。
- 不复制 `github/` 或 `C:\Users\xiao\Downloads\llmwiki借鉴库` 的代码。

## 恢复

只有用户明确要求回滚时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```
