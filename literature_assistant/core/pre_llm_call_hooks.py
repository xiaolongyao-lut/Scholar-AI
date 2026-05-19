"""Typed pre-LLM hook registry for local chat entry points.

The registry is intentionally in-process and empty by default. Optional
integrations can register hooks during app startup or tests without changing
the core chat router contract.
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace


@dataclass(frozen=True, slots=True)
class PreLlmCallImage:
    """Image attachment shape exposed to pre-LLM hooks.

    Args:
        mime: Browser-provided MIME type. Callers must validate allowed types.
        data_b64: Base64 payload without a data-URL prefix.
        size: Original byte size reported by the client.
        name: Optional user-facing file name. Must not be treated as a path.
    """

    mime: str
    data_b64: str
    size: int
    name: str | None = None


@dataclass(frozen=True, slots=True)
class PreLlmCallContext:
    """Immutable input provided to each pre-LLM hook.

    Args:
        query: Non-empty user text that will be sent to the LLM.
        context: Context blocks that will be sent alongside the query.
        mode: Product mode for the originating chat surface.
        session_id: Stable session id for the current turn.
        project_id: Optional active project id.
        images: Optional image attachments. Hooks may inspect them but the
            default registry never invokes a vision provider.
        metadata: Extra route-local facts for future hooks.
    """

    query: str
    context: tuple[str, ...]
    mode: str
    session_id: str
    project_id: str | None = None
    images: tuple[PreLlmCallImage, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreLlmCallResult:
    """Hook output that can replace the query and context blocks."""

    query: str
    context: tuple[str, ...]


PreLlmCallHookResult = PreLlmCallResult | None
PreLlmCallHook = Callable[
    [PreLlmCallContext],
    PreLlmCallHookResult | Awaitable[PreLlmCallHookResult],
]


@dataclass(frozen=True, order=True, slots=True)
class _RegisteredHook:
    priority: int
    sequence: int
    hook: PreLlmCallHook = field(compare=False)


_LOCK = threading.RLock()
_HOOKS: list[_RegisteredHook] = []
_SEQUENCE = 0


def _validate_context(context: PreLlmCallContext) -> None:
    if not context.query.strip():
        raise ValueError("pre-LLM query must be non-empty")
    if any(not isinstance(item, str) for item in context.context):
        raise TypeError("pre-LLM context must contain strings only")
    if any(not image.mime or image.size < 1 or not image.data_b64 for image in context.images):
        raise ValueError("pre-LLM images must include mime, data_b64, and positive size")


def _validate_result(result: PreLlmCallResult) -> None:
    if not result.query.strip():
        raise ValueError("pre-LLM hook returned an empty query")
    if any(not isinstance(item, str) for item in result.context):
        raise TypeError("pre-LLM hook returned non-string context")


def register_pre_llm_call_hook(hook: PreLlmCallHook, *, priority: int = 100) -> Callable[[], None]:
    """Register a pre-LLM hook and return an unregister callback.

    Args:
        hook: Callable that receives `PreLlmCallContext` and may return a
            replacement `PreLlmCallResult`.
        priority: Lower values run first. Equal priorities keep registration
            order so integration behavior is deterministic.

    Returns:
        A callback that removes this hook if it is still registered.

    Raises:
        TypeError: If `hook` is not callable or `priority` is not an integer.
    """

    if not callable(hook):
        raise TypeError("pre-LLM hook must be callable")
    if not isinstance(priority, int):
        raise TypeError("pre-LLM hook priority must be an integer")

    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        registered = _RegisteredHook(priority=priority, sequence=_SEQUENCE, hook=hook)
        _HOOKS.append(registered)
        _HOOKS.sort()

    def unregister() -> None:
        with _LOCK:
            _HOOKS[:] = [item for item in _HOOKS if item is not registered]

    return unregister


def clear_pre_llm_call_hooks() -> None:
    """Remove all registered hooks.

    Intended for test isolation and local teardown. Production code should keep
    the returned unregister callback from `register_pre_llm_call_hook`.
    """

    with _LOCK:
        _HOOKS.clear()


def list_pre_llm_call_hooks() -> tuple[PreLlmCallHook, ...]:
    """Return registered hooks in execution order."""

    with _LOCK:
        return tuple(item.hook for item in _HOOKS)


async def run_pre_llm_call_hooks(context: PreLlmCallContext) -> PreLlmCallResult:
    """Run registered pre-LLM hooks and return the final query/context pair.

    Args:
        context: Immutable call context for the current chat turn.

    Returns:
        The effective query/context after every hook has run. With no hooks,
        this is equivalent to the original `context.query` and
        `context.context`.
    """

    _validate_context(context)
    with _LOCK:
        hooks = tuple(_HOOKS)

    query = context.query
    blocks = context.context
    for registered in hooks:
        current = replace(context, query=query, context=blocks)
        outcome = registered.hook(current)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if outcome is None:
            continue
        _validate_result(outcome)
        query = outcome.query
        blocks = tuple(outcome.context)

    return PreLlmCallResult(query=query, context=blocks)
