from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from literature_assistant.core.wiki.source_registry import WikiRegistry


@dataclass(frozen=True)
class EvidenceImportCandidate:
    """One evidence reference that could be imported into the wiki registry.

    The candidate is intentionally report-only. It keeps enough identifiers to
    let a later approved importer register sources/chunks without exposing full
    source text or mutating the registry during migration planning.
    """

    source_id: str
    chunk_id: str
    material_id: str
    title: str
    source_type: str
    has_text: bool
    text_length: int
    page: str | None = None
    source_hint: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "material_id": self.material_id,
            "title": self.title,
            "source_type": self.source_type,
            "has_text": self.has_text,
            "text_length": self.text_length,
            "page": self.page,
            "source_hint": self.source_hint,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class EvidenceMigrationDryRunReport:
    """Machine-readable dry-run plan for evidence_refs -> wiki registry migration."""

    ok: bool
    would_write: bool
    candidate_count: int
    duplicate_count: int
    skipped_count: int
    already_registered_count: int
    candidates: tuple[EvidenceImportCandidate, ...]
    skipped: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "would_write": self.would_write,
            "candidate_count": self.candidate_count,
            "duplicate_count": self.duplicate_count,
            "skipped_count": self.skipped_count,
            "already_registered_count": self.already_registered_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "metadata": self.metadata,
        }


def evidence_refs_migration_dry_run(
    evidence_refs: Iterable[Mapping[str, Any]],
    *,
    registry: WikiRegistry | None = None,
    source_type: str = "rag_evidence",
    max_candidates: int = 500,
) -> EvidenceMigrationDryRunReport:
    """Plan a read-only migration from RAG evidence references to wiki registry.

    Args:
        evidence_refs: Iterable of EvidenceReference-shaped mappings.
        registry: Optional wiki registry used only to count already registered
            chunks. The function never writes to it.
        source_type: Registry source type assigned to import candidates.
        max_candidates: Hard cap that prevents accidental huge reports.

    Returns:
        A dry-run report with ``would_write=False`` and sanitized candidates.

    Raises:
        TypeError: If evidence_refs or registry has the wrong shape.
        ValueError: If source_type or max_candidates is invalid.
    """

    if isinstance(evidence_refs, (str, bytes)) or not isinstance(evidence_refs, Iterable):
        raise TypeError("evidence_refs must be an iterable of mappings")
    if registry is not None and not isinstance(registry, WikiRegistry):
        raise TypeError("registry must be a WikiRegistry when provided")
    normalized_source_type = source_type.strip().lower()
    if not normalized_source_type:
        raise ValueError("source_type must be a non-empty string")
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")

    candidates: list[EvidenceImportCandidate] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    duplicate_count = 0
    already_registered_count = 0

    for index, raw_ref in enumerate(evidence_refs):
        if len(candidates) >= max_candidates:
            warnings.append(f"candidate limit reached: max_candidates={max_candidates}")
            skipped.append({"index": index, "reason": "candidate_limit_reached"})
            continue
        if not isinstance(raw_ref, Mapping):
            skipped.append({"index": index, "reason": "not_a_mapping", "type": type(raw_ref).__name__})
            continue
        candidate = _candidate_from_evidence_ref(raw_ref, index=index, source_type=normalized_source_type)
        if candidate is None:
            skipped.append({"index": index, "reason": "missing_chunk_or_material_id"})
            continue
        key = (candidate.source_id, candidate.chunk_id)
        if key in seen_keys:
            duplicate_count += 1
            skipped.append({"index": index, "reason": "duplicate", "source_id": candidate.source_id, "chunk_id": candidate.chunk_id})
            continue
        seen_keys.add(key)
        if registry is not None and registry.verify_chunk_exists(candidate.chunk_id):
            already_registered_count += 1
        candidates.append(candidate)

    return EvidenceMigrationDryRunReport(
        ok=not warnings,
        would_write=False,
        candidate_count=len(candidates),
        duplicate_count=duplicate_count,
        skipped_count=len(skipped),
        already_registered_count=already_registered_count,
        candidates=tuple(candidates),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
        metadata={
            "source_type": normalized_source_type,
            "max_candidates": max_candidates,
            "registry_checked": registry is not None,
        },
    )


def evidence_refs_migration_dry_run_from_jsonl(
    input_path: Path,
    *,
    registry: WikiRegistry | None = None,
    source_type: str = "rag_evidence",
    max_candidates: int = 500,
) -> EvidenceMigrationDryRunReport:
    """Read EvidenceReference-shaped JSONL and return a no-write migration report.

    Each line may either be one evidence reference or an object containing an
    ``evidence_refs`` list. Invalid JSON lines are skipped with line numbers.
    """

    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"evidence refs input not found: {path}")
    if not path.is_file():
        raise ValueError("input_path must be a file")

    evidence_refs: list[Mapping[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            skipped.append({"line": line_number, "reason": "invalid_json", "message": exc.msg})
            continue
        evidence_refs.extend(_evidence_refs_from_payload(payload, line_number=line_number, skipped=skipped))

    report = evidence_refs_migration_dry_run(
        evidence_refs,
        registry=registry,
        source_type=source_type,
        max_candidates=max_candidates,
    )
    if not skipped:
        return report
    return EvidenceMigrationDryRunReport(
        ok=False,
        would_write=report.would_write,
        candidate_count=report.candidate_count,
        duplicate_count=report.duplicate_count,
        skipped_count=report.skipped_count + len(skipped),
        already_registered_count=report.already_registered_count,
        candidates=report.candidates,
        skipped=tuple((*report.skipped, *skipped)),
        warnings=tuple((*report.warnings, "input contained skipped JSONL records")),
        metadata=report.metadata,
    )


def _candidate_from_evidence_ref(
    ref: Mapping[str, Any],
    *,
    index: int,
    source_type: str,
) -> EvidenceImportCandidate | None:
    chunk_id = _clean_text(ref.get("chunk_id"))
    material_id = _clean_text(ref.get("material_id") or ref.get("source_id"))
    if not chunk_id and not material_id:
        return None
    if not chunk_id:
        chunk_id = f"{material_id}::unresolved"
    if not material_id:
        material_id = f"material-for-{chunk_id}"

    title = _clean_text(ref.get("title") or ref.get("source_label") or ref.get("source") or material_id)
    text = _clean_text(ref.get("text") or ref.get("compressed_text") or ref.get("content"))
    quote = _clean_text(ref.get("quote"))
    source_hint = _clean_text(ref.get("source_hint") or ref.get("source"))
    page = _clean_text(ref.get("page"))
    warnings: list[str] = []
    if not text and not quote:
        warnings.append("missing_text_or_quote")
    if chunk_id.endswith("::unresolved"):
        warnings.append("missing_chunk_id")

    return EvidenceImportCandidate(
        source_id=f"{source_type}:{_registry_token(material_id)}",
        chunk_id=chunk_id,
        material_id=material_id,
        title=title or f"Evidence {index + 1}",
        source_type=source_type,
        has_text=bool(text or quote),
        text_length=len(text or quote),
        page=page,
        source_hint=source_hint,
        warnings=tuple(warnings),
    )


def _evidence_refs_from_payload(
    payload: Any,
    *,
    line_number: int,
    skipped: list[dict[str, Any]],
) -> Sequence[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        nested = payload.get("evidence_refs")
        if isinstance(nested, list):
            refs = []
            for item_index, item in enumerate(nested):
                if isinstance(item, Mapping):
                    refs.append(item)
                else:
                    skipped.append({"line": line_number, "index": item_index, "reason": "nested_ref_not_a_mapping"})
            return refs
        return (payload,)
    skipped.append({"line": line_number, "reason": "payload_not_a_mapping"})
    return ()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _registry_token(value: str) -> str:
    token_chars: list[str] = []
    for char in value.strip().lower():
        if char.isalnum():
            token_chars.append(char)
        elif char in {" ", "-", "_", ".", "/", "\\", ":"}:
            token_chars.append("-")
    token = "-".join(part for part in "".join(token_chars).split("-") if part)
    return token[:96] or "unknown"
