# Squad Team

> 通用 AI 工程项目：以架构、编码、测试、数据生产为核心的多模型协作小队

## Coordinator

- **Name:** Squad
- **Role:** Coordinator
- **Notes:** Routes work, enforces handoffs/reviewer gates, runs 5-second patrol, requires 25-second unified heartbeat on long-running tasks, uses Coordinator-led active heartbeat polling (pull) with ordered summary output, supports quiet-window downshift (60s summaries after 3 unchanged windows), keeps generic `peek` default-off for single-owner runs, and uses `co-work` interface + `nudge` by heartbeat thresholds.
- **Authority boundary:** Coordinator manages execution flow; Morpheus owns architecture judgment and hard-stop approvals.
- **Operating model:** 7 member agents + 1 Coordinator (`7+1`). Coordinator does not count as a member worker.
- **Conflict rule:** supervision for the same target run is serialized (single supervision token), never concurrent.

## Members

| Name     | Role                    | Charter                             | Status  |
| -------- | ----------------------- | ----------------------------------- | ------- |
| Morpheus | Architect / QA Lead     | `.squad/agents/morpheus/charter.md` | Active  |
| Trinity  | Implementation          | `.squad/agents/trinity/charter.md`  | Active  |
| Switch   | Frontend Design         | `.squad/agents/switch/charter.md`   | Active  |
| Tank     | QA                      | `.squad/agents/tank/charter.md`     | Active  |
| Oracle   | Data Engineer           | `.squad/agents/oracle/charter.md`   | Active  |
| Scribe   | Session Logger          | `.squad/agents/scribe/charter.md`   | Silent  |
| Ralph    | Work Monitor            | —                                   | Monitor |

## Project Context

- **Owner:** xiao
- **Stack:** 多模态 RAG / 文献处理 / 智能对话，前后端协同推进
- **Description:** 多模态 RAG 文献助手项目，当前只聚焦文献提取、关键词相关性遍历与智能对话，为后续写作助手奠定基础
- **Created:** 2026-04-20

## Owner Decision Profile (Autopilot)

- **Primary profile source:** `my-project/.copilot/skills/user-profile/SKILL.md`
- **Evidence profile source:** `..\用户画像_AI协作工程画像.md` (workspace sibling)
- **Execution intent:** 在 `autopilot` 档位下，Morpheus 的审批与执行默认以 Owner 画像优先（求真、可回滚、门禁可验、blast radius 可控）。
- **Approval default:** 非红线事项满足 `surgical + rollback + DoD + controlled blast radius` 时，默认 `DO NOW`，不等待额外人工确认。
