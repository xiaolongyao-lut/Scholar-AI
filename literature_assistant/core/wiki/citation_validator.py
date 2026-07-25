from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from literature_assistant.core.wiki.source_registry import WikiRegistry


class ValidationMode(str, Enum):
    DRAFT = "draft"
    FINAL = "final"


class ValidationLevel(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True)
class ParsedCitation:
    raw: str
    source_id: str | None = None
    chunk_id: str | None = None
    evidence_ref: str | None = None
    page: str | None = None
    span: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    level: ValidationLevel
    message: str
    line: int | None = None
    citation: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    mode: ValidationMode
    passed: bool
    total_claims: int
    cited_claims: int
    citation_density: float
    issues: list[ValidationIssue]
    metrics: dict[str, Any]


SUPPORTED_EVIDENCE_REF_PREFIXES = (
    "chunk:",
    "source_vault:chunk:",
    "evidence_pack:",
    "wiki:",
)

_EVIDENCE_REF_TOKEN = (
    r"(?:source_vault:chunk|chunk|evidence_pack|wiki):[A-Za-z0-9_./:#-]+"
)

CITATION_PATTERN = re.compile(
    r"\[\[(?P<target>[A-Za-z0-9_./:-]+(?:#[A-Za-z0-9_./:-]+)?)\]\]|"
    r"\[(?P<chunk_id>[a-f0-9]{16})\]|"
    rf"\[(?P<bracket_ref>{_EVIDENCE_REF_TOKEN})\]|"
    rf"(?<![\w:/.-])(?P<bare_ref>{_EVIDENCE_REF_TOKEN})"
)

CLAIM_SENTENCE_PATTERN = re.compile(
    r"(?<!\n)(?<!\n\n)(?<!^)(?<!#)(?<!-)(?<!\*)(?<!\d\.)\s*([A-Z][^.!?]*[.!?])",
    re.MULTILINE
)


def parse_citation(raw: str) -> ParsedCitation:
    if not isinstance(raw, str):
        raise TypeError("raw must be a string")
    match = CITATION_PATTERN.search(raw)
    if not match:
        return ParsedCitation(raw=raw)
    if match.group("chunk_id"):
        return ParsedCitation(raw=raw, chunk_id=match.group("chunk_id"))
    evidence_ref = _clean_evidence_ref(match.group("bracket_ref") or match.group("bare_ref"))
    if evidence_ref is not None:
        return ParsedCitation(raw=raw, evidence_ref=evidence_ref)
    target = match.group("target")
    if not target:
        return ParsedCitation(raw=raw)
    parts = target.split("#", 1)
    source_id = parts[0].strip()
    chunk_id = parts[1].strip() if len(parts) > 1 else None
    return ParsedCitation(raw=raw, source_id=source_id, chunk_id=chunk_id)


def extract_citations(text: str) -> list[ParsedCitation]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    citations: list[ParsedCitation] = []
    for match in CITATION_PATTERN.finditer(text):
        citation = parse_citation(match.group(0))
        if citation.source_id or citation.chunk_id or citation.evidence_ref:
            citations.append(citation)
    return citations


def extract_frontmatter_citations(frontmatter: Mapping[str, Any]) -> list[ParsedCitation]:
    """Return machine-readable evidence refs declared in page frontmatter.

    Generated wiki pages often carry evidence in structured frontmatter rather
    than repeating every chunk id inline. Only explicit evidence-bearing fields
    are treated as citations; relation links and ordinary wiki metadata are not.
    """

    if not isinstance(frontmatter, Mapping):
        raise TypeError("frontmatter must be a mapping")
    raw_refs = frontmatter.get("evidence_refs")
    if raw_refs is None:
        raw_refs = frontmatter.get("references")
    if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes)):
        return []
    citations: list[ParsedCitation] = []
    for raw_ref in raw_refs:
        citation = _citation_from_frontmatter_ref(raw_ref)
        if citation is not None:
            citations.append(citation)
    return citations


def detect_claim_sentences(body: str) -> list[str]:
    if not isinstance(body, str):
        raise TypeError("body must be a string")
    lines = body.split("\n")
    claims: list[str] = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("-") or stripped.startswith("*"):
            continue
        if not stripped:
            continue
        sentences = re.split(r'(?<=[.!?])\s+', stripped)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 10 and sentence[0].isupper():
                claims.append(sentence)
    return claims


def validate_citation_exists(citation: ParsedCitation, registry: WikiRegistry) -> bool:
    if citation.evidence_ref:
        return _is_supported_evidence_ref(citation.evidence_ref)
    if citation.chunk_id:
        return registry.verify_chunk_exists(citation.chunk_id)
    if citation.source_id:
        return registry.get_source(citation.source_id) is not None
    return False


def validate_quote_match(quote: str, chunk_text: str, *, fuzzy: bool = False) -> bool:
    if not isinstance(quote, str) or not isinstance(chunk_text, str):
        raise TypeError("quote and chunk_text must be strings")
    if quote in chunk_text:
        return True
    if fuzzy:
        normalized_quote = " ".join(quote.lower().split())
        normalized_chunk = " ".join(chunk_text.lower().split())
        return normalized_quote in normalized_chunk
    return False


def calculate_citation_density(total_claims: int, cited_claims: int) -> float:
    if total_claims == 0:
        return 1.0
    return cited_claims / total_claims


def validate_page(
    body: str,
    frontmatter: Mapping[str, Any],
    registry: WikiRegistry,
    *,
    mode: ValidationMode = ValidationMode.DRAFT,
) -> ValidationReport:
    if not isinstance(body, str):
        raise TypeError("body must be a string")
    if not isinstance(frontmatter, Mapping):
        raise TypeError("frontmatter must be a mapping")
    issues: list[ValidationIssue] = []
    claims = detect_claim_sentences(body)
    citations = extract_citations(body)
    frontmatter_citations = extract_frontmatter_citations(frontmatter)
    has_page_level_evidence = any(validate_citation_exists(citation, registry) for citation in frontmatter_citations)
    citation_positions = {match.start(): match.group(0) for match in CITATION_PATTERN.finditer(body)}
    cited_claims = 0
    for claim in claims:
        claim_start = body.find(claim)
        claim_end = claim_start + len(claim)
        has_citation = any(
            claim_start <= pos < claim_end
            for pos in citation_positions.keys()
        ) or has_page_level_evidence
        if has_citation:
            cited_claims += 1
        elif mode == ValidationMode.FINAL:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.FAILED,
                    message=f"Claim lacks citation: {claim[:80]}",
                )
            )
    for citation in [*citations, *frontmatter_citations]:
        if not validate_citation_exists(citation, registry):
            level = ValidationLevel.FAILED if mode == ValidationMode.FINAL else ValidationLevel.WARNING
            issues.append(
                ValidationIssue(
                    level=level,
                    message=f"Citation target not found: {citation.raw}",
                    citation=citation.raw,
                )
            )
    density = calculate_citation_density(len(claims), cited_claims)
    passed = all(issue.level != ValidationLevel.FAILED for issue in issues)
    return ValidationReport(
        mode=mode,
        passed=passed,
        total_claims=len(claims),
        cited_claims=cited_claims,
        citation_density=density,
        issues=issues,
        metrics={
            "citations_count": len(citations),
            "frontmatter_citations_count": len(frontmatter_citations),
            "total_citations_count": len(citations) + len(frontmatter_citations),
        },
    )


def _clean_evidence_ref(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip(".,;)")
    return cleaned or None


def _is_supported_evidence_ref(value: str) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = _clean_evidence_ref(value)
    if cleaned is None:
        return False
    return any(
        cleaned.startswith(prefix) and len(cleaned) > len(prefix)
        for prefix in SUPPORTED_EVIDENCE_REF_PREFIXES
    )


def _citation_from_frontmatter_ref(raw_ref: object) -> ParsedCitation | None:
    if isinstance(raw_ref, str):
        citation = parse_citation(raw_ref)
        if citation.source_id or citation.chunk_id or citation.evidence_ref:
            return citation
        evidence_ref = _clean_evidence_ref(raw_ref)
        if evidence_ref is not None and _is_supported_evidence_ref(evidence_ref):
            return ParsedCitation(raw=evidence_ref, evidence_ref=evidence_ref)
        return None
    if not isinstance(raw_ref, Mapping):
        return None

    for key in ("ref_id", "source_vault_ref_id", "evidence_pack_ref", "citation"):
        value = raw_ref.get(key)
        if isinstance(value, str) and _is_supported_evidence_ref(value):
            evidence_ref = _clean_evidence_ref(value)
            return ParsedCitation(raw=value, evidence_ref=evidence_ref)

    source_ref = raw_ref.get("source_ref")
    if isinstance(source_ref, Mapping):
        nested = _citation_from_frontmatter_ref(source_ref)
        if nested is not None:
            return nested

    chunk_id = raw_ref.get("chunk_id")
    if isinstance(chunk_id, str) and chunk_id.strip():
        cleaned_chunk_id = _clean_evidence_ref(chunk_id)
        if cleaned_chunk_id is None:
            return None
        if _is_supported_evidence_ref(cleaned_chunk_id):
            return ParsedCitation(raw=chunk_id, evidence_ref=cleaned_chunk_id)
        material_id = raw_ref.get("material_id")
        if isinstance(material_id, str) and material_id.strip():
            return ParsedCitation(raw=chunk_id, evidence_ref=f"chunk:{cleaned_chunk_id}")
        return ParsedCitation(raw=chunk_id, chunk_id=cleaned_chunk_id)

    material_id = raw_ref.get("material_id")
    if isinstance(material_id, str) and material_id.strip():
        return ParsedCitation(raw=material_id, evidence_ref=f"chunk:{material_id.strip()}")

    source_id = raw_ref.get("source_id")
    if isinstance(source_id, str) and source_id.strip():
        return ParsedCitation(raw=source_id, source_id=source_id.strip())

    return None
