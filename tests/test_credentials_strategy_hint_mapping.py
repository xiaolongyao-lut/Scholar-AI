"""Test B5: Cost tier canonical mapping (2026-05-26).

Verify that normalize_strategy_hint accepts legacy values and returns
canonical product tiers (low/medium/high/xhigh/max).
"""

import pytest

from literature_assistant.core.models.credentials import (
    CredentialStrategyHint,
    normalize_strategy_hint,
)


class TestNormalizeStrategyHint:
    """B5: Canonical five-tier mapping with legacy compatibility."""

    def test_canonical_tiers_pass_through(self):
        """Canonical tiers return themselves."""
        assert normalize_strategy_hint("low") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("medium") == CredentialStrategyHint.MEDIUM
        assert normalize_strategy_hint("high") == CredentialStrategyHint.HIGH
        assert normalize_strategy_hint("xhigh") == CredentialStrategyHint.XHIGH
        assert normalize_strategy_hint("max") == CredentialStrategyHint.MAX

    def test_canonical_enum_pass_through(self):
        """Canonical enum values return themselves."""
        assert normalize_strategy_hint(CredentialStrategyHint.LOW) == CredentialStrategyHint.LOW
        assert normalize_strategy_hint(CredentialStrategyHint.MEDIUM) == CredentialStrategyHint.MEDIUM
        assert normalize_strategy_hint(CredentialStrategyHint.HIGH) == CredentialStrategyHint.HIGH
        assert normalize_strategy_hint(CredentialStrategyHint.XHIGH) == CredentialStrategyHint.XHIGH
        assert normalize_strategy_hint(CredentialStrategyHint.MAX) == CredentialStrategyHint.MAX

    def test_legacy_cheap_maps_to_low(self):
        """Legacy 'cheap' maps to LOW."""
        assert normalize_strategy_hint("cheap") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("save") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("aggressive") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("cost-save") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("cost_save") == CredentialStrategyHint.LOW

    def test_legacy_default_maps_to_medium(self):
        """Legacy 'default' maps to MEDIUM."""
        assert normalize_strategy_hint("default") == CredentialStrategyHint.MEDIUM
        assert normalize_strategy_hint("balanced") == CredentialStrategyHint.MEDIUM

    def test_legacy_fast_maps_to_medium(self):
        """Legacy 'fast' maps to MEDIUM (preserves latency hint)."""
        assert normalize_strategy_hint("fast") == CredentialStrategyHint.MEDIUM

    def test_legacy_quality_maps_to_high(self):
        """Legacy 'quality' maps to HIGH."""
        assert normalize_strategy_hint("quality") == CredentialStrategyHint.HIGH
        assert normalize_strategy_hint("high-quality") == CredentialStrategyHint.HIGH
        assert normalize_strategy_hint("high_quality") == CredentialStrategyHint.HIGH

    def test_surface_specific_hints_pass_through(self):
        """Surface-specific hints (discussion/embedding/rerank) pass through."""
        assert normalize_strategy_hint("discussion") == CredentialStrategyHint.DISCUSSION
        assert normalize_strategy_hint("embedding") == CredentialStrategyHint.EMBEDDING
        assert normalize_strategy_hint("rerank") == CredentialStrategyHint.RERANK

    def test_none_defaults_to_medium(self):
        """None defaults to MEDIUM."""
        assert normalize_strategy_hint(None) == CredentialStrategyHint.MEDIUM

    def test_unknown_defaults_to_medium(self):
        """Unknown values default to MEDIUM."""
        assert normalize_strategy_hint("unknown") == CredentialStrategyHint.MEDIUM
        assert normalize_strategy_hint("invalid") == CredentialStrategyHint.MEDIUM
        assert normalize_strategy_hint("") == CredentialStrategyHint.MEDIUM

    def test_case_insensitive(self):
        """Mapping is case-insensitive."""
        assert normalize_strategy_hint("LOW") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("Medium") == CredentialStrategyHint.MEDIUM
        assert normalize_strategy_hint("HIGH") == CredentialStrategyHint.HIGH
        assert normalize_strategy_hint("CHEAP") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("Quality") == CredentialStrategyHint.HIGH

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        assert normalize_strategy_hint("  low  ") == CredentialStrategyHint.LOW
        assert normalize_strategy_hint("\tmedium\n") == CredentialStrategyHint.MEDIUM
