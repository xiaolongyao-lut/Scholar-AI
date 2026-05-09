# Team Roster

> 多模态 RAG 文献助手 — 架构/编码/测试/数据/前端协作的多 Agent 小队 (canonical source: `team.md`)

## Coordinator

| Name | Role | Notes |
|------|------|-------|
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. Does not generate domain artifacts. |

## Members

| Name | Role | Charter | Status |
|------|------|---------|--------|
| Morpheus | Architect / QA Lead | `.squad/agents/morpheus/charter.md` | ✅ Active |
| Trinity | Implementation | `.squad/agents/trinity/charter.md` | ✅ Active |
| Switch | Frontend Design | `.squad/agents/switch/charter.md` | ✅ Active |
| Dozer | Frontend Implementation | `.squad/agents/dozer/charter.md` | ✅ Active |
| Tank | QA | `.squad/agents/tank/charter.md` | ✅ Active |
| Oracle | Data Engineer | `.squad/agents/oracle/charter.md` | ✅ Active |
| Scribe | Session Logger | `.squad/agents/scribe/charter.md` | 📋 Silent |
| Ralph | Work Monitor | — | 🔄 Monitor |

> Canonical identity source: `team.md`. If this table drifts from `team.md`, `team.md` wins; run the audit skill to reconcile.

## Coding Agent

<!-- copilot-auto-assign: false -->

| Name | Role | Charter | Status |
|------|------|---------|--------|
| @copilot | Coding Agent | — | 🤖 Coding Agent |

### Capabilities

**🟢 Good fit — auto-route when enabled:**
- Bug fixes with clear reproduction steps
- Test coverage (adding missing tests, fixing flaky tests)
- Lint/format fixes and code style cleanup
- Dependency updates and version bumps
- Small isolated features with clear specs
- Boilerplate/scaffolding generation
- Documentation fixes and README updates

**🟡 Needs review — route to @copilot but flag for squad member PR review:**
- Medium features with clear specs and acceptance criteria
- Refactoring with existing test coverage
- API endpoint additions following established patterns
- Migration scripts with well-defined schemas

**🔴 Not suitable — route to squad member instead:**
- Architecture decisions and system design
- Multi-system integration requiring coordination
- Ambiguous requirements needing clarification
- Security-critical changes (auth, encryption, access control)
- Performance-critical paths requiring benchmarking
- Changes requiring cross-team discussion

## Project Context

- **Owner:** xiao (小龙 姚)
- **Stack:** Python (RAG runtime), Node/React (frontend), Zotero integration, SiliconFlow + DashScope LLM providers
- **Description:** 多模态 RAG 文献助手 — 当前聚焦文献提取、关键词相关性遍历与智能对话，后续扩展写作助手
- **Created:** 2026-04-20
