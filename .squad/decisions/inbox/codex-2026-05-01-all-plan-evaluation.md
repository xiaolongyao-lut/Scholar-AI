# Codex All-Plan Evaluation — 2026-05-01

## Scope

本记录评估用户指定的 6 份方案/规格，并以当前仓库事实为准给出执行优先级：

- `.squad/decisions/inbox/copilot-plan-status-2026-05-01.md`
- `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md`
- `.kilo/plans/2026-04-27-full-project-build-master-plan.md`
- `.kilo/plans/2026-04-27-squad-official-capability-reuse.md`
- `docs/superpowers/specs/2026-04-30-wechat-codex-rag-design.md`
- `.kilo/plans/1776608354894-playful-meadow.md`

## Rollback

- 本轮评估写入前已建立回档点：`C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.rollback_snapshots\codex-all-plan-evaluation-20260501_011352`。
- 回档内容包含用户指定的 6 份计划/规格文件原始副本。
- 本轮只写记录与状态快照，不修改 `.env`、API key、provider routing、connectivity scripts、corpus/goldset、运行时代码。

## External Mature References

- VS Code / GitHub Copilot customization 官方文档确认：`copilot-instructions.md` 适合作为仓库级 always-on instructions；prompt files 适合重复任务；skills 适合多步骤工具包；hooks 适合生命周期确定性执行。参考：[VS Code Customization](https://code.visualstudio.com/docs/copilot/concepts/customization)、[Custom instructions](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)、[Agent Skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills)、[Hooks](https://code.visualstudio.com/docs/copilot/customization/hooks)。
- GitHub Copilot customization cheat sheet 同样把 custom instructions、prompt files、agent skills 分成不同用途，支持当前 Squad T5 的拆分方向。参考：[GitHub Copilot customization cheat sheet](https://docs.github.com/en/copilot/reference/customization-cheat-sheet)。
- Playwright 官方最佳实践要求测试隔离、user-visible locators、web-first assertions，并支持 `page.route()` / `browserContext.route()` 做 API mock；当前 E2E gate 的 deterministic mock 与 role/text locator 方向符合成熟实践。参考：[Playwright Best Practices](https://playwright.dev/docs/best-practices)、[Locators](https://playwright.dev/docs/locators)、[Network](https://playwright.dev/docs/network)、[Assertions](https://playwright.dev/docs/test-assertions)。
- OpenAI/Codex 相关公开资料强调 AGENTS.md / repo instructions 应作为清晰、可维护的工程上下文，不应把所有流程堆成不可诊断的单体说明；当前把 Squad 流程拆到 instructions / prompts / skills / hooks 的方向合理。参考：[OpenAI Codex AGENTS.md docs](https://github.com/openai/codex/blob/main/docs/agents_md.md)、[Harness engineering](https://openai.com/index/harness-engineering/)。

## Plan Verdicts

| Plan | Role | Current Verdict | Evidence | Open Items |
| --- | --- | --- | --- | --- |
| `2026-04-27-full-project-build-master-plan.md` | 当前主计划 | **Active / near-close**。Wave 0-10 主体完成，Wave 9/10 前端 E2E gate 已由 2026-05-01 证据收口；下一主线转向后端 hardening。 | Master plan 已记录 `npm run test` -> `34 passed`、`npm run build` -> success、`npm run test:e2e -- --reporter=line` -> `16 passed (50.7s)`；TASK-179/191/192 已标完成；TASK-193/194 已加入 Wave 10 后端 hardening。 | TASK-193 Skill approval decision 持久化；TASK-194 Skill 卸载/回滚 API；前端审批/卸载 UI 后续切片。 |
| `2026-04-27-squad-official-capability-reuse.md` | 治理/协作能力计划 | **Gate-passed / signed off**。Plan B 不再是当前阻塞项。 | T5 拆分已落：`.github/prompts/squad-plan.prompt.md`、`.github/skills/squad-startup-packet/SKILL.md`、`.github/skills/squad-cli-handoff/SKILL.md`；`prompts.md` 已下线为 `.deprecated`；用户签收记录见 `.squad/decisions/inbox/copilot-2026-05-01-phasea-user-signoff.md`。 | 仅保留宿主级 hooks 真实触发观察，不阻塞。 |
| `2026-04-21-cost-and-defaults.md` | 成本/默认值/缓存历史计划 | **Mostly implemented / audit tail**。不再作为主执行计划，只保留手动验收与阻塞审计项。 | Sampling、LLM cost logger/router、MMR、tokenizer、chunk guard、gateway、contextual precompute、evidence packing 多数已实装；计划内有明确通过测试和输出证据。 | §2.1.4 curl/manual 验收；§2.2.5 telemetry off/error path；§3.3 cache rebuild/rerun；§3.5.6 rerank_cost/manifest consistency；§3.6 full rerun 或 cache cleanup 演示；§3.8 answer-level `[chunk_id]` grep 因缺稳定 answer artifact path 阻塞。 |
| `1776608354894-playful-meadow.md` | 早期战略祖先计划 | **Superseded / historical**。其核心方向已被 master plan 吸收。 | 该计划要求先修评测可信度、reranker 实证、运行时收敛、再做 TOLF；master plan Wave 1/4/5/6 已分别覆盖这些方向。 | 不再直接派活；若涉及 TOLF/reranker，只从 master plan 或新专项切片启动。 |
| `2026-04-30-wechat-codex-rag-design.md` | 微信/OpenClaw 运维规格 | **Usable manual integration / validation pending**。不是主项目构建 blocker。 | 已记录 `/codex` 简单问答可用、cwd/权限/启动脚本、前台 gateway 启停方式、署名前缀和 fan-out 设计。 | `@所有人` fan-out 真实验证；`copilot进入squad` 自然语言路由验证；`/codex`/`/claude`/`/copilot` cwd/权限/署名复测；可选 `openclaw gateway install`；可选模型/推理参数固化。 |
| `copilot-plan-status-2026-05-01.md` | 状态快照 | **Needs correction**。Plan B 部分已准，Plan C/Master 部分仍停留在 TASK-192 未通过的旧判断。 | 该文件仍写 Wave 9/10 E2E 未收口、TASK-192 待执行；master plan 已在 2026-05-01 回填 16/16 E2E pass。 | 本轮同步修正为 near-close + backend hardening open items。 |

## Decisions

1. 以后项目推进以 `.kilo/plans/2026-04-27-full-project-build-master-plan.md` 为主计划；`copilot-plan-status-2026-05-01.md` 只作为快照，不得覆盖 master plan 的更新事实。
2. Squad governance plan 视为已签收，不再重复修 T5 prompt/skill 拆分；后续只在 hooks 宿主触发异常时开新诊断。
3. Cost/defaults plan 保持为 audit backlog；不运行付费 eval 或 cache rebuild，除非用户明确启动该专项。
4. Playful Meadow 归档为历史战略，不再直接按该文件派发新任务。
5. WeChat/OpenClaw RAG spec 属于运维集成验证计划；可以独立推进，但不得作为当前 master build 的阻塞项。
6. 当前安全下一步是 TASK-193：Skill approval decision 持久化。TASK-194 必须等 TASK-193 的模型/审计/契约测试稳定后再执行。

## Next Safe Actions

1. 执行 TASK-193：先写 approval persistence contract tests，再落 `skills/approval.py` / `models/skills.py` / `routers/skills_router.py` 最小实现。
2. TASK-193 完成后执行 TASK-194：仅 user skill 支持 uninstall/rollback，builtin skill 必须 403。
3. 若用户要继续微信控制面，先跑 `tools\openclaw\start-wechat-gateway.ps1 -DryRun`，再做 `/codex`、`/claude`、`/copilot`、`copilot进入squad`、`@所有人` 五段人工验证。
4. 若用户要继续成本计划，优先补 §3.8 answer artifact path，因为它能解除 `[chunk_id]` grep 验收阻塞，也能支撑后续 RAG 质量审计。

## Commit Scope Recommendation

- 建议本次只提交计划/状态记录文件，避免把当前 dirty worktree 中大量并行 agent 改动、浏览器 profile 删除、前后端实现改动混入同一提交。
- 推荐 stage 范围：`.squad/decisions/inbox/codex-2026-05-01-all-plan-evaluation.md` 与 `.squad/decisions/inbox/copilot-plan-status-2026-05-01.md`。
