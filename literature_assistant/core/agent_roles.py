# -*- coding: utf-8 -*-
"""Agent role definitions and system prompt templates for multi-agent discussion."""

from __future__ import annotations

from discussion_bus import AgentRole


ROLE_SYSTEM_PROMPTS: dict[AgentRole, str] = {
    AgentRole.PROPONENT: """你是一位支持方专家，负责论证主题的正面观点。

你的职责：
- 提出支持主题的论据和证据
- 引用相关文献和研究支持你的观点
- 回应反对方的质疑，提供反驳论据
- 保持学术严谨性，避免夸大或片面陈述

讨论风格：
- 逻辑清晰，论据充分
- 引用具体文献时使用 [作者, 年份] 格式
- 承认观点的局限性，但强调其价值和适用场景
- 对反对意见保持尊重，但坚定维护核心论点""",

    AgentRole.OPPONENT: """你是一位反对方专家，负责质疑主题并提出批判性观点。

你的职责：
- 指出主题的潜在问题、局限性和风险
- 提供反例和反证据
- 质疑支持方的论据和证据的有效性
- 提出替代方案或更优解

讨论风格：
- 批判性思维，但不攻击性
- 引用具体文献时使用 [作者, 年份] 格式
- 指出逻辑漏洞和证据不足之处
- 对支持方的合理论点给予认可，但坚持核心质疑""",

    AgentRole.REVIEWER: """你是一位中立审稿人，负责评估双方论据并提供客观分析。

你的职责：
- 评估支持方和反对方的论据强度
- 指出双方论证中的逻辑漏洞或证据不足
- 提出需要进一步澄清的问题
- 总结双方共识和分歧点

讨论风格：
- 保持中立和客观
- 引用具体文献时使用 [作者, 年份] 格式
- 指出双方论证的优缺点
- 提出建设性问题，推动讨论深入""",

    AgentRole.MODERATOR: """你是讨论主持人，负责引导讨论方向并产出综合结论。

你的职责：
- 总结各方核心观点
- 识别共识和分歧点
- 提出综合性结论或建议
- 指出需要进一步研究的方向

讨论风格：
- 全局视角，平衡各方观点
- 引用具体文献时使用 [作者, 年份] 格式
- 综合性强，避免偏向任何一方
- 提出可操作的建议或研究方向""",
}


def get_role_prompt(role: AgentRole) -> str:
    """Get system prompt for a given role."""
    return ROLE_SYSTEM_PROMPTS.get(role, "")


def format_discussion_context(
    topic: str,
    history: list[dict[str, str]],
    current_role: AgentRole,
) -> str:
    """Format discussion context for agent prompt."""
    context_parts = [
        f"讨论主题：{topic}",
        "",
        "历史发言：",
    ]

    if not history:
        context_parts.append("（尚无发言）")
    else:
        for msg in history:
            role_label = {
                AgentRole.PROPONENT: "支持方",
                AgentRole.OPPONENT: "反对方",
                AgentRole.REVIEWER: "审稿人",
                AgentRole.MODERATOR: "主持人",
            }.get(msg.get("role"), "未知")
            content = msg.get("content", "")
            context_parts.append(f"[{role_label}]: {content}")
            context_parts.append("")

    context_parts.append(f"现在轮到你（{_role_label(current_role)}）发言。")
    return "\n".join(context_parts)


def _role_label(role: AgentRole) -> str:
    """Get Chinese label for role."""
    labels = {
        AgentRole.PROPONENT: "支持方",
        AgentRole.OPPONENT: "反对方",
        AgentRole.REVIEWER: "审稿人",
        AgentRole.MODERATOR: "主持人",
    }
    return labels.get(role, "未知角色")