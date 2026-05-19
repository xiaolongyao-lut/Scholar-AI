"""Generation Dispatch Adapter — bridge between KeyPool and ModelDispatcher.

Purpose (plan v2 §13.1f.1):
    Provide a reusable, pure-helper layer so that new dispatcher-aware
    callers (discussion orchestrator, future agents) can drive the SAME
    credential failover + cooldown logic that the legacy ``pool.try_call``
    callsites use today, without:

      * re-implementing cooldown in the dispatcher,
      * leaking secrets into ``DispatchCandidate``,
      * breaking the cache layer (cache_key_parts is cred-agnostic already,
        see §13.1f.1 finding 2026-05-11).

This module is strictly additive. It does NOT:
    - register any HTTP routes
    - modify any production callsite
    - touch KeyPool internals (uses only the public is_cooled_down /
      mark_failure / mark_success surface added in the same slice)
    - persist any state

It DOES:
    - convert ``pool.list(category)`` into ``list[DispatchCandidate]``
      (secrets stripped, identity preserved)
    - return an ``invoke(candidate)`` wrapper that resolves the candidate
      back to the underlying Credential and routes cooldown via the
      pool's public mark_failure / mark_success methods

After this module lands, the C+1 main migration becomes a one-line swap
inside ``with_generation_pool_failover``:

    # before
    return pool.try_call(_GENERATION_CATEGORY, lambda cred: invoke_factory(cred)())

    # after (sketch — actual swap is the next slice, NOT in this file)
    candidates = build_candidates_from_pool(pool, _GENERATION_CATEGORY)
    invoke = make_pool_invoke_wrapper(
        pool, _GENERATION_CATEGORY,
        lambda cred: invoke_factory(cred)(),
    )
    batch = invoke_failover(candidates, invoke)
    if batch.first_success is None:
        raise DispatcherAllFailedError(...)
    return batch.first_success.output

Identity contract (locked by tests/test_generation_dispatch_adapter.py):
    * candidate_id is sha256("v1|<provider>|<model>|<base_url>|<api_key[:12]>")[:16]
    * version prefix ``v1`` lets a future fingerprint algorithm reset all
      dispatcher trace ids without renaming the cooldown table (which is
      keyed by ``Credential.cred_id`` and unaffected).
    * pool insertion order = DispatchCandidate.priority (lower = higher
      priority); dispatcher's _sort_by_priority preserves pool order.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Awaitable, Callable, TypeVar

from key_pool import Category, Credential, KeyPool
from model_dispatcher import DispatchCandidate

logger = logging.getLogger("GenerationDispatchAdapter")

T = TypeVar("T")

_ADAPTER_VERSION = "v1"


# ---------------------------------------------------------------------------
# Sentinel exceptions for the wrapper

class CredentialNotFoundError(LookupError):
    """Raised when a DispatchCandidate.candidate_id cannot be resolved to a
    Credential in the snapshot taken at wrapper-build time.

    Indicates the pool was mutated mid-dispatch, or the candidate list was
    built from a different pool. Dispatcher treats this as a hard failure
    of that candidate (not a soft skip).
    """


class CredentialCooledDownError(RuntimeError):
    """Raised when a candidate is in cooldown at invoke time.

    Dispatcher's failover mode catches any Exception and proceeds to the
    next candidate, so this gives ``pool.try_call``-equivalent skipping
    behaviour without dispatcher needing cooldown-specific awareness.
    """


# ---------------------------------------------------------------------------
# Identity

def candidate_id_from_credential(cred: Credential) -> str:
    """Return a stable, byte-deterministic candidate_id for ``cred``.

    Identity inputs are aligned with ``KeyPool``'s cooldown identity
    (api_key prefix + base_url + model) so a dispatcher trace can be
    cross-referenced with the pool's cooldown table.

    Version-prefixed: bumping ``_ADAPTER_VERSION`` is the documented
    migration knob to reset all dispatcher-side identities without
    touching cooldown state.
    """
    key_prefix, base_url, model = cred.cred_id
    material = "|".join(
        [
            _ADAPTER_VERSION,
            str(cred.provider or ""),
            str(model or ""),
            str(base_url or ""),
            str(key_prefix or ""),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# Candidate list builder

def build_candidates_from_pool(
    pool: KeyPool,
    category: Category,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> list[DispatchCandidate]:
    """Convert ``pool.list(category)`` into a list of DispatchCandidate.

    - Secrets are NOT included; only candidate_id / provider / model /
      base_url metadata that is safe to log or persist.
    - Priority = position in the pool list (lower = higher priority), so
      ``model_dispatcher._sort_by_priority`` preserves pool order.
    - Cooled-down credentials are still emitted; the wrapper returned by
      ``make_pool_invoke_wrapper`` is responsible for short-circuiting
      them at invoke time. This keeps the candidate list deterministic
      across cooldown state changes.
    - ``extra_metadata`` is merged into every candidate's ``metadata``
      field (callers can stamp e.g. ``{"task": "summary"}``); per-cred
      keys like ``source`` / ``category`` always take precedence.
    """
    creds = pool.list(category)
    candidates: list[DispatchCandidate] = []
    base_metadata = dict(extra_metadata or {})
    for index, cred in enumerate(creds):
        cid = candidate_id_from_credential(cred)
        metadata = dict(base_metadata)
        metadata.update(
            {
                "source": "key_pool",
                "category": str(category),
                "pool_index": index,
            }
        )
        candidates.append(
            DispatchCandidate(
                candidate_id=cid,
                provider=str(cred.provider or ""),
                model=str(cred.model or ""),
                base_url=str(cred.base_url or ""),
                credential_id=cid,
                priority=index,
                metadata=metadata,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Invoke wrapper

def make_pool_invoke_wrapper(
    pool: KeyPool,
    category: Category,
    legacy_invoke: Callable[[Credential], T],
    *,
    cooldown_on: Callable[[BaseException], bool] | None = None,
    on_attempt: Callable[[Credential, BaseException | None], None] | None = None,
) -> Callable[[DispatchCandidate], T]:
    """Build an ``invoke(candidate)`` for ``model_dispatcher.invoke_failover``.

    Behavioural contract — must match ``pool.try_call(category, fn)``:

      1. Skip cooled-down candidates (raise ``CredentialCooledDownError``).
      2. On success: call ``pool.mark_success(cred)`` and return the value.
      3. On exception: call ``pool.mark_failure(cred, exc, cooldown_on=...)``
         and re-raise so the dispatcher records the structured error and
         proceeds to the next candidate.
      4. Invoke the optional ``on_attempt(cred, exc_or_None)`` hook before
         re-raise / return, matching ``try_call``'s ``on_attempt`` semantics.

    Parameters
    ----------
    pool
        The KeyPool that owns cooldown state for these credentials.
    category
        Category to snapshot at build time. The snapshot is taken once so
        a single dispatch call sees a consistent candidate set even if the
        pool is mutated mid-flight.
    legacy_invoke
        ``invoke_factory(cred)``-style callable from existing callsites.
        Receives the resolved Credential, must return the call's result
        or raise.
    cooldown_on
        Optional override for ``pool.mark_failure``'s cooldown predicate.
        Defaults to ``KeyPool`` heuristic (401/403/429/4xx-shaped errors).
    on_attempt
        Optional symmetric callback mirroring ``KeyPool.try_call(on_attempt=...)``.

    Returns
    -------
    Callable[[DispatchCandidate], T]
        Suitable for passing as the ``invoke`` argument of
        ``invoke_failover``, ``ainvoke_failover``, etc.
    """
    # Snapshot credentials at build time so a single dispatch call has a
    # stable lookup map; pool mutations during the call surface as
    # ``CredentialNotFoundError`` rather than silent re-binding.
    snapshot = list(pool.list(category))
    cred_by_id: dict[str, Credential] = {
        candidate_id_from_credential(c): c for c in snapshot
    }

    def _invoke(candidate: DispatchCandidate) -> T:
        cred = cred_by_id.get(candidate.candidate_id)
        if cred is None:
            logger.warning(
                "generation_dispatch_adapter: candidate %s not in pool[%s] snapshot",
                candidate.candidate_id,
                category,
            )
            raise CredentialNotFoundError(
                f"candidate_id={candidate.candidate_id!r} not present in "
                f"pool[{category!s}] snapshot ({len(snapshot)} creds)"
            )
        if pool.is_cooled_down(cred):
            raise CredentialCooledDownError(
                f"cred {cred.provider}/{cred.model} is in cooldown"
            )
        try:
            result = legacy_invoke(cred)
        except Exception as exc:
            pool.mark_failure(cred, exc, cooldown_on=cooldown_on)
            if on_attempt is not None:
                try:
                    on_attempt(cred, exc)
                except Exception:  # pragma: no cover — observer must never break dispatch
                    logger.exception("on_attempt hook raised; swallowing")
            raise
        pool.mark_success(cred)
        if on_attempt is not None:
            try:
                on_attempt(cred, None)
            except Exception:  # pragma: no cover
                logger.exception("on_attempt hook raised; swallowing")
        return result

    return _invoke


# ---------------------------------------------------------------------------
# Async counterpart (mirror of make_pool_invoke_wrapper)

def make_pool_invoke_wrapper_async(
    pool: KeyPool,
    category: Category,
    legacy_invoke_async: Callable[[Credential], "Awaitable[T]"],
    *,
    cooldown_on: Callable[[BaseException], bool] | None = None,
    on_attempt: Callable[[Credential, BaseException | None], None] | None = None,
) -> Callable[[DispatchCandidate], "Awaitable[T]"]:
    """Async counterpart of :func:`make_pool_invoke_wrapper`.

    Behaviour mirrors ``pool.try_call_async``:
      * skip cooled-down candidates (raise ``CredentialCooledDownError``)
      * on exception: ``pool.mark_failure(cred, exc, cooldown_on=...)`` then re-raise
      * on success: ``pool.mark_success(cred)`` then return
      * ``on_attempt(cred, exc_or_None)`` hook called for both branches;
        hook errors are swallowed.

    The wrapper itself is sync (returns an awaitable) so it slots directly
    into ``ainvoke_failover(candidates, invoke=wrapper)``.
    """
    snapshot = list(pool.list(category))
    cred_by_id: dict[str, Credential] = {
        candidate_id_from_credential(c): c for c in snapshot
    }

    async def _invoke(candidate: DispatchCandidate) -> T:
        cred = cred_by_id.get(candidate.candidate_id)
        if cred is None:
            logger.warning(
                "generation_dispatch_adapter[async]: candidate %s not in pool[%s] snapshot",
                candidate.candidate_id,
                category,
            )
            raise CredentialNotFoundError(
                f"candidate_id={candidate.candidate_id!r} not present in "
                f"pool[{category!s}] snapshot ({len(snapshot)} creds)"
            )
        if pool.is_cooled_down(cred):
            raise CredentialCooledDownError(
                f"cred {cred.provider}/{cred.model} is in cooldown"
            )
        try:
            result = await legacy_invoke_async(cred)
        except Exception as exc:
            pool.mark_failure(cred, exc, cooldown_on=cooldown_on)
            if on_attempt is not None:
                try:
                    on_attempt(cred, exc)
                except Exception:  # pragma: no cover
                    logger.exception("on_attempt hook raised; swallowing")
            raise
        pool.mark_success(cred)
        if on_attempt is not None:
            try:
                on_attempt(cred, None)
            except Exception:  # pragma: no cover
                logger.exception("on_attempt hook raised; swallowing")
        return result

    return _invoke


__all__ = [
    "candidate_id_from_credential",
    "build_candidates_from_pool",
    "make_pool_invoke_wrapper",
    "make_pool_invoke_wrapper_async",
    "CredentialNotFoundError",
    "CredentialCooledDownError",
]
