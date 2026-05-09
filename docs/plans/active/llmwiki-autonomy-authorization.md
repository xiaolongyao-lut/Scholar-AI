# LLM-Wiki 自决策授权补充

> 生效时间：2026-05-04
> 适用范围：`Modular-Pipeline-Script` 的 LLM-Wiki + RAG 文献助手长跑任务。

## 授权原则

- 计划内 LMWR 任务继续自决策执行，不因小权限问题频繁请示。
- 每个非平凡任务仍必须先创建回档 checkpoint，再搜索成熟方案或官方方案，然后实现、验证、回填记录。
- 不得自动恢复 checkpoint。只有用户明确要求“回滚、恢复、撤销”时才执行 restore。
- 可删除或修改项目内文件、评测数据、派生产物或旧实现，但必须先有可验证备份；备份路径、影响范围和验证结果要写入 runbook 或决策记录。
- 使用现有 env / provider 配置运行评测或 canary control 不属于停下条件；执行时必须避免打印密钥、避免修改 `.env`，并记录 no-secret 输出。
- 外部系统、账号、凭据、远程历史和真实外部知识库数据的操作必须先做目标级备份或 dry-run。无法备份、无法验证或涉及账号不可逆风险时停下请示。

## 产品界面与前端测试

- 最终程序界面定位为独立窗口应用；当前浏览器页面只作为开发期预览、smoke test 和最小 E2E 验收工具。
- 浏览器 UI 适配只做测试期最小可用，不为测试以外目标投入大量 token 做完整响应式/视觉优化。
- LMWR-466 使用现有 Playwright E2E 框架优先，不引入 Cypress；如果缺少 Playwright browser runtime，可按官方 Playwright browser 安装流程补齐。
- E2E 目标是覆盖关键工作流是否能打开、显示、触发 dry-run 和错误态，不把浏览器页面当最终交付形态。

## 查询集与评测基线

- 默认优先新增查询集、版本化查询集和对照实验，而不是直接覆盖旧 qrels/goldset/canary30。
- 若新增查询集或对照实验显示新配置明显更好，允许在备份后自决策修改旧查询集、qrels、goldset 或 canary30。
- 修改前必须：
  - 创建代码 checkpoint。
  - 复制原始评测文件到 `workspace_artifacts/backups/` 或带日期的评测备份目录。
  - 记录旧指标、新指标、样本数、查询集版本和恢复路径。
  - 保留 no-rerank/raw/default control，避免把单一路径误判为最终收益。
- 修改后必须运行 focused eval，并把结果写入 `docs/analysis/` 或对应 LMWR runbook。

## AI 联网与知识库回答边界

- 程序本体默认不需要联网，除接入 AI provider 之外不应主动访问网络。
- AI 可以联网搜索成熟方案、官方文档或外部知识来辅助开发和回答，但用户问答的最终依据必须优先来自本地知识库、RAG evidence、Wiki evidence_refs 和可追溯 citation。
- 网络搜索结果只能作为背景、补充解释或成熟方案参考，不能静默写成知识库证据，不能替代本地知识库引用。
- 如果回答中使用了网络信息而本地知识库没有证据，必须把它标记为外部背景或建议用户导入知识库后再作为正式依据。

## 安全审计授权

安全审计不是昂贵的外部扫描。本项目的 LMWR-472 定义为本地轻量工程门禁：

- 路径安全：防止 `../`、绝对路径、符号链接或用户输入越界读取/写入项目外文件。
- 输入校验：API、CLI、connector、page path、source_id、query 参数必须拒绝非法形状。
- 权限边界：只读 connector 不得写外部库，default-off 能力不得静默开启。
- 日志与错误：不得把 API key、私有路径、全文敏感片段写入日志、trace、doctor report 或前端错误态。
- RAG/LLM 边界：防止外部网页或恶意文档提示词绕过知识库证据链。

不做这类审计的后果：可能误读/误写项目外文件、泄露密钥或私有路径、把网络内容当知识库证据、被恶意文档诱导生成不基于证据的回答，或让只读 connector 变成隐式写回。

本审计参考 OWASP ASVS 的输入校验、访问控制、错误日志等控制面，以及 OWASP GenAI/LLM 安全项目对 prompt injection、敏感信息泄露、RAG 数据污染的风险分类。实现时只做本地测试、文档和小范围防守代码，不做外部攻击扫描。

## 删除、修改与备份

允许自决策执行的前提：

- 项目内文件删除、迁移、改名、清理 stale artifact：先 checkpoint，再复制目标到备份目录，验证备份可读。
- 评测文件修改：按“查询集与评测基线”执行。
- 外部知识库或用户资料目录修改：先生成 dry-run diff、目标级导出/备份、operation journal；没有这些证据时停下。
- Git 分支或远程历史类操作：先创建本地备份分支或 tag，记录当前 commit 和 remote ref；涉及 force push 或删除远程分支时，如果无法确认备份覆盖远程历史，停下。

仍需停下的情况：

- 备份无法创建、无法读取或无法证明覆盖目标数据。
- 需要新增或修改账号授权、密钥、`.env` secret，或需要生产环境访问。
- 操作会删除外部系统中无法从备份恢复的数据。
- 要把未经独立验收的评测结果宣布为最终发布门禁。

## 后续 agent 读档要求

任何继续 LLM-Wiki/RAG 长跑的 agent 必须先读：

- `AI_WORKSPACE_GUIDE.md`
- `docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md`
- `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`
- `docs/plans/active/llmwiki-autonomy-authorization.md`
- `docs/plans/runbooks/longrun-local-supervisor.md`

若这些文档冲突，以本授权补充和用户最新消息为准。
