from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

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


CITATION_PATTERN = re.compile(
    r"\[\[(?P<target>[^\]]+)\]\]|"
    r"\[(?P<chunk_id>[a-f0-9]{16})\]"
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
    target = match.group("target")
    if not target:
        return ParsedCitation(raw=raw)
    parts = target.split("#")
    source_id = parts[0].strip()
    chunk_id = parts[1].strip() if len(parts) > 1 else None
    return ParsedCitation(raw=raw, source_id=source_id, chunk_id=chunk_id)


def extract_citations(text: str) -> list[ParsedCitation]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    citations: list[ParsedCitation] = []
    for match in CITATION_PATTERN.finditer(text):
        citations.append(parse_citation(match.group(0)))
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
    citation_positions = {match.start(): match.group(0) for match in CITATION_PATTERN.finditer(body)}
    cited_claims = 0
    for claim in claims:
        claim_start = body.find(claim)
        claim_end = claim_start + len(claim)
        has_citation = any(
            claim_start <= pos < claim_end
            for pos in citation_positions.keys()
        )
        if has_citation:
            cited_claims += 1
        elif mode == ValidationMode.FINAL:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.FAILED,
                    message=f"Claim lacks citation: {claim[:80]}",
                )
            )
    for citation in citations:
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
        metrics={"citations_count": len(citations)},
    )

