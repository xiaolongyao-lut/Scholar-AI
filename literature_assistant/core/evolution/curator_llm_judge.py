"""
LLM-judged semantic conflict detection.

Scope:
    - Receive small batches of candidate claims that already share
      (workspace_id, project_id, memory_type) and exhibit a
      structural-polarity disagreement (accepted/promoted + rejected).
    - Ask an LLM to judge whether the claims express a semantic
      contradiction (same fact, opposite assertion / incompatible
      quantitative value / mutually exclusive scope).
    - Return a small JSON verdict the curator can attach to its
      conflict report. Never write candidate state.

This module is intentionally narrow:
    - No persistence.
    - No credential storage.
    - No retry loop beyond what `llm.gateway.invoke` already provides.
    - No sensitive material in prompts, logs, or failure output: callers must
      have run the sensitive-content scan upstream (capture path already does).

Default gating: `evolution.curator_llm_judge_enabled` (false) AND
`evolution.curator_enabled` (false). Both must be true for the curator
to invoke the judge; failures degrade silently to structural-only.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Dict, List, Optional

import httpx

from llm.gateway import invoke as invoke_llm_gateway
from runtime_env import resolve_llm_config


logger = logging.getLogger("EvolutionCuratorJudge")

# Defaults mirror contextual_chunker.py so the same Ark deployment is
# reused when nothing else is configured. resolve_llm_config() also
# honors ARK_API_KEY / OPENAI_API_KEY / etc env overrides.
DEFAULT_ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
DEFAULT_ARK_MODEL = "ep-20260414011719-8x7s4"

# Hard cap to keep prompts small and predictable. Buckets exceeding
# this are truncated; the judge sees only the first MAX_CLAIMS rows.
MAX_CLAIMS_PER_BUCKET = 8

JUDGE_PROMPT_TEMPLATE = """You are reviewing whether the following candidate \
memories express a semantic contradiction.

The candidates already share (workspace, project, memory_type) and reviewers \
have given them mixed accept/reject decisions. Decide whether the *content* of \
the claims is actually contradictory.

Respond with a single JSON object on one line, no prose, no markdown:
  {{"conflict": true|false, "rationale": "<one short Chinese sentence>"}}

Set conflict=true only when at least two claims assert the same fact with \
incompatible values or mutually exclusive scope. Set conflict=false for \
overlapping but compatible claims, complementary phrasings, or differences \
explained by context.

Candidate claims:
{claim_list}
"""


@dataclass(frozen=True)
class JudgeVerdict:
    """Structured judge output appended to a conflict report entry."""

    conflict: bool
    rationale: str
    judged_claim_count: int
    error: Optional[str] = None

    def to_report_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "conflict": bool(self.conflict),
            "rationale": str(self.rationale or "")[:240],
            "judged_claim_count": int(self.judged_claim_count),
        }
        if self.error:
            payload["error"] = str(self.error)[:240]
        return payload


JudgeCallable = Callable[[List[str]], JudgeVerdict]


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
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


def _extract_output_text(payload: Any) -> str:
    """Mirror contextual_chunker._extract_output_text for the Ark response shape."""

    if not isinstance(payload, dict):
        return ""
    output = payload.get("output")
    if isinstance(output, list):
        texts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text") or content.get("value")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        if texts:
            return "\n".join(texts)
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    if isinstance(payload.get("text"), str):
        return payload["text"]
    return ""


def _call_judge_once(prompt: str, api_key: str, *, model: str, base_url: str) -> str:
    # Security gate: validate endpoint before sending credentials
    try:
        from provider_endpoint_policy import (
            TrustSource,
            validate_endpoint,
        )

        decision = validate_endpoint(
            base_url,
            trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
            allow_loopback_http=True,
        )
        if not decision.allowed:
            raise RuntimeError(
                f"Evolution judge endpoint rejected by security policy: {base_url} "
                f"(reason: {decision.reason})"
            )
    except RuntimeError:
        raise
    except Exception as policy_exc:
        raise RuntimeError(
            f"Endpoint policy check failed for {base_url}: {policy_exc}"
        ) from policy_exc

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    }
    fallback_body = {"model": model, "input": prompt}
    with httpx.Client(timeout=20.0) as client:
        response = client.post(base_url, headers=headers, json=body)
        if response.status_code == 400:
            text = (response.text or "").lower()
            if "unknown type: text" in text or "content.type" in text:
                response = client.post(base_url, headers=headers, json=fallback_body)
    response.raise_for_status()
    return _extract_output_text(response.json())


def _build_prompt(claims: List[str]) -> str:
    numbered = "\n".join(f"{idx + 1}. {claim}" for idx, claim in enumerate(claims))
    return JUDGE_PROMPT_TEMPLATE.format(claim_list=numbered)


def call_curator_llm_judge(
    claims: List[str],
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> JudgeVerdict:
    """Default judge implementation. Returns a structural verdict on failure.

    Truncates claim list to MAX_CLAIMS_PER_BUCKET, then routes through
    `llm.gateway.invoke(kind="llm", task="evolution_curator_judge", ...)` so the
    call participates in the existing cache, retry, semaphore, and
    metrics infrastructure.
    """

    trimmed = [c.strip() for c in (claims or []) if isinstance(c, str) and c.strip()]
    trimmed = trimmed[:MAX_CLAIMS_PER_BUCKET]
    if len(trimmed) < 2:
        return JudgeVerdict(
            conflict=False,
            rationale="judge skipped: fewer than 2 non-empty claims",
            judged_claim_count=len(trimmed),
        )

    resolved_key, resolved_base, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
    if not resolved_key:
        return JudgeVerdict(
            conflict=False,
            rationale="judge skipped: no LLM credential",
            judged_claim_count=len(trimmed),
            error="missing_api_key",
        )

    prompt = _build_prompt(trimmed)
    try:
        raw = invoke_llm_gateway(
            kind="llm",
            cache_key_parts={
                "model": resolved_model,
                "prompt_hash": _prompt_hash(prompt),
                "claim_count": len(trimmed),
                "task": "evolution_curator_judge",
            },
            payload={"prompt": prompt},
            invoke_fn=lambda: _call_judge_once(
                prompt,
                resolved_key,
                model=resolved_model,
                base_url=resolved_base,
            ),
            validate_result=lambda value: isinstance(value, str),
            stage="evolution_curator_judge",
        )
    except httpx.HTTPError as exc:
        logger.warning("curator judge HTTP error: %s", exc.__class__.__name__)
        return JudgeVerdict(
            conflict=False,
            rationale="judge unavailable",
            judged_claim_count=len(trimmed),
            error=exc.__class__.__name__,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("curator judge unexpected error: %s", exc.__class__.__name__)
        return JudgeVerdict(
            conflict=False,
            rationale="judge unavailable",
            judged_claim_count=len(trimmed),
            error=exc.__class__.__name__,
        )

    parsed = _extract_json_object(str(raw or ""))
    if parsed is None:
        return JudgeVerdict(
            conflict=False,
            rationale="judge output unparseable",
            judged_claim_count=len(trimmed),
            error="parse_error",
        )

    conflict_raw = parsed.get("conflict")
    if isinstance(conflict_raw, str):
        conflict_flag = conflict_raw.strip().lower() in {"true", "1", "yes"}
    else:
        conflict_flag = bool(conflict_raw)
    rationale = str(parsed.get("rationale") or "").strip() or (
        "判定为存在矛盾" if conflict_flag else "判定为不构成矛盾"
    )
    return JudgeVerdict(
        conflict=conflict_flag,
        rationale=rationale,
        judged_claim_count=len(trimmed),
    )
