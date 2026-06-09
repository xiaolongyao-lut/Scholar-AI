"""Public facade for model-call gateway operations.

This module is intentionally thin. It gives callers a stable
``llm.gateway`` import target while preserving the existing
``model_call_gateway`` runtime behavior behind the facade.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeAlias

import model_call_gateway as _legacy_gateway


GatewayKind: TypeAlias = Literal["embedding", "rerank", "llm"]


def _validate_kind(kind: GatewayKind) -> GatewayKind:
    if kind not in ("embedding", "rerank", "llm"):
        raise ValueError("kind must be one of: embedding, rerank, llm")
    return kind


def _validate_cache_key_parts(cache_key_parts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cache_key_parts, dict):
        raise TypeError("cache_key_parts must be a dict")
    if not cache_key_parts:
        raise ValueError("cache_key_parts must not be empty")
    return cache_key_parts


def invoke(
    *,
    kind: GatewayKind,
    cache_key_parts: dict[str, Any],
    payload: Any,
    invoke_fn: Callable[[], Any],
    budget_estimate_tokens: int = 0,
    skip_predicate: Callable[[], bool] | None = None,
    validate_result: Callable[[Any], bool] | None = None,
    cache_enabled: bool = True,
    on_decision: Callable[[str, str], None] | None = None,
    stage: str | None = None,
) -> Any:
    """Invoke a model operation through the shared gateway.

    Args:
        kind: Gateway bucket controlling cache/retry/concurrency behavior.
        cache_key_parts: Stable cache identity fields understood by the
            underlying gateway.
        payload: Provider payload for metrics/cache accounting.
        invoke_fn: No-argument function that performs the actual provider call.
        budget_estimate_tokens: Optional approximate token budget for metrics.
        skip_predicate: Optional early-skip predicate.
        validate_result: Optional schema validator for the provider result.
        cache_enabled: Whether the gateway cache is allowed.
        on_decision: Optional callback receiving cache status and decision.
        stage: Optional metric stage label.

    Returns:
        The underlying ``model_call_gateway.gated_call`` result.

    Raises:
        TypeError: If callable or mapping inputs have invalid shapes.
        ValueError: If ``kind`` or cache key fields are invalid.
    """

    _validate_kind(kind)
    _validate_cache_key_parts(cache_key_parts)
    if not callable(invoke_fn):
        raise TypeError("invoke_fn must be callable")
    if skip_predicate is not None and not callable(skip_predicate):
        raise TypeError("skip_predicate must be callable or None")
    if validate_result is not None and not callable(validate_result):
        raise TypeError("validate_result must be callable or None")
    if on_decision is not None and not callable(on_decision):
        raise TypeError("on_decision must be callable or None")
    if not isinstance(budget_estimate_tokens, int) or budget_estimate_tokens < 0:
        raise ValueError("budget_estimate_tokens must be a non-negative integer")
    if not isinstance(cache_enabled, bool):
        raise TypeError("cache_enabled must be a boolean")

    return _legacy_gateway.gated_call(
        kind=kind,
        cache_key_parts=cache_key_parts,
        payload=payload,
        invoke=invoke_fn,
        budget_estimate_tokens=budget_estimate_tokens,
        skip_predicate=skip_predicate,
        validate_result=validate_result,
        cache_enabled=cache_enabled,
        on_decision=on_decision,
        stage=stage,
    )


def get_cached(
    *,
    kind: GatewayKind,
    cache_key_parts: dict[str, Any],
    budget_estimate_tokens: int = 0,
    cache_enabled: bool = True,
    on_decision: Callable[[str, str], None] | None = None,
    stage: str | None = None,
) -> tuple[bool, Any]:
    """Return a cached gateway result without invoking a provider.

    Args:
        kind: Gateway bucket controlling cache namespace.
        cache_key_parts: Stable cache identity fields.
        budget_estimate_tokens: Optional approximate token budget for metrics.
        cache_enabled: Whether cache lookup is allowed.
        on_decision: Optional callback receiving cache status and decision.
        stage: Optional metric stage label.

    Returns:
        ``(hit, value)`` from the underlying gateway cache lookup.

    Raises:
        TypeError: If mapping/callback inputs have invalid shapes.
        ValueError: If ``kind`` or cache key fields are invalid.
    """

    _validate_kind(kind)
    _validate_cache_key_parts(cache_key_parts)
    if not isinstance(budget_estimate_tokens, int) or budget_estimate_tokens < 0:
        raise ValueError("budget_estimate_tokens must be a non-negative integer")
    if not isinstance(cache_enabled, bool):
        raise TypeError("cache_enabled must be a boolean")
    if on_decision is not None and not callable(on_decision):
        raise TypeError("on_decision must be callable or None")

    return _legacy_gateway.get_cached_call(
        kind=kind,
        cache_key_parts=cache_key_parts,
        budget_estimate_tokens=budget_estimate_tokens,
        cache_enabled=cache_enabled,
        on_decision=on_decision,
        stage=stage,
    )


def with_generation_pool_failover(
    invoke_factory: Callable[[Any], Callable[[], Any]],
) -> Callable[[], Any]:
    """Wrap generation calls with the existing key-pool failover behavior.

    Args:
        invoke_factory: Existing factory shape accepted by
            ``model_call_gateway.with_generation_pool_failover``.

    Returns:
        A no-argument callable that preserves the legacy failover semantics.

    Raises:
        TypeError: If ``invoke_factory`` is not callable.
    """

    if not callable(invoke_factory):
        raise TypeError("invoke_factory must be callable")
    return _legacy_gateway.with_generation_pool_failover(invoke_factory)


__all__ = [
    "GatewayKind",
    "get_cached",
    "invoke",
    "with_generation_pool_failover",
]
