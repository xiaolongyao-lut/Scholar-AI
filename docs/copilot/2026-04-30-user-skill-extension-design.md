# 2026-04-30 用户自定义 Skill 扩展层设计

## Facts

- 当前项目已经存在 `skills/` 子系统：`SkillDescriptor`、`SkillRegistry`、`WritingSkillService`、`ApprovalStore`、`AuditLog` 和 `SKILL.md.template`。
- 已接入 RAG 文献助手的 AI/RAG/写作能力应作为基础功能或 builtin/base capability，不作为普通用户可删除的 Skill。
- 用户自定义 Skill 应复用现有 registry/service/approval/audit/runtime，不另起第二套插件系统。
- Claude 当前在处理 API/provider connectivity，本设计不触碰 `.env`、provider key、model routing 和连通性脚本。
- 本轮已建立计划文件回档点：`.rollback_snapshots/2026-04-27-full-project-build-master-plan.skill-interface.20260430-185134.md.bak`。

## Mature Patterns

- Dify plugin：workspace scoped install、manifest metadata、permission declaration、privacy policy、tool/provider/extension 等类型分层。
- MCP：tools 使用明确 input schema，resources 和 prompts 与 tools 分离，roots 限定文件系统边界，sampling 保持 human-in-loop。
- LangChain tools：tool name/description/schema/runtime context 明确分离，输入输出可验证。
- VS Code extension：manifest 负责 metadata/contributes/activation，运行时激活与 UI 注册解耦。

## Decision

用户 Skill 采用 manifest-driven package 形态，MVP 只支持 prompt-only 和 workflow 两类可执行 Skill；tool-wrapper 先做 schema 和 UI 展示，scripted Skill 默认导入但 blocked。

基础能力区与用户扩展区必须分开：

- 基础能力：RAG 检索、证据压缩、引用审计、写作导出、会话恢复等 builtin/base capability。
- 用户扩展：用户创建或导入的 prompt/workflow/tool/script package。

## Package Contract

最小包结构：

```text
my-skill/
  SKILL.md
  prompts/
  references/
  assets/
  schemas/
  scripts/
```

`SKILL.md` frontmatter 必填字段：

```yaml
id: user.academic.polish
name: Academic Polish
version: 1.0.0
kind: transform
description: Rewrite selected text into academic Chinese.
entry_mode: manual
ui_visibility: skill_assisted
supported_scopes:
  - selection
  - section
input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
permissions:
  draft.read: true
  draft.write: false
  retrieval.read: false
  files.read: false
  files.write: false
  network: false
  script.execute: false
root_policy:
  allowed_roots:
    - skill_root
script_policy:
  has_scripts: false
  safe_to_execute: false
model_policy:
  allow_llm: true
  allow_embedding: false
privacy_notes: Does not access external files or network.
rollback_hint: Disable this skill from Skill Manager.
```

Validation rules:

- `id` 必须稳定、命名空间化、只允许 ASCII lowercase、数字、点、短横线和下划线。
- `version` 必须是 SemVer。
- 所有引用路径必须是相对路径，并解析后仍位于 Skill 根目录。
- 包大小、单文件大小、文件数量必须有限制。
- `scripts/` 存在时不代表可执行，必须由 `script_policy` 和审批状态共同决定。
- 权限默认 deny，manifest 未声明的权限视为 false。

## Permission Model

权限分组：

- `model.llm`
- `model.embedding`
- `retrieval.read`
- `draft.read`
- `draft.write`
- `references.read`
- `files.read`
- `files.write`
- `network`
- `script.execute`
- `storage`

默认策略：

- builtin/base capability 可按现有规则 auto allowed。
- user/imported prompt-only skill 默认 guidance-only 或 disabled，用户启用后可运行。
- user/imported workflow skill 需要逐项展示其编排的 builtin/base capability。
- script.execute、network、files.write 默认 blocked。
- 高风险权限必须出现审批记录，且写入 audit log。

## Runtime Model

执行输入：

- `skill_id`
- `scope`
- `input_text`
- `draft_context`
- `evidence_refs`
- `parameters`
- `session_id`

执行输出：

- `job_id`
- `skill_id`
- `status`
- `output_text`
- `structured_output`
- `evidence_refs`
- `warnings`
- `audit_id`
- `execution_time_ms`

运行约束：

- prompt-only Skill 只填充受控 prompt template，不直接访问文件、网络或 secrets。
- workflow Skill 只能编排已授权 builtin/base capability。
- tool-wrapper 必须先声明 JSON Schema，执行入口另行审批。
- scripted Skill MVP 不执行，只展示 blocked 状态和禁用原因。

## Backend Tasks

- `TASK-184`：定义 manifest/schema validator。
- `TASK-185`：实现导入到 managed root，并记录 hash/origin/installed_at。
- `TASK-186`：持久化 enabled/trust/approval/audit 状态。
- `TASK-187`：实现 prompt-only/workflow runtime，scripted 保持 blocked。
- `TASK-188`：固化 Skill 管理 API 和 OpenAPI schema。

## Frontend Tasks

- `TASK-189`：在 Settings 或独立 Skill Center 实现 Skill Manager。
- `TASK-190`：接入 Workbench/DraftStudio 的手动触发入口。
- `TASK-191`：补 E2E、文档与 gate review。

UI 必须展示：

- 基础功能与用户 Skill 分区。
- 来源、版本、权限、信任级别、脚本状态。
- 启用/禁用/测试运行/审计入口。
- 危险权限 badge 和二次确认。

## Threat Model

主要风险：

- path traversal 读取项目外文件。
- Skill 包尝试读取 `.env` 或密钥。
- 脚本执行任意命令。
- 外部网络泄露论文内容或草稿。
- 用户 Skill 静默覆盖默认检索链、评测口径或回答提示词。
- prompt injection 通过 references 或 assets 改变系统约束。

防护：

- managed root + 路径 canonicalize。
- 权限默认 deny。
- scripts 默认 blocked。
- network 默认 blocked。
- import/run/enable/disable 全量 audit。
- 基础能力不可被用户删除。
- 用户 Skill 回填正文前必须 preview/diff。

## Rollback

- 计划文件可从 `.rollback_snapshots/2026-04-27-full-project-build-master-plan.skill-interface.20260430-185134.md.bak` 恢复。
- 用户 Skill 包导入前后都应生成 hash 和备份。
- 启用状态可以通过 Skill Manager 或后端管理 API 禁用。
- MVP 实现应提供全局 feature flag，例如 `USER_SKILLS_ENABLED=false`。

## Open

- 用户 Skill managed root 最终放在项目级 `.scholarai/skills/user/`、应用级 `skills/user/`，还是 profile 目录，需要实现前确认。
- 是否允许 zip 导入在 MVP 开启，还是第一版只允许目录导入。
- 是否需要 per-project Skill enablement，避免一个项目的 Skill 影响另一个项目。

## Next

1. 实施 `TASK-184` 前再次建立代码回档点。
2. 先写 manifest validator tests，再改 `skills/models.py` 或新增 `skills/user_manifest.py`。
3. 暂不实现脚本执行，只保留 blocked 状态和审批文案。
