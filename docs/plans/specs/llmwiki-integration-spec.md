# LLM-Wiki 集成规范文档

> LMWR-228 ~ LMWR-237 · Wave 0 治理产物

## LMWR-228：Feature Flag 命名

所有 wiki 集成新能力默认**关闭**，通过以下环境变量启用：

| 环境变量 | 默认值 | 启用值 | 说明 |
| --- | --- | --- | --- |
| `LITERATURE_ASSISTANT_WIKI_ENABLED` | `0` | `1` / `true` / `yes` / `on` | 启用 wiki 集成总开关 |
| `LITERATURE_ASSISTANT_WIKI_FIRST_RETRIEVAL` | `0` | `1` | 检索时优先查询 wiki（default-off） |
| `LITERATURE_ASSISTANT_WIKI_COMPILE_ENABLED` | `0` | `1` | 允许 LLM 驱动的编译（default-off） |
| `LITERATURE_ASSISTANT_WIKI_AUTOFINALIZE` | `0` | `1` | 允许自动从 review → final（default-off） |
| `LITERATURE_ASSISTANT_WIKI_GRAPH_ENABLED` | `0` | `1` | 启用 graph 影响分析（default-off） |

读取函数统一在 `literature_assistant/core/runtime_env.py` 新增。

## LMWR-229：Wiki 输出路径策略

所有 wiki 产物必须通过 `project_paths.py` 路径 helper 定位，不直接硬编码绝对路径。

| 路径 Helper | 实际路径 | 用途 |
| --- | --- | --- |
| `wiki_runtime_db_path()` | `workspace_artifacts/runtime_state/wiki/wiki.db` | SQLite 注册表 |
| `wiki_graph_path()` | `workspace_artifacts/runtime_state/wiki/graph.json` | 图谱存储 |
| `wiki_manifest_path()` | `workspace_artifacts/runtime_state/wiki/retrieval_manifest.json` | 检索清单 |
| `wiki_review_queue_path()` | `workspace_artifacts/runtime_state/wiki/review_queue.jsonl` | 审核队列 |
| `wiki_generated_root()` | `workspace_artifacts/generated/wiki/` | wiki 页面根目录 |
| `wiki_page_path(kind, slug)` | `workspace_artifacts/generated/wiki/<kind>/<slug>.md` | 单个页面路径 |

**约束**：
- wiki 产物不写回根目录 `output/`。
- `workspace_artifacts/` 下的内容不提交到 git（已在 `.gitignore`）。

## LMWR-230：只读外部参考库规则

| 规则 | 说明 |
| --- | --- |
| `github/` 只读 | 该目录下所有参考库不得修改，不得向 git 提交任何改动 |
| `llmwiki借鉴库` 只读 | `C:\Users\xiao\Downloads\llmwiki借鉴库` 下所有项目只作参考，不复制代码 |
| 思路借鉴后必须重实现 | 按本项目 import/path/test 约束从头写，不粘贴参考代码 |
| 参考文件路径必须标注 | 每次借鉴必须在切片 runbook 中记录参考文件路径和具体借鉴点 |

## LMWR-231：任务完成证据包格式

每个切片完成时，证据包必须包含以下六节，可写入 runbook 或 `.squad/decisions/inbox/`：

```markdown
### Facts
- 可验证的已完成工作，每项需有文件路径或命令输出作为锚点

### Decision
- 本切片自决策的关键选择及理由

### Evidence
- 产物路径 + 验证输出（pytest pass / compileall OK / API response）

### Rollback
- 如需回滚执行的精确命令

### Open
- 遗留问题、后续切片依赖、待确认事项

### Next
- LMWR-NNN：下一个任务的精确入口
```

## LMWR-232：Wiki 页面状态枚举

| 状态 | 语义 | 自动进入 | 需人工确认 |
| --- | --- | --- | --- |
| `draft` | 草稿，由编译器或 query-save 创建 | ✓ | |
| `review` | 待审核，触发 immutability 变更或 citation 警告 | ✓ | |
| `final` | 已确认，citation density ≥ 0.95，evidence_refs 非空 | | ✓ |
| `deprecated` | 已被更新版本取代 | | ✓ |
| `archived` | 归档，不再参与检索 | | ✓ |

非法转换（如 `archived → draft`）在代码层 fail-fast。

## LMWR-233：Claim 审计分级

| 级别 | 机器标签 | 语义 |
| --- | --- | --- |
| 通过 | `passed` | claim 有有效 citation，chunk 存在，quote 可验证 |
| 警告 | `warning` | citation 格式存在但 chunk 未注册，或 quote 不完全匹配 |
| 失败 | `failed` | claim 完全无 citation，或 citation density < 0.95（final 模式） |
| 草稿限定 | `draft_only` | 无 citation 但页面状态为 draft，暂不阻塞 |

规则：`failed` 在 final 模式下阻塞 finalize；`draft_only` 不阻塞 draft/review 写入。

## LMWR-234：LLM-Wiki 集成风险登记表

| 风险 | 缓解措施 |
| --- | --- |
| Hallucination | 所有 claim 必须有 evidence_refs；final 模式需 citation density ≥ 0.95 |
| Stale source | source_hash 变化进入 review 而非静默覆盖 |
| 重复 wiki 页 | stable_slug + chunk_id 保证幂等；WikiLoom duplicates 策略参考 |
| 许可证问题 | 借鉴库仅读取思路，不复制代码；引用文献不落入 wiki final |
| LLM 成本超支 | 编译器第一版 deterministic stub，LLM 调用必须等 validator/review 就位后再开 |
| 隐私泄露 | `chunk_id`/`material_id` 不含用户 PII；wiki 日志不含用户凭证 |
| 破坏现有 RAG 链 | wiki-first retrieval default-off；feature flag 未开启时 wiki 代码路径不执行 |

## LMWR-235：LLM-Wiki Task Dependency Graph

```
Wave 0（治理）─► Wave 1（数据模型）─► Wave 2（registry）─► Wave 3（page store）
                                                  │
                                                  ├─► Wave 4（citation validator）
                                                  │
                                                  └─► Wave 5（evidence adapter）
                                                            │
                                                            └─► Wave 6（compiler dry-run）
                                                                        │
                                                            Wave 7（LLM 接入，需等 Wave 4+6）
                                                                        │
                                                            Wave 8（wiki-first retrieval，需等 Wave 6）
                                                                        │
                                                  Wave 9（graph/doctor）─┤
                                                                        │
                                              Wave 10（doctor/review queue）
                                                                        │
                                              Wave 11（API router，需等 Wave 3+4+6）
                                                                        │
                                              Wave 12（前端，需等 Wave 11）
```

阻塞依赖（必须等前置 Wave 验证通过）：
- Wave 7 阻塞于：Wave 4 citation validator + Wave 6 compiler schema
- Wave 8 阻塞于：Wave 6 compiler（有可搜索 wiki 页面）
- Wave 11 阻塞于：Wave 3 page_store atomic write
- Wave 12 阻塞于：Wave 11 API router

## LMWR-236：Copilot/Agent 执行提示模板

每次启动新的 LLM-Wiki 切片任务，执行者（Copilot/Agent）应在开头确认以下项目：

```markdown
切片 ID：LMWR-NNN
1. 已创建回档点：[是 / 命令：xxx]
2. 已读成熟方案：[是 / 参考文件：xxx / 关键借鉴点：xxx]
3. 本切片改动范围：[仅新增文件 / 修改现有文件 xxx]
4. 验证计划：[pytest 命令 + compileall 命令]
5. 不改变内容：现有 RAG 主链 / corpus / goldset / qrels / 默认 runtime
```

## LMWR-237：Wiki Integration Stop Conditions

以下情况必须停下确认，不可自决策继续：

| 情形 | 原因 |
| --- | --- |
| 修改现有评测口径（qrels/goldset/eval queries） | 影响可复现评测基线 |
| 写回外部系统（Zotero/EndNote/Obsidian） | 破坏用户数据 |
| 修改 RAG 默认链（hybrid_search_runtime、tolf_text_selector 等为默认路径） | 回归影响面大 |
| 删除 `workspace_artifacts/` 下的 embedding cache 或 vector store | 不可逆 |
| 自动 finalize 任何 wiki 页面（状态 draft → final） | 需 citation 人工确认 |
| 修改 `.env` 或 secrets | 硬边界 |
| 引入外部 LLM 调用成本 > 5 USD/run | 需预算授权 |
