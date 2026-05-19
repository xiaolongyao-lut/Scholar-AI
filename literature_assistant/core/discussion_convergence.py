"""Discussion auto-stop convergence helpers (Plan 2026-05-15 / D2).

Pure helpers. The orchestrator (D3) decides what to record into
``DiscussionConvergenceTrace`` and when to break the turn loop.

Embedding path reuses ``chunk_vector_store.batch_embed_texts`` so the
existing provider resolution, token guard, retry, and failover apply.
Tests inject a stub ``embed_fn`` / ``invoke_agent`` to avoid real network.
"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]
InvokeFn = Callable[[Any, str], Awaitable[str]]


class ConvergenceError(Exception):
    """Base class for convergence-helper failures."""


class EmbeddingFailure(ConvergenceError):
    pass


class JudgeFailure(ConvergenceError):
    pass


class JudgeParseFailure(ConvergenceError):
    pass


@dataclass(frozen=True)
class JudgeOutcome:
    done: bool
    confidence: float
    reason: str


def format_turn_text(turn_messages: list[dict[str, Any]]) -> str:
    """Concatenate agent messages from one turn into a single embedding input."""
    parts: list[str] = []
    for msg in turn_messages:
        content = msg.get("content", "")
        if not content:
            continue
        agent_id = msg.get("agent_id", "")
        parts.append(f"[{agent_id}] {content}")
    return "\n\n".join(parts)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine of two equal-length non-zero vectors.

    Raises ``ValueError`` on length mismatch, empty input, or zero-norm
    vector — these are caller bugs, not numeric noise, so the orchestrator
    surfaces them as ``judge_errors[stage=embedding]``.
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"vector length mismatch: {len(vec_a)} vs {len(vec_b)}"
        )
    if not vec_a:
        raise ValueError("vectors must be non-empty")
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("cosine_similarity undefined for zero-norm vector")
    return dot / (norm_a * norm_b)


async def embed_turn_texts(
    texts: list[str],
    *,
    embed_fn: EmbedFn,
) -> list[list[float]]:
    """Embed turn texts via the injected embedder.

    Real usage: ``embed_fn = chunk_vector_store.batch_embed_texts``. Tests
    pass a stub. Any underlying failure is re-raised as ``EmbeddingFailure``
    so the orchestrator can route it to ``judge_errors[stage=embedding]``.
    """
    if not texts:
        return []
    try:
        return await embed_fn(texts)
    except Exception as exc:  # noqa: BLE001 — translate to typed failure
        raise EmbeddingFailure(str(exc)) from exc


_JUDGE_PROMPT_INSTRUCTIONS = (
    "You are a convergence judge for a multi-agent discussion. "
    "Given the recent dialogue, decide whether continuing the discussion "
    "would still surface meaningful new information, or whether the agents "
    "have already exposed the key consensus and the key remaining "
    "disagreement clearly enough for a synthesizer to write a final answer.\n\n"
    "Do NOT pick a winner. Do NOT inject your own opinion. Only judge "
    "whether further turns would add material new content.\n\n"
    'Return STRICT JSON: {"done": true|false, "confidence": 0.0..1.0, "reason": "..."}\n'
    "No prose outside the JSON object.\n\n"
    "=== DIALOGUE ===\n"
)


def _build_judge_prompt(history_text: str) -> str:
    return _JUDGE_PROMPT_INSTRUCTIONS + history_text


def _summarize_history(history: list[dict[str, Any]], *, max_chars: int = 4000) -> str:
    """Most-recent-first compaction of history into prompt-sized text.

    Each turn entry has shape ``{"turn_index": int, "messages": [...]}``;
    each message has ``agent_id`` / ``role`` / ``content``.
    """
    chunks: list[str] = []
    used = 0
    truncated = False
    for turn in reversed(history):
        ti = turn.get("turn_index", "?")
        for m in turn.get("messages", []):
            piece = f"[turn {ti} | {m.get('agent_id', '?')}] {m.get('content', '')}"
            if used + len(piece) > max_chars:
                truncated = True
                break
            chunks.append(piece)
            used += len(piece)
        if truncated:
            break
    body = "\n\n".join(reversed(chunks))
    if truncated:
        body = body + "\n\n[…truncated…]"
    return body


def parse_judge_json(text: str) -> JudgeOutcome:
    """Parse the judge's response into a ``JudgeOutcome``.

    Tolerates a single ```json fence; salvages a JSON object surrounded by
    explanatory prose. Raises ``JudgeParseFailure`` on anything still
    invalid so the orchestrator records the failure and continues.
    """
    if not isinstance(text, str) or not text.strip():
        raise JudgeParseFailure("empty judge response")
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body[:4].lower() == "json":
            body = body[4:]
        body = body.strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        start = body.find("{")
        end = body.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise JudgeParseFailure(
                f"no JSON object in response: {body[:120]!r}"
            )
        try:
            data = json.loads(body[start : end + 1])
        except json.JSONDecodeError as exc:
            raise JudgeParseFailure(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgeParseFailure(
            f"judge response is not an object: {type(data).__name__}"
        )
    if "done" not in data:
        raise JudgeParseFailure("judge response missing 'done'")
    done = data["done"]
    if not isinstance(done, bool):
        raise JudgeParseFailure(f"'done' is not bool: {type(done).__name__}")
    confidence_raw = data.get("confidence", 0.5)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as exc:
        raise JudgeParseFailure(
            f"'confidence' not numeric: {confidence_raw!r}"
        ) from exc
    confidence = max(0.0, min(1.0, confidence))
    reason = data.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)
    if len(reason) > 512:
        reason = reason[:512]
    return JudgeOutcome(done=done, confidence=confidence, reason=reason)


async def judge_convergence(
    *,
    history: list[dict[str, Any]],
    judge_cand: Any,
    invoke_agent: InvokeFn,
) -> JudgeOutcome:
    """Ask the judge agent whether the discussion has converged.

    Raises ``JudgeFailure`` on transport/agent error and
    ``JudgeParseFailure`` on malformed response. The orchestrator catches
    both, records into ``judge_errors``, and treats the call as
    ``done=False`` (safe default).
    """
    history_text = _summarize_history(history)
    prompt = _build_judge_prompt(history_text)
    try:
        response = await invoke_agent(judge_cand, prompt)
    except Exception as exc:  # noqa: BLE001
        raise JudgeFailure(str(exc)) from exc
    return parse_judge_json(response)


__all__ = [
    "ConvergenceError",
    "EmbeddingFailure",
    "JudgeFailure",
    "JudgeOutcome",
    "JudgeParseFailure",
    "cosine_similarity",
    "embed_turn_texts",
    "format_turn_text",
    "judge_convergence",
    "parse_judge_json",
]
