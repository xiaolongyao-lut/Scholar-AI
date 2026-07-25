"""Allowlisted source registry and adapter protocol."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from .models import CandidateManifest, SearchQuery, SourcePolicy


class SourceAdapterError(RuntimeError):
    """Bounded source failure that does not authorize a fallback route."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "source_error")[:80]
        self.safe_message = str(message or "source request failed").replace("\n", " ")[:500]


class SourceHumanGateRequired(SourceAdapterError):
    """Source response requires a visible, user-controlled access step."""

    def __init__(self, gate_type: str, url: str, message: str) -> None:
        super().__init__("human_gate_required", message)
        self.gate_type = gate_type
        self.url = url


@runtime_checkable
class SourceAdapter(Protocol):
    """One metadata source implementing the shared search contract."""

    @property
    def policy(self) -> SourcePolicy:
        """Return the immutable source policy."""

    async def search(self, query: SearchQuery, *, run_id: str) -> tuple[CandidateManifest, ...]:
        """Return bounded normalized candidates without mutating durable state."""


class SourceRegistry:
    """Exact-id registry shared by desktop HTTP and injected tests."""

    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        """Initialize a registry from explicitly supplied adapters."""

        self._adapters: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        """Register one adapter once using its policy source id."""

        if not isinstance(adapter, SourceAdapter):
            raise TypeError("adapter must implement SourceAdapter")
        source_id = adapter.policy.source_id
        existing = self._adapters.get(source_id)
        if existing is not None and existing is not adapter:
            raise ValueError(f"source adapter already registered: {source_id}")
        self._adapters[source_id] = adapter

    def get(self, source_id: str) -> SourceAdapter:
        """Return one enabled adapter or raise a bounded lookup error."""

        normalized = str(source_id or "").strip().lower()
        adapter = self._adapters.get(normalized)
        if adapter is None or not adapter.policy.enabled:
            raise KeyError(f"source adapter unavailable: {normalized}")
        return adapter

    def policies(self) -> tuple[SourcePolicy, ...]:
        """Return enabled policies in stable source-id order."""

        return tuple(
            adapter.policy
            for source_id, adapter in sorted(self._adapters.items())
            if adapter.policy.enabled
        )
