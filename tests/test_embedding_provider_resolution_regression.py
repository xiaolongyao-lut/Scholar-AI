"""E1 regression guard — embedding provider switch.

Handoff: `docs/superpowers/plans/2026-04-25-embedding-rerank-test-handoff.md` §E1.

The four E1 cases (SiliconFlow-only, Jina-only, both-present-prefers-SF with
`EMBEDDING_PROVIDER=jina` override, no-key contract) are already covered by
`tests/test_embedding_provider_resolution.py`. Validity-first probe behaviour
is covered by `tests/test_embedding_key_probe.py`.

This file exists purely as a regression anchor: if the canonical coverage
above is renamed or removed, this test will fail loudly so the E1 contract
is never silently dropped.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent

CANONICAL_PROVIDER_TESTS = TESTS_DIR / "test_embedding_provider_resolution.py"
CANONICAL_PROBE_TESTS = TESTS_DIR / "test_embedding_key_probe.py"

REQUIRED_PROVIDER_CASES = (
    "test_siliconflow_key_resolves_embedding_endpoint",
    "test_jina_only_falls_through_to_jina",
    "test_both_present_prefers_siliconflow_unless_overridden",
    "test_no_key_returns_none_api_key_contract",
)


def test_canonical_provider_resolution_file_exists() -> None:
    assert CANONICAL_PROVIDER_TESTS.is_file(), (
        f"E1 regression anchor broken: {CANONICAL_PROVIDER_TESTS.name} is missing. "
        "Restore the four provider-switch cases before removing this file."
    )


def test_canonical_probe_file_exists() -> None:
    assert CANONICAL_PROBE_TESTS.is_file(), (
        f"E1 regression anchor broken: {CANONICAL_PROBE_TESTS.name} is missing. "
        "Validity-first probe coverage lives there; restore it first."
    )


@pytest.mark.parametrize("case_name", REQUIRED_PROVIDER_CASES)
def test_required_case_present(case_name: str) -> None:
    text = CANONICAL_PROVIDER_TESTS.read_text(encoding="utf-8")
    assert f"def {case_name}(" in text, (
        f"E1 regression anchor broken: {case_name} missing from "
        f"{CANONICAL_PROVIDER_TESTS.name}."
    )
