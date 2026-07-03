# -*- coding: utf-8 -*-
"""Deterministic linter for chunk-store evidence units."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from chunk_hashing import compute_chunk_hashes
from chunk_size_guard import inspect_chunk


CHUNK_EVIDENCE_LINTER_SCHEMA_VERSION = "scholar-ai-chunk-evidence-linter/v1"

ChunkLintSeverity = Literal["error", "warning", "info"]

_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_FRAGMENT_RE = re.compile(
    r"^(?:and|or|but|which|that|therefore|however|while|whereas|because|以及|并且|然而|因此|其中|由于)[,，\s]+",
    re.IGNORECASE,
)
_TRAILING_FRAGMENT_RE = re.compile(r"[,，;；:：]$")


@dataclass(frozen=True)
class ChunkLintIssue:
    """One deterministic issue found in a chunk evidence unit.

    Args:
        code: Stable machine-readable issue code.
        severity: Error blocks indexing; warning permits fallback use.
        chunk_id: Bounded chunk id when the issue is row-specific.
        material_id: Bounded material id when available.
        message: Short remediation target.
        metadata: Non-secret scalar diagnostics for tests and UI surfaces.
    """

    code: str
    severity: ChunkLintSeverity
    chunk_id: str = ""
    material_id: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable issue payload."""

        return {
            "code": self.code,
            "severity": self.severity,
            "chunk_id": self.chunk_id,
            "material_id": self.material_id,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ChunkEvidenceLintReport:
    """Machine-readable lint report for a chunk-store slice."""

    schema_version: str
    chunk_count: int
    error_count: int
    warning_count: int
    passed: bool
    issues: tuple[ChunkLintIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report payload."""

        return {
            "schema_version": self.schema_version,
            "chunk_count": self.chunk_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _bounded_text(value: object, *, max_chars: int = 240) -> str:
    text = str(value or "").strip()
    return text[:max_chars]


def _evidence_text(chunk: Mapping[str, Any]) -> str:
    return _bounded_text(chunk.get("raw_content") or chunk.get("content"), max_chars=200_000)


def _normalized_duplicate_text(chunk: Mapping[str, Any]) -> str:
    text = _evidence_text(chunk).lower()
    return _WHITESPACE_RE.sub(" ", text).strip()


def _coerce_positive_page(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        page = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _chunk_page(chunk: Mapping[str, Any]) -> int | None:
    page = _coerce_positive_page(chunk.get("page"))
    if page is not None:
        return page
    locator = chunk.get("locator")
    if isinstance(locator, Mapping):
        return _coerce_positive_page(locator.get("page"))
    return None


def _has_locator_payload(chunk: Mapping[str, Any]) -> bool:
    if _chunk_page(chunk) is not None:
        return True
    if chunk.get("bbox"):
        return True
    if chunk.get("image_paths"):
        return True
    if _bounded_text(chunk.get("table_csv")):
        return True
    if _bounded_text(chunk.get("equation_latex")):
        return True
    locator = chunk.get("locator")
    return isinstance(locator, Mapping) and bool(locator)


def _chunk_identity(chunk: Mapping[str, Any]) -> tuple[str, str]:
    return _bounded_text(chunk.get("chunk_id")), _bounded_text(chunk.get("material_id"))


class ChunkEvidenceUnitLinter:
    """Validate chunk-store units before derived indexing.

    Args:
        min_content_chars: Minimum evidence-body length before a warning.
        duplicate_min_chars: Minimum normalized content length considered for
            duplicate detection.
    """

    def __init__(self, *, min_content_chars: int = 20, duplicate_min_chars: int = 24) -> None:
        if min_content_chars < 1:
            raise ValueError("min_content_chars must be positive")
        if duplicate_min_chars < 1:
            raise ValueError("duplicate_min_chars must be positive")
        self._min_content_chars = min_content_chars
        self._duplicate_min_chars = duplicate_min_chars

    def lint_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> ChunkEvidenceLintReport:
        """Return a deterministic report for a sequence of chunk mappings.

        Args:
            chunks: Runtime-order chunk dictionaries from one project or
                material slice.

        Returns:
            A report whose issue ordering is stable across runs.

        Raises:
            TypeError: If ``chunks`` is not a sequence of mappings.
        """

        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("chunks must be a sequence of mappings")

        issues: list[ChunkLintIssue] = []
        duplicate_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)

        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, Mapping):
                raise TypeError(f"chunk at index {index} must be a mapping")
            issues.extend(self._lint_single_chunk(index=index, chunk=chunk))
            duplicate_key = _normalized_duplicate_text(chunk)
            if len(duplicate_key) >= self._duplicate_min_chars:
                duplicate_groups[duplicate_key].append(chunk)

        issues.extend(self._duplicate_issues(duplicate_groups))
        issues.sort(key=lambda item: (item.severity, item.code, item.material_id, item.chunk_id, repr(item.metadata)))
        error_count = sum(1 for issue in issues if issue.severity == "error")
        warning_count = sum(1 for issue in issues if issue.severity == "warning")
        return ChunkEvidenceLintReport(
            schema_version=CHUNK_EVIDENCE_LINTER_SCHEMA_VERSION,
            chunk_count=len(chunks),
            error_count=error_count,
            warning_count=warning_count,
            passed=error_count == 0,
            issues=tuple(issues),
        )

    def _lint_single_chunk(self, *, index: int, chunk: Mapping[str, Any]) -> list[ChunkLintIssue]:
        issues: list[ChunkLintIssue] = []
        chunk_id, material_id = _chunk_identity(chunk)
        required_fields = {
            "chunk_id": chunk_id,
            "material_id": material_id,
            "title": _bounded_text(chunk.get("title")),
            "content": _bounded_text(chunk.get("content"), max_chars=200_000),
        }
        for field_name, value in required_fields.items():
            if not value:
                issues.append(
                    ChunkLintIssue(
                        code="missing_required_field",
                        severity="error",
                        chunk_id=chunk_id,
                        material_id=material_id,
                        message=f"Required chunk field is missing: {field_name}",
                        metadata={"field": field_name, "index": index},
                    )
                )

        if _chunk_page(chunk) is None:
            issues.append(
                ChunkLintIssue(
                    code="missing_page_locator",
                    severity="error",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk must carry a positive page locator before derived indexing.",
                    metadata={"index": index},
                )
            )
        if not _has_locator_payload(chunk):
            issues.append(
                ChunkLintIssue(
                    code="missing_locator",
                    severity="warning",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk has no recoverable locator payload.",
                    metadata={"index": index},
                )
            )

        evidence = _evidence_text(chunk)
        if 0 < len(evidence) < self._min_content_chars:
            issues.append(
                ChunkLintIssue(
                    code="short_content",
                    severity="warning",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk evidence body is too short for reliable retrieval.",
                    metadata={"char_count": len(evidence), "index": index},
                )
            )
        if _LEADING_FRAGMENT_RE.search(evidence):
            issues.append(
                ChunkLintIssue(
                    code="possible_leading_fragment",
                    severity="warning",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk appears to start mid-sentence.",
                    metadata={"index": index},
                )
            )
        if _TRAILING_FRAGMENT_RE.search(evidence.strip()):
            issues.append(
                ChunkLintIssue(
                    code="possible_trailing_fragment",
                    severity="warning",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk appears to end mid-sentence.",
                    metadata={"index": index},
                )
            )

        metrics = inspect_chunk(dict(chunk))
        if bool(metrics.get("is_oversize")):
            issues.append(
                ChunkLintIssue(
                    code="oversize_chunk",
                    severity="error",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk exceeds hard embedding safety limits.",
                    metadata={
                        "char_count": metrics.get("char_count"),
                        "token_count": metrics.get("token_count"),
                        "max_chars": metrics.get("max_chars"),
                        "max_tokens": metrics.get("max_tokens"),
                        "index": index,
                    },
                )
            )

        try:
            compute_chunk_hashes(chunk, material_id_hint=material_id or None)
        except (TypeError, ValueError) as exc:
            issues.append(
                ChunkLintIssue(
                    code="hash_unavailable",
                    severity="error",
                    chunk_id=chunk_id,
                    material_id=material_id,
                    message="Chunk cannot produce deterministic truth hashes.",
                    metadata={"error": str(exc)[:240], "index": index},
                )
            )
        return issues

    def _duplicate_issues(self, groups: Mapping[str, list[Mapping[str, Any]]]) -> list[ChunkLintIssue]:
        issues: list[ChunkLintIssue] = []
        for duplicate_key, group in groups.items():
            if len(group) < 2:
                continue
            duplicate_ids = [_chunk_identity(chunk)[0] for chunk in group]
            for chunk in group:
                chunk_id, material_id = _chunk_identity(chunk)
                issues.append(
                    ChunkLintIssue(
                        code="duplicate_content",
                        severity="warning",
                        chunk_id=chunk_id,
                        material_id=material_id,
                        message="Chunk evidence text duplicates another chunk.",
                        metadata={
                            "duplicate_count": len(group),
                            "duplicate_chunk_ids": sorted(item for item in duplicate_ids if item)[:12],
                            "content_fingerprint": duplicate_key[:80],
                        },
                    )
                )
        return issues
