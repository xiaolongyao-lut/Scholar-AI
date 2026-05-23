"""Shared AnalysisChain payload model.

Single source of truth for the 6-field reasoning chain shape used across:
- Inspiration pipeline (already shipped via ``inspiration_router``)
- RAG QA pipeline (ACR-020 ~ ACR-024, this slice)
- Multi-agent discussion (ACR-030 ~ ACR-034, future slice)

The schema is intentionally tolerant (missing / wrong-shape fields fall back
to empty strings or empty lists) so an LLM that drops a key cannot break
the response. This mirrors the contract documented in
``docs/plans/specs/analysis-chain-cross-pipeline-spec.md`` Slice 0.
"""

from __future__ import annotations

from pydantic import BaseModel


class AnalysisChainPayload(BaseModel):
    """6-field structured reasoning chain (IRAC + FinCoT compatible).

    Optional + tolerant: missing / wrong-shape fields fall back to empty
    strings or empty lists so the surrounding response is preserved.
    """

    observation: str = ""
    mechanism: str = ""
    evidence: list[str] = []
    boundary: str = ""
    counter_evidence: list[str] = []
    next_action: str = ""


__all__ = ["AnalysisChainPayload"]
