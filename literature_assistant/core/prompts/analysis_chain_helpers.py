"""AnalysisChain prompt + carry-over helpers shared across pipelines.

Source of truth for the AnalysisChain 6-field schema:
``literature_assistant/core/inspiration_engine.py`` ``AnalysisChain``.

This module is the single rendering point for AnalysisChain prompts and
prior-step carry-over blocks, so RAG QA, Multi-agent Discussion, and any
future surface use one shared format. See
``docs/plans/specs/analysis-chain-cross-pipeline-spec.md`` Slice 0 for the
rationale (ACR-013) — the inspiration pipeline keeps its full sparks-list
templates intact; this module produces a leaner single-chain prompt block
that downstream pipelines can embed in their own task prompt without
inheriting the inspiration-specific JSON schema.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Mapping

ChainFrame = Literal["irac", "fincot"]


_FIELD_ORDER: tuple[str, ...] = (
    "observation",
    "mechanism",
    "evidence",
    "boundary",
    "counter_evidence",
    "next_action",
)


_IRAC_FIELD_MAP_ZH: dict[str, str] = {
    "observation": "Issue（研究问题）：1-2 句具体可观察的问题或反常现象，不要泛化",
    "mechanism": "Rule（规则/机制）：被引用或可能成立的机制、定律、因果路径",
    "evidence": "Application（证据如何适用）：1-3 条最小证据；每条 ≤200 字；不写空话",
    "boundary": "Application 的边界条件：样本/方法/时序/scope 限制",
    "counter_evidence": "Application 的对立证据：0-3 条；没有就空数组",
    "next_action": "Conclusion（可写结论）：下一步要写、验证或补检索的具体动作",
}


_FINCOT_FIELD_MAP_ZH: dict[str, str] = {
    "observation": "现象：1-2 句具体可观察的现象或经验事实",
    "mechanism": "driver → mediator → outcome 的因果路径；未识别部分要显式标记",
    "evidence": "结果指标：1-3 条最小证据片段；每条 ≤200 字；优先量化",
    "boundary": "机制失效的样本/时序/scope 边界或测量误差/共变量风险",
    "counter_evidence": "对立结果：0-3 条；没有就空数组",
    "next_action": "下一步验证：要写、要做的实验、要查的数据",
}


_HARD_CONSTRAINTS = (
    "仅输出 JSON 对象；禁止前导语、解释、Markdown 代码块。",
    "六个固定 key 全部输出：observation、mechanism、evidence、boundary、counter_evidence、next_action。",
    "evidence 与 counter_evidence 最多 3 条；每条 ≤200 字。",
    "未知内容填 \"\" 或 []；不得省略 key，不得伪造证据或编造文献。",
    "evidence 字符串只允许来自调用方注入的证据上下文；未注入证据时 evidence 必须为 [] 或写明 \"待验证\"。",
)


_SCHEMA_BLOCK = (
    "{{\n"
    '  "observation": "",\n'
    '  "mechanism": "",\n'
    '  "evidence": [],\n'
    '  "boundary": "",\n'
    '  "counter_evidence": [],\n'
    '  "next_action": ""\n'
    "}}"
)


def _field_map(frame: ChainFrame) -> Mapping[str, str]:
    if frame == "fincot":
        return _FINCOT_FIELD_MAP_ZH
    return _IRAC_FIELD_MAP_ZH


def render_analysis_chain_prompt_block(
    frame: ChainFrame,
    *,
    context_summary: str = "",
    evidence_present: bool = False,
) -> str:
    """Render a single-chain prompt block for downstream pipelines.

    Args:
        frame: ``irac`` for argument/boundary work, ``fincot`` for causal chains.
        context_summary: Short description (≤300 chars recommended) of what
            the downstream task is reasoning about — e.g. ``"用户问题: ...
            + 证据片段 N 条"``. Empty string is allowed.
        evidence_present: True when the caller has injected concrete evidence
            snippets into its own prompt; controls the evidence-fabrication
            guardrail wording.

    Returns:
        A prompt block (Chinese, no leading whitespace) that the caller
        appends to its own task prompt. Output is a plain string suitable
        for f-string or ``str.format``-free concatenation.
    """

    frame_name = "FinCoT (现象 → 驱动因素 → 中介机制 → 结果指标 → 风险/边界 → 下一步)" if frame == "fincot" else "IRAC (Issue → Rule → Application → Conclusion)"
    field_map = _field_map(frame)
    field_lines = "\n".join(
        f"- {key}：{desc}" for key, desc in zip(_FIELD_ORDER, (field_map[k] for k in _FIELD_ORDER))
    )
    constraint_lines = "\n".join(f"{i}) {c}" for i, c in enumerate(_HARD_CONSTRAINTS, 1))
    evidence_clause = (
        "本次任务已注入证据上下文；evidence 字段必须只引用其中片段，不得编造来源。"
        if evidence_present
        else "本次任务未注入可识别证据；evidence 字段必须为 [] 或仅写 \"待验证: <证据类型>\"。"
    )
    summary_clause = f"任务上下文：{context_summary}\n" if context_summary else ""

    return (
        f"请基于 {frame_name} 推理框架，针对下方任务给出一段结构化推理过程（AnalysisChain）。\n"
        f"{summary_clause}"
        f"六字段语义：\n{field_lines}\n\n"
        f"硬性约束：\n{constraint_lines}\n"
        f"证据约束：{evidence_clause}\n\n"
        f"输出 JSON Schema：\n{_SCHEMA_BLOCK}"
    )


def render_carryover_block(
    prior_chains: Iterable[Mapping[str, Any]],
    *,
    max_chains: int = 3,
    max_chars_per_chain: int = 600,
) -> str:
    """Format prior AnalysisChain dicts as a compact reference block.

    Returns an empty string when no chains are provided so callers can
    concatenate unconditionally. Per-chain truncation is hard — callers
    must enforce overall prompt budget separately (e.g.
    ``MAX_HISTORY_LENGTH`` in ``discussion_orchestrator.py``).

    Args:
        prior_chains: Iterable of dicts shaped like ``AnalysisChain.to_dict()``;
            non-dict entries are silently skipped.
        max_chains: Hard cap on number of chains carried (most-recent-first
            when caller provides an ordered iterable).
        max_chars_per_chain: Each chain's serialized block is truncated to
            this many characters (suffix appended on truncation).

    Returns:
        Multi-line string starting with the ``[上一轮推理参考]`` header, or
        ``""`` when no usable chains were provided.
    """

    if max_chains <= 0:
        return ""

    rendered_chains: list[str] = []
    for entry in prior_chains:
        if not isinstance(entry, Mapping):
            continue
        if len(rendered_chains) >= max_chains:
            break
        body_lines: list[str] = []
        for key in _FIELD_ORDER:
            value = entry.get(key)
            if isinstance(value, list):
                normalized = "; ".join(str(item).strip() for item in value if str(item).strip())
            elif value is None:
                normalized = ""
            else:
                normalized = str(value).strip()
            if not normalized:
                continue
            body_lines.append(f"- {key}: {normalized}")
        if not body_lines:
            continue
        body = "\n".join(body_lines)
        if len(body) > max_chars_per_chain:
            body = body[: max(0, max_chars_per_chain - 14)].rstrip() + "… [truncated]"
        rendered_chains.append(body)

    if not rendered_chains:
        return ""

    joined = "\n\n".join(
        f"[第 {idx + 1} 条]\n{chain}" for idx, chain in enumerate(rendered_chains)
    )
    return f"[上一轮推理参考]\n{joined}\n[/上一轮推理参考]"


__all__ = [
    "ChainFrame",
    "render_analysis_chain_prompt_block",
    "render_carryover_block",
]
