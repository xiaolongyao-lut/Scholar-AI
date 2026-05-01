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
| Dozer    | Frontend Implementation | `.squad/agents/dozer/charter.md`    | Active  |
| Tank     | QA                      | `.squad/agents/tank/charter.md`     | Active  |
| Oracle   | Data Engineer           | `.squad/agents/oracle/charter.md`   | Active  |
| Scribe   | Session Logger          | `.squad/agents/scribe/charter.md`   | Silent  |
| Ralph    | Work Monitor            | —                                   | Monitor |

## Project Context

- **Owner:** xiao
- **Stack:** TOLF 目标架构 / 多模态文献处理 / 检索评测 / 智能对话 / 写作交付，前后端协同推进
- **Description:** 本地优先文献助手与科研写作管线。标准 RAG 是当前对照组和过渡参考系，TOLF 是长期目标；当前重点是文献接入、关键词相关性遍历、检索/重排门禁、智能对话与可读交付产物。
- **Created:** 2026-04-20

## Owner Decision Profile (Autopilot)

- **Primary profile source:** `C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md`
- **Squad adapter:** `.squad/identity/owner-profile-v4.md` (shim only; do not duplicate profile text)
- **Evidence profile source:** `C:\Users\xiao\Desktop\tools\用户画像_AI协作工程画像.md`
- **Operational reference:** `C:\Users\xiao\Desktop\tools\用户画像_AI编码参考_v2.md`
- **Superseded:** `C:\Users\xiao\Desktop\tools\用户画像_v3.md` remains archival only; v4 overrides it for Squad behavior.
- **Execution intent:** 在 `autopilot` 档位下，Morpheus 与 Coordinator 的审批与执行默认以 Owner v4 画像优先：求真、可回滚、门禁可验、blast radius 可控、完成证据明确。
- **Approval default:** 非红线事项满足 `surgical + rollback + DoD + controlled blast radius + evidence + cleanup` 时，默认 `DO NOW`，不等待额外人工确认。
- **Non-negotiable completion:** `主产物落盘 ∧ 状态同步 ∧ 门禁通过 ∧ 环境收尾`。
