"""
Secret-scan wrapper for the evolution candidate write path.

Reuses literature_assistant.core.wiki.evaluation.scan_text_for_secrets so the
detection pattern set stays a single source of truth (wiki citation auditor
already uses it for compiled wiki pages).

Policy (plan §Fail-closed Rules):
    - Any non-zero finding count blocks the write.
    - Scanned fields: title, claim, future_use, source_summary.
    - Findings are surfaced as a short reason string; raw matches are never
      echoed back to the caller (the underlying scanner does not return the
      matched substring either — only kind + line + message).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from wiki.evaluation import scan_text_for_secrets

_SCANNED_FIELDS: Tuple[str, ...] = (
    "title",
    "claim",
    "future_use",
    "source_summary",
)


@dataclass(frozen=True)
class SecretScanVerdict:
    blocked: bool
    findings: int
    reason: str


def scan_candidate_fields(
    *,
    title: str,
    claim: str,
    future_use: str,
    source_summary: str,
) -> SecretScanVerdict:
    """Scan all user-supplied text fields of a candidate.

    Returns SecretScanVerdict.blocked=True if any field contains a secret
    pattern. Caller must persist the candidate with status BLOCKED and
    decision_reason set from `reason`.
    """

    values = {
        "title": title,
        "claim": claim,
        "future_use": future_use,
        "source_summary": source_summary,
    }

    total = 0
    hits: list[str] = []
    for field_name, value in values.items():
        if not value:
            continue
        report = scan_text_for_secrets(value, source=field_name)
        if report.finding_count > 0:
            total += report.finding_count
            kinds = sorted({finding.kind for finding in report.findings})
            hits.append(f"{field_name}({','.join(kinds)})")

    if total == 0:
        return SecretScanVerdict(blocked=False, findings=0, reason="")

    return SecretScanVerdict(
        blocked=True,
        findings=total,
        reason=f"secret_scan: {total} findings in {', '.join(hits)}",
    )


def fields_to_scan() -> Iterable[str]:
    """Names of fields scanned by `scan_candidate_fields` (test introspection)."""

    return _SCANNED_FIELDS
