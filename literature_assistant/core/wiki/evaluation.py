from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from literature_assistant.core.wiki.citation_validator import detect_claim_sentences, extract_citations


AuditLevel = Literal["passed", "warning", "failed"]


@dataclass(frozen=True)
class WikiEvalCase:
    """One zero-cost wiki evaluation case.

    The case shape mirrors common RAG evaluation fields while keeping local
    source IDs separate from optional answer/context text to avoid accidental
    leakage in manifests.
    """

    case_id: str
    query: str
    expected_source_ids: tuple[str, ...] = ()
    expected_chunk_ids: tuple[str, ...] = ()
    wiki_context_source_ids: tuple[str, ...] = ()
    wiki_context_chunk_ids: tuple[str, ...] = ()
    raw_context_source_ids: tuple[str, ...] = ()
    raw_context_chunk_ids: tuple[str, ...] = ()
    answer_page_path: str | None = None
    answer: str | None = None
    ground_truth: str | None = None
    contexts: tuple[str, ...] = ()

    @property
    def expected_ids(self) -> tuple[str, ...]:
        """Return de-duplicated expected source and chunk identifiers."""

        return _dedupe_preserve_order((*self.expected_source_ids, *self.expected_chunk_ids))

    @property
    def wiki_context_ids(self) -> tuple[str, ...]:
        """Return de-duplicated wiki-first retrieval identifiers."""

        return _dedupe_preserve_order((*self.wiki_context_source_ids, *self.wiki_context_chunk_ids))

    @property
    def raw_context_ids(self) -> tuple[str, ...]:
        """Return de-duplicated raw RAG retrieval identifiers."""

        return _dedupe_preserve_order((*self.raw_context_source_ids, *self.raw_context_chunk_ids))


@dataclass(frozen=True)
class WikiEvalManifest:
    """Versioned zero-cost wiki evaluation manifest."""

    schema_version: int
    cases: tuple[WikiEvalCase, ...]
    description: str = ""
    metrics: tuple[str, ...] = ("hit_rate", "mrr", "precision", "recall")


@dataclass(frozen=True)
class RetrievalMetricRow:
    """Per-case retrieval metrics computed from expected and retrieved IDs."""

    case_id: str
    expected_count: int
    retrieved_count: int
    hit_rate: float
    mrr: float
    precision: float
    recall: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable metric row."""

        return {
            "case_id": self.case_id,
            "expected_count": self.expected_count,
            "retrieved_count": self.retrieved_count,
            "hit_rate": self.hit_rate,
            "mrr": self.mrr,
            "precision": self.precision,
            "recall": self.recall,
        }


@dataclass(frozen=True)
class RetrievalComparisonReport:
    """Aggregate raw-vs-wiki retrieval comparison report."""

    case_count: int
    top_k: int
    wiki: dict[str, float]
    raw: dict[str, float]
    per_case: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable comparison report."""

        return {
            "case_count": self.case_count,
            "top_k": self.top_k,
            "wiki": dict(self.wiki),
            "raw": dict(self.raw),
            "per_case": list(self.per_case),
        }


@dataclass(frozen=True)
class CitationAuditPageResult:
    """Citation quality result for a single wiki page."""

    page_path: str
    status: str
    level: AuditLevel
    citation_count: int
    evidence_ref_count: int
    total_claims: int
    cited_claims: int
    citation_density: float
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable page audit result."""

        return {
            "page_path": self.page_path,
            "status": self.status,
            "level": self.level,
            "citation_count": self.citation_count,
            "evidence_ref_count": self.evidence_ref_count,
            "total_claims": self.total_claims,
            "cited_claims": self.cited_claims,
            "citation_density": self.citation_density,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class CitationAuditReport:
    """Aggregate citation audit report for wiki pages."""

    page_count: int
    passed_count: int
    warning_count: int
    failed_count: int
    average_citation_density: float
    pages: tuple[CitationAuditPageResult, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable citation audit report."""

        return {
            "page_count": self.page_count,
            "passed_count": self.passed_count,
            "warning_count": self.warning_count,
            "failed_count": self.failed_count,
            "average_citation_density": self.average_citation_density,
            "pages": [page.to_dict() for page in self.pages],
        }


@dataclass(frozen=True)
class SecretScanFinding:
    """Public-safe finding for a possible secret or private path."""

    source: str
    line: int
    kind: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable finding without raw secret snippets."""

        return {
            "source": self.source,
            "line": self.line,
            "kind": self.kind,
            "message": self.message,
        }


@dataclass(frozen=True)
class SecretScanReport:
    """No-secret scan result for eval manifests and runtime traces."""

    source_count: int
    finding_count: int
    findings: tuple[SecretScanFinding, ...]

    @property
    def passed(self) -> bool:
        """Return True when no secret-like findings were detected."""

        return self.finding_count == 0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable no-secret scan report."""

        return {
            "source_count": self.source_count,
            "finding_count": self.finding_count,
            "passed": self.passed,
            "findings": [finding.to_dict() for finding in self.findings],
        }


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "authorization_bearer",
        re.compile(r"(?i)\bauthorization\b\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._~+/=-]{10,}"),
        "authorization bearer credential must not be stored in eval artifacts",
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        "bearer token must not be stored in eval artifacts",
    ),
    (
        "openai_style_key",
        re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{18,}\b"),
        "API key-like value must not be stored in eval artifacts",
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "cloud access key-like value must not be stored in eval artifacts",
    ),
    (
        "named_secret_value",
        re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}"),
        "named secret field appears to contain a raw value",
    ),
    (
        "windows_user_path",
        re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\r\n]+\\"),
        "private Windows user path must not be stored in public eval artifacts",
    ),
)


def load_wiki_eval_manifest(path: Path) -> WikiEvalManifest:
    """Load and validate a zero-cost wiki evaluation manifest.

    Args:
        path: JSON file containing ``schema_version`` and ``cases``.

    Raises:
        TypeError: If the top-level shape or fields are invalid.
        ValueError: If required values are empty.
        FileNotFoundError: If the manifest path does not exist.
    """

    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(str(manifest_path))
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise TypeError("wiki eval manifest must be a JSON object")

    schema_version = raw.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError("schema_version must be a positive integer")

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases must be a non-empty list")

    cases = tuple(_parse_eval_case(item, index) for index, item in enumerate(raw_cases))
    description = _optional_string(raw.get("description"), "description") or ""
    metrics = _string_tuple(raw.get("metrics", ("hit_rate", "mrr", "precision", "recall")), "metrics")
    return WikiEvalManifest(
        schema_version=schema_version,
        description=description,
        metrics=metrics,
        cases=cases,
    )


def compute_retrieval_metrics(
    case_id: str,
    expected_ids: Sequence[str],
    retrieved_ids: Sequence[str],
    *,
    top_k: int = 10,
) -> RetrievalMetricRow:
    """Compute deterministic hit-rate, MRR, precision, and recall for one case."""

    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must be a non-empty string")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    expected = _dedupe_preserve_order(expected_ids)
    if not expected:
        raise ValueError("expected_ids cannot be empty")
    retrieved = _dedupe_preserve_order(retrieved_ids)[:top_k]
    expected_set = set(expected)
    hit_positions = [index + 1 for index, value in enumerate(retrieved) if value in expected_set]
    hit_count = len(hit_positions)
    hit_rate = 1.0 if hit_positions else 0.0
    mrr = 1.0 / hit_positions[0] if hit_positions else 0.0
    precision = hit_count / len(retrieved) if retrieved else 0.0
    recall = hit_count / len(expected)
    return RetrievalMetricRow(
        case_id=case_id.strip(),
        expected_count=len(expected),
        retrieved_count=len(retrieved),
        hit_rate=round(hit_rate, 6),
        mrr=round(mrr, 6),
        precision=round(precision, 6),
        recall=round(recall, 6),
    )


def compare_wiki_vs_raw_retrieval(manifest: WikiEvalManifest, *, top_k: int = 10) -> RetrievalComparisonReport:
    """Compare wiki-first and raw RAG retrieval IDs without model calls."""

    if not isinstance(manifest, WikiEvalManifest):
        raise TypeError("manifest must be a WikiEvalManifest")
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    wiki_rows: list[RetrievalMetricRow] = []
    raw_rows: list[RetrievalMetricRow] = []
    per_case: list[dict[str, object]] = []
    for case in manifest.cases:
        if not case.expected_ids:
            continue
        wiki_row = compute_retrieval_metrics(case.case_id, case.expected_ids, case.wiki_context_ids, top_k=top_k)
        raw_row = compute_retrieval_metrics(case.case_id, case.expected_ids, case.raw_context_ids, top_k=top_k)
        wiki_rows.append(wiki_row)
        raw_rows.append(raw_row)
        per_case.append({"case_id": case.case_id, "wiki": wiki_row.to_dict(), "raw": raw_row.to_dict()})

    if not wiki_rows:
        raise ValueError("manifest has no cases with expected IDs")

    return RetrievalComparisonReport(
        case_count=len(wiki_rows),
        top_k=top_k,
        wiki=_aggregate_metric_rows(wiki_rows),
        raw=_aggregate_metric_rows(raw_rows),
        per_case=tuple(per_case),
    )


def audit_wiki_page_text(page_path: str, text: str) -> CitationAuditPageResult:
    """Audit a single rendered wiki markdown page for citation quality."""

    if not isinstance(page_path, str) or not page_path.strip():
        raise ValueError("page_path must be a non-empty string")
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    frontmatter, body, parse_issues = parse_rendered_wiki_page(text)
    status = str(frontmatter.get("status") or "draft").strip().lower() or "draft"
    citations = extract_citations(body)
    evidence_refs = _evidence_refs_from_frontmatter(frontmatter)
    claims = detect_claim_sentences(body)
    cited_claims = _count_cited_claims(body, claims)
    density = round(cited_claims / len(claims), 6) if claims else 1.0

    issues = list(parse_issues)
    if not body.strip():
        issues.append("failed: page body is empty")
    if citations:
        malformed = [citation.raw for citation in citations if not citation.source_id and not citation.chunk_id]
        if malformed:
            issues.append("warning: malformed citation target")
    else:
        level_prefix = "failed" if status == "final" else "warning"
        issues.append(f"{level_prefix}: page has no citations")
    if evidence_refs is None:
        issues.append("warning: evidence_refs is not a list")
        evidence_ref_count = 0
    else:
        evidence_ref_count = len(evidence_refs)
        for evidence_ref in evidence_refs:
            if not _is_valid_evidence_ref(evidence_ref):
                issues.append("warning: evidence_ref lacks source_id/chunk_id or quote/text")
                break
    if status == "final" and evidence_ref_count == 0:
        issues.append("failed: final page has no evidence_refs")

    level = _audit_level(issues)
    return CitationAuditPageResult(
        page_path=page_path.strip().replace("\\", "/"),
        status=status,
        level=level,
        citation_count=len(citations),
        evidence_ref_count=evidence_ref_count,
        total_claims=len(claims),
        cited_claims=cited_claims,
        citation_density=density,
        issues=tuple(issues),
    )


def audit_wiki_pages(page_root: Path, page_paths: Sequence[Path] | None = None) -> CitationAuditReport:
    """Audit rendered wiki markdown pages under ``page_root`` without writes."""

    root = Path(page_root)
    if not root.exists():
        return CitationAuditReport(0, 0, 0, 0, 1.0, ())
    if not root.is_dir():
        raise ValueError("page_root must be a directory")

    relative_paths = tuple(page_paths) if page_paths is not None else tuple(sorted(path.relative_to(root) for path in root.rglob("*.md")))
    results: list[CitationAuditPageResult] = []
    for relative_path in relative_paths:
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise ValueError("page_paths must stay inside page_root")
        page_file = root / relative_path
        if not page_file.exists():
            results.append(
                CitationAuditPageResult(
                    page_path=Path(relative_path).as_posix(),
                    status="missing",
                    level="failed",
                    citation_count=0,
                    evidence_ref_count=0,
                    total_claims=0,
                    cited_claims=0,
                    citation_density=0.0,
                    issues=("failed: page file does not exist",),
                )
            )
            continue
        results.append(audit_wiki_page_text(Path(relative_path).as_posix(), page_file.read_text(encoding="utf-8")))

    return _build_citation_audit_report(results)


def scan_text_for_secrets(text: str, *, source: str = "<memory>") -> SecretScanReport:
    """Scan text for raw secrets and private paths without echoing matches."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")

    findings: list[SecretScanFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern, message in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    SecretScanFinding(
                        source=source.strip(),
                        line=line_number,
                        kind=kind,
                        message=message,
                    )
                )
    return SecretScanReport(source_count=1, finding_count=len(findings), findings=tuple(findings))


def scan_paths_for_secrets(paths: Sequence[Path]) -> SecretScanReport:
    """Scan files for raw secrets and private paths without writing output."""

    if not isinstance(paths, Sequence):
        raise TypeError("paths must be a sequence of Path values")
    findings: list[SecretScanFinding] = []
    source_count = 0
    for path in paths:
        candidate = Path(path)
        if not candidate.exists():
            raise FileNotFoundError(str(candidate))
        if candidate.is_dir():
            raise ValueError("scan_paths_for_secrets expects files, not directories")
        source_count += 1
        report = scan_text_for_secrets(candidate.read_text(encoding="utf-8"), source=candidate.as_posix())
        findings.extend(report.findings)
    return SecretScanReport(source_count=source_count, finding_count=len(findings), findings=tuple(findings))


def parse_rendered_wiki_page(text: str) -> tuple[dict[str, object], str, tuple[str, ...]]:
    """Parse the current JSON-frontmatter wiki page format."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not text.startswith("---json\n"):
        return {}, text, ("warning: page has no JSON frontmatter",)
    frontmatter_end = text.find("\n---\n", len("---json\n"))
    if frontmatter_end == -1:
        return {}, text, ("failed: JSON frontmatter is not closed",)
    raw_frontmatter = text[len("---json\n") : frontmatter_end]
    body = text[frontmatter_end + len("\n---\n") :].strip()
    try:
        frontmatter = json.loads(raw_frontmatter)
    except json.JSONDecodeError:
        return {}, body, ("failed: JSON frontmatter is invalid",)
    if not isinstance(frontmatter, dict):
        return {}, body, ("failed: JSON frontmatter is not an object",)
    return frontmatter, body, ()


def _parse_eval_case(raw: object, index: int) -> WikiEvalCase:
    if not isinstance(raw, Mapping):
        raise TypeError(f"cases[{index}] must be an object")
    case_id = _required_string(raw.get("case_id"), f"cases[{index}].case_id")
    query = _required_string(raw.get("query"), f"cases[{index}].query")
    return WikiEvalCase(
        case_id=case_id,
        query=query,
        expected_source_ids=_string_tuple(raw.get("expected_source_ids", ()), f"cases[{index}].expected_source_ids"),
        expected_chunk_ids=_string_tuple(raw.get("expected_chunk_ids", ()), f"cases[{index}].expected_chunk_ids"),
        wiki_context_source_ids=_string_tuple(raw.get("wiki_context_source_ids", ()), f"cases[{index}].wiki_context_source_ids"),
        wiki_context_chunk_ids=_string_tuple(raw.get("wiki_context_chunk_ids", ()), f"cases[{index}].wiki_context_chunk_ids"),
        raw_context_source_ids=_string_tuple(raw.get("raw_context_source_ids", ()), f"cases[{index}].raw_context_source_ids"),
        raw_context_chunk_ids=_string_tuple(raw.get("raw_context_chunk_ids", ()), f"cases[{index}].raw_context_chunk_ids"),
        answer_page_path=_optional_string(raw.get("answer_page_path"), f"cases[{index}].answer_page_path"),
        answer=_optional_string(raw.get("answer"), f"cases[{index}].answer"),
        ground_truth=_optional_string(raw.get("ground_truth"), f"cases[{index}].ground_truth"),
        contexts=_string_tuple(raw.get("contexts", ()), f"cases[{index}].contexts"),
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string when provided")
    text = value.strip()
    return text or None


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a list of strings")
    strings: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        strings.append(item.strip())
    return _dedupe_preserve_order(strings)


def _dedupe_preserve_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("identifier values must be strings")
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _aggregate_metric_rows(rows: Sequence[RetrievalMetricRow]) -> dict[str, float]:
    if not rows:
        return {"hit_rate": 0.0, "mrr": 0.0, "precision": 0.0, "recall": 0.0}
    return {
        "hit_rate": round(sum(row.hit_rate for row in rows) / len(rows), 6),
        "mrr": round(sum(row.mrr for row in rows) / len(rows), 6),
        "precision": round(sum(row.precision for row in rows) / len(rows), 6),
        "recall": round(sum(row.recall for row in rows) / len(rows), 6),
    }


def _evidence_refs_from_frontmatter(frontmatter: Mapping[str, object]) -> list[object] | None:
    raw = frontmatter.get("evidence_refs")
    if raw is None:
        raw = frontmatter.get("references")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    return list(raw)


def _is_valid_evidence_ref(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    has_target = bool(str(value.get("source_id") or value.get("chunk_id") or value.get("material_id") or "").strip())
    has_quote = bool(str(value.get("quote") or value.get("text") or value.get("compressed_text") or "").strip())
    return has_target and has_quote


def _count_cited_claims(body: str, claims: Sequence[str]) -> int:
    citation_positions = {match.start() for match in _citation_matches(body)}
    cited_claims = 0
    for claim in claims:
        claim_start = body.find(claim)
        if claim_start < 0:
            continue
        claim_end = claim_start + len(claim)
        if any(claim_start <= position < claim_end for position in citation_positions):
            cited_claims += 1
    return cited_claims


def _citation_matches(body: str) -> Iterable[Any]:
    from literature_assistant.core.wiki.citation_validator import CITATION_PATTERN

    return CITATION_PATTERN.finditer(body)


def _audit_level(issues: Sequence[str]) -> AuditLevel:
    if any(issue.startswith("failed:") for issue in issues):
        return "failed"
    if issues:
        return "warning"
    return "passed"


def _build_citation_audit_report(results: Sequence[CitationAuditPageResult]) -> CitationAuditReport:
    page_count = len(results)
    passed_count = sum(1 for result in results if result.level == "passed")
    warning_count = sum(1 for result in results if result.level == "warning")
    failed_count = sum(1 for result in results if result.level == "failed")
    average_density = round(sum(result.citation_density for result in results) / page_count, 6) if page_count else 1.0
    return CitationAuditReport(
        page_count=page_count,
        passed_count=passed_count,
        warning_count=warning_count,
        failed_count=failed_count,
        average_citation_density=average_density,
        pages=tuple(results),
    )
