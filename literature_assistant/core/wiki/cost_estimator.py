"""Compatibility helpers for Wiki compile cost estimates.

The canonical dry-run estimate lives in ``wiki.compiler`` because it is based
on registry chunks and budget checks. This module keeps the older page-count
API importable for plans, scripts, and notebooks while preserving the same
"estimate, not billing record" boundary.
"""

from __future__ import annotations

from typing import Final, TypedDict

from literature_assistant.core.llm_pricing import estimate_cost_usd, lookup_pricing


class WikiCompileCostEstimate(TypedDict):
    """Dictionary shape returned by ``estimate_wiki_compile_cost``."""

    page_count: int
    model: str
    prompt_tokens_per_page: int
    completion_tokens_per_page: int
    total_prompt_tokens: int
    total_completion_tokens: int
    estimated_cost_usd: float
    pricing: tuple[float, float]
    pricing_source: str


DEFAULT_PROMPT_TOKENS_PER_PAGE: Final[int] = 8000
DEFAULT_COMPLETION_TOKENS_PER_PAGE: Final[int] = 2000
DEFAULT_TOKENS_PER_PAGE: Final[dict[str, int]] = {
    "prompt_tokens": DEFAULT_PROMPT_TOKENS_PER_PAGE,
    "completion_tokens": DEFAULT_COMPLETION_TOKENS_PER_PAGE,
}


def estimate_wiki_compile_cost(
    page_count: int,
    model: str = "claude-3-5-sonnet",
    *,
    prompt_tokens_per_page: int | None = None,
    completion_tokens_per_page: int | None = None,
) -> WikiCompileCostEstimate:
    """Estimate page-count based Wiki compilation cost.

    Args:
        page_count: Number of planned pages. Must be a non-negative integer.
        model: Model identifier for the local pricing table. Must be non-empty.
        prompt_tokens_per_page: Optional non-negative prompt token estimate.
        completion_tokens_per_page: Optional non-negative output token estimate.

    Returns:
        A JSON-friendly cost estimate. Prices come from the local compatibility
        pricing table and should be treated as planning data only.
    """

    normalized_page_count = _non_negative_int(page_count, "page_count")
    normalized_model = _non_empty_string(model, "model")
    prompt_tokens = _optional_non_negative_int(
        prompt_tokens_per_page,
        "prompt_tokens_per_page",
        default=DEFAULT_PROMPT_TOKENS_PER_PAGE,
    )
    completion_tokens = _optional_non_negative_int(
        completion_tokens_per_page,
        "completion_tokens_per_page",
        default=DEFAULT_COMPLETION_TOKENS_PER_PAGE,
    )

    total_prompt_tokens = normalized_page_count * prompt_tokens
    total_completion_tokens = normalized_page_count * completion_tokens
    pricing = lookup_pricing(normalized_model)
    estimated_cost = estimate_cost_usd(
        normalized_model,
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
    )

    return {
        "page_count": normalized_page_count,
        "model": normalized_model,
        "prompt_tokens_per_page": prompt_tokens,
        "completion_tokens_per_page": completion_tokens,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "estimated_cost_usd": estimated_cost,
        "pricing": pricing,
        "pricing_source": "literature_assistant.core.llm_pricing",
    }


def format_cost_estimate(estimate: WikiCompileCostEstimate) -> str:
    """Format a validated estimate for CLI or runbook output.

    Args:
        estimate: Dictionary returned by ``estimate_wiki_compile_cost``.

    Returns:
        Human-readable multi-line summary. Invalid estimate shapes are rejected
        so callers do not silently present misleading cost data.
    """

    _validate_estimate(estimate)
    return f"""
Wiki Compilation Cost Estimate
===============================

Pages: {estimate['page_count']}
Model: {estimate['model']}

Token Estimate:
  - Prompt tokens per page: {estimate['prompt_tokens_per_page']:,}
  - Completion tokens per page: {estimate['completion_tokens_per_page']:,}
  - Total prompt tokens: {estimate['total_prompt_tokens']:,}
  - Total completion tokens: {estimate['total_completion_tokens']:,}

Cost Estimate:
  - Input cost: ${estimate['pricing'][0]:.2f} / 1M tokens
  - Output cost: ${estimate['pricing'][1]:.2f} / 1M tokens
  - Estimated total cost: ${estimate['estimated_cost_usd']:.2f} USD
  - Pricing source: {estimate['pricing_source']}

Note: This compatibility estimate is for planning only. The canonical Wiki
compile dry-run estimate is generated from registry chunks in wiki.compiler.
""".strip()


def _validate_estimate(estimate: WikiCompileCostEstimate) -> None:
    if not isinstance(estimate, dict):
        raise TypeError("estimate must be a dictionary returned by estimate_wiki_compile_cost")
    _non_negative_int(estimate.get("page_count"), "estimate.page_count")
    _non_empty_string(estimate.get("model"), "estimate.model")
    _non_negative_int(estimate.get("prompt_tokens_per_page"), "estimate.prompt_tokens_per_page")
    _non_negative_int(estimate.get("completion_tokens_per_page"), "estimate.completion_tokens_per_page")
    _non_negative_int(estimate.get("total_prompt_tokens"), "estimate.total_prompt_tokens")
    _non_negative_int(estimate.get("total_completion_tokens"), "estimate.total_completion_tokens")
    _non_negative_float(estimate.get("estimated_cost_usd"), "estimate.estimated_cost_usd")
    pricing = estimate.get("pricing")
    if not isinstance(pricing, tuple) or len(pricing) != 2:
        raise TypeError("estimate.pricing must be a two-item tuple")
    _non_negative_float(pricing[0], "estimate.pricing[0]")
    _non_negative_float(pricing[1], "estimate.pricing[1]")
    _non_empty_string(estimate.get("pricing_source"), "estimate.pricing_source")


def _optional_non_negative_int(value: int | None, name: str, *, default: int) -> int:
    if value is None:
        return default
    return _non_negative_int(value, name)


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _non_negative_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    numeric_value = float(value)
    if numeric_value < 0:
        raise ValueError(f"{name} must be non-negative")
    return numeric_value


def _non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized
