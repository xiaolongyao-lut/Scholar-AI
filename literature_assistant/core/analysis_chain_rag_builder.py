"""AnalysisChain builder for the RAG QA pipeline (ACR-020 ~ ACR-024).

Two builders share a common interface:
- ``build_deterministic`` produces a partial chain from the query + evidence
  snippets WITHOUT any extra LLM call (cheap, always available).
- ``build_with_llm`` calls the LLM (via the shared ``prompts.analysis_chain_helpers``
  rendering helper) to produce a full 6-field chain; on any failure it
  silently falls back to the deterministic path so the host pipeline
  never sees an exception.

Gating lives upstream in ``routers.chat_router.chat_ask``; this module is
flag-agnostic. The host decides which path to invoke based on
``feature_flags.is_enabled("analysis_chain_rag")`` +
``feature_flags.is_enabled("analysis_chain_rag_llm")``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from models.analysis_chain import AnalysisChainPayload


logger = logging.getLogger(__name__)


_MAX_OBSERVATION_LEN = 240
_MAX_EVIDENCE_PER_CHAIN = 3
_MAX_EVIDENCE_LEN = 200
_DEFAULT_NEXT_ACTION = "对照原文核验关键论点，必要时检索相关综述或最新数据补全证据链。"


def _truncate(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def build_deterministic(
    *,
    query: str,
    answer: str,
    evidence_snippets: list[str] | None = None,
) -> AnalysisChainPayload:
    """Construct a partial AnalysisChain without any extra LLM call.

    Conservative by design: only the three fields that can be derived
    factually from the request/response without inference get populated.
    ``mechanism`` / ``boundary`` / ``counter_evidence`` are left empty
    rather than fabricated.

    Args:
        query: the user's original question. Used to seed ``observation``.
        answer: the assistant's final answer (currently unused but reserved
            for a future heuristic that extracts a counter-evidence hint
            from hedging language).
        evidence_snippets: ordered list of context strings the chat layer
            received (typically ``ChatRequest.context``). The first
            ``_MAX_EVIDENCE_PER_CHAIN`` are surfaced verbatim (truncated to
            ``_MAX_EVIDENCE_LEN``).

    Returns:
        AnalysisChainPayload with observation + evidence (when any) +
        next_action populated; other fields empty.
    """

    _ = answer  # reserved for future hedging-signal heuristic
    snippets = list(evidence_snippets or [])
    observation = (
        f"用户提出问题：{_truncate(query, _MAX_OBSERVATION_LEN)}" if query else ""
    )
    evidence: list[str] = []
    for snippet in snippets[:_MAX_EVIDENCE_PER_CHAIN]:
        cleaned = _truncate(snippet, _MAX_EVIDENCE_LEN)
        if cleaned:
            evidence.append(cleaned)
    return AnalysisChainPayload(
        observation=observation,
        mechanism="",
        evidence=evidence,
        boundary="",
        counter_evidence=[],
        next_action=_DEFAULT_NEXT_ACTION if observation else "",
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if 0 <= start < end:
            cleaned = cleaned[start : end + 1].strip()
        else:
            return None
    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_to_payload(raw: dict[str, Any]) -> AnalysisChainPayload:
    def _str_field(key: str) -> str:
        value = raw.get(key, "")
        return str(value).strip() if value is not None else ""

    def _list_field(key: str) -> list[str]:
        value = raw.get(key, [])
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value[:_MAX_EVIDENCE_PER_CHAIN]:
            cleaned = _truncate(str(item or ""), _MAX_EVIDENCE_LEN)
            if cleaned:
                out.append(cleaned)
        return out

    return AnalysisChainPayload(
        observation=_truncate(_str_field("observation"), _MAX_OBSERVATION_LEN),
        mechanism=_truncate(_str_field("mechanism"), _MAX_OBSERVATION_LEN),
        evidence=_list_field("evidence"),
        boundary=_truncate(_str_field("boundary"), _MAX_OBSERVATION_LEN),
        counter_evidence=_list_field("counter_evidence"),
        next_action=_truncate(_str_field("next_action"), _MAX_OBSERVATION_LEN),
    )


def build_with_llm(
    *,
    query: str,
    answer: str,
    evidence_snippets: list[str] | None = None,
    llm_invoke: Any = None,
    frame: str = "irac",
) -> AnalysisChainPayload:
    """Use an LLM to render a full 6-field chain. Falls back deterministically.

    ``llm_invoke`` is a callable ``(prompt: str) -> str`` injected by the
    host so this module never imports the LLM stack directly. When the
    callable is missing, raises, or returns an unparseable payload, we
    silently return the deterministic chain.

    Caller-side gating ensures we only land here when both
    ``analysis_chain_rag=on`` and ``analysis_chain_rag_llm=on``.
    """

    deterministic = build_deterministic(
        query=query, answer=answer, evidence_snippets=evidence_snippets
    )
    if llm_invoke is None:
        return deterministic

    try:
        from prompts.analysis_chain_helpers import render_analysis_chain_prompt_block
    except ImportError:
        logger.debug("analysis_chain_helpers unavailable; returning deterministic chain")
        return deterministic

    evidence_present = bool(evidence_snippets)
    context_summary = (
        f"用户问题：{_truncate(query, 160)}；最终答案前 200 字：{_truncate(answer, 200)}"
    )
    prompt_block = render_analysis_chain_prompt_block(
        frame if frame in ("irac", "fincot") else "irac",
        context_summary=context_summary,
        evidence_present=evidence_present,
    )
    try:
        raw = llm_invoke(prompt_block)
    except Exception:  # noqa: BLE001 — host LLM failure must not break the chat response
        logger.exception("LLM invocation for analysis_chain_rag failed; falling back")
        return deterministic

    parsed = _extract_json_object(str(raw or ""))
    if parsed is None:
        logger.warning("analysis_chain_rag LLM output unparseable; falling back")
        return deterministic
    return _coerce_to_payload(parsed)


__all__ = [
    "build_deterministic",
    "build_with_llm",
]
