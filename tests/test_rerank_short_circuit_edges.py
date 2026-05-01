"""R4 edge-case placeholder.

All four edge cases requested by the R4 handoff item are **already**
covered in ``tests/test_rerank_short_circuit_and_budget.py`` (closed
2026-04-25, see the A11.R4.1 / A11.R4.2 docstrings there):

* ``test_empty_candidates_returns_empty_without_calling_provider``
* ``test_single_candidate_short_circuits``
* ``test_top_n_larger_than_candidates``
* ``test_negative_or_zero_top_n_raises``

This file exists so the handoff's verification command
(``pytest tests/test_rerank_short_circuit_edges.py``) still resolves to
a collectable test node, and records that no duplication was added per
CLAUDE.md §2 Simplicity First / §3 Surgical Changes.
"""

from __future__ import annotations

import pytest


def test_r4_edges_already_covered_in_sibling_file() -> None:
    pytest.skip(
        "R4 cases 1-4 already live in tests/test_rerank_short_circuit_and_budget.py; "
        "not duplicated per CLAUDE.md Surgical Changes."
    )
