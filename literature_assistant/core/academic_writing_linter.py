# -*- coding: utf-8 -*-
"""Deterministic academic-writing quality linting."""

from __future__ import annotations

import html as html_lib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


AcademicLintContentType = Literal["review", "introduction", "manuscript", "section"]
AcademicLintLanguage = Literal["zh", "en", "auto"]
AcademicLintSeverity = Literal["error", "warning", "info"]
AcademicLintInvocationSurface = Literal["direct_api", "external_mcp", "api_chat_local_tools", "unknown"]


class AcademicWritingLintIssue(BaseModel):
    """One deterministic writing-quality finding.

    Args:
        code: Stable machine-readable issue code.
        severity: Impact level used for pass/fail and score penalties.
        message: Human-readable remediation target.
        span: Optional compact location hint; offsets refer to normalized text.
    """

    code: str = Field(min_length=1)
    severity: AcademicLintSeverity
    message: str = Field(min_length=1)
    span: dict[str, int | str] | None = None


class AcademicWritingLintMetrics(BaseModel):
    """Observable writing metrics used by the linter response."""

    char_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    section_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    evidence_ref_count: int = Field(ge=0)
    figure_ref_count: int = Field(ge=0)
    table_ref_count: int = Field(ge=0)
    equation_ref_count: int = Field(ge=0)
    academic_connector_count: int = Field(ge=0)
    conversational_phrase_count: int = Field(ge=0)


class AcademicWritingAuditContext(BaseModel):
    """Caller-supplied provenance for writing-quality audit.

    Args:
        invocation_surface: Stable caller class. Unknown custom values are
            rejected to keep audit dashboards machine-filterable.
        agent_host: Optional external agent or chat surface identifier.
        source: Optional workflow source label.
        project_id: Optional Literature Assistant project id.
        tool_chain: Ordered high-level steps used before linting.
        used_mcp_tools: Tool names already invoked by the agent/tool loop.
        retrieval_diagnostics: Prior retrieval visibility payload, typically
            copied from an evidence-pack response.
        reasoning_trace: Safe, user-visible reasoning summary. This is not
            private model chain-of-thought.
    """

    invocation_surface: AcademicLintInvocationSurface = "direct_api"
    agent_host: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=80)
    project_id: str | None = Field(default=None, max_length=128)
    tool_chain: list[str] = Field(default_factory=list, max_length=32)
    used_mcp_tools: list[str] = Field(default_factory=list, max_length=64)
    retrieval_diagnostics: dict[str, Any] | None = None
    reasoning_trace: list[str] = Field(default_factory=list, max_length=16)


class AcademicWritingAuditTrail(BaseModel):
    """Machine-readable audit trail for one writing-quality gate run."""

    invocation_surface: AcademicLintInvocationSurface
    agent_mediated: bool
    mcp_tool_calls_used: bool
    agent_host: str | None = None
    source: str | None = None
    project_id: str | None = None
    tool_chain: list[str] = Field(default_factory=list)
    used_mcp_tools: list[str] = Field(default_factory=list)
    style_profile: str | None = None
    evidence_ref_count: int = Field(ge=0)
    evidence_pack_ref_count: int = Field(ge=0)
    retrieval_diagnostics: dict[str, Any] | None = None
    reasoning_trace: list[str] = Field(default_factory=list)
    quality_gate: Literal["passed", "failed"]
    checks: list[str] = Field(default_factory=list)
    disclosure_required: bool
    disclosure_note: str | None = None


class AcademicWritingLintRequest(BaseModel):
    """Input for deterministic academic writing lint.

    Args:
        text: Plain Markdown/text manuscript content.
        html: Optional HTML manuscript content; headings/tables/captions are
            recognized before tags are stripped.
        content_type: Expected scholarly unit being checked.
        language: ``auto`` derives Chinese/English from Unicode/script counts.
        required_sections: Section labels that must appear as headings or
            standalone section labels.
        require_evidence_refs: Whether citation/evidence anchors are required.
        require_figure_table_formula_refs: Whether figure, table, and equation
            references must all be present.
        style_profile: Optional journal/export style profile expectation.
        audit_context: Optional caller provenance used to distinguish direct
            API checks from MCP/agent-mediated writing checks.
    """

    text: str | None = Field(default=None, max_length=300_000)
    html: str | None = Field(default=None, max_length=300_000)
    content_type: AcademicLintContentType = "manuscript"
    language: AcademicLintLanguage = "auto"
    required_sections: list[str] = Field(default_factory=list, max_length=32)
    require_evidence_refs: bool = True
    require_figure_table_formula_refs: bool = False
    style_profile: str | None = Field(default=None, max_length=80)
    audit_context: AcademicWritingAuditContext | None = None


class AcademicWritingLintResponse(BaseModel):
    """Deterministic academic writing quality result."""

    passed: bool
    score: float = Field(ge=0.0, le=100.0)
    content_type: AcademicLintContentType
    language: Literal["zh", "en"]
    metrics: AcademicWritingLintMetrics
    audit: AcademicWritingAuditTrail
    issues: list[AcademicWritingLintIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


_HTML_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_HTML_TABLE_RE = re.compile(r"<table\b|<tr\b|<td\b|<th\b", re.IGNORECASE)
_HTML_FIGURE_RE = re.compile(r"<figcaption\b|<figure\b|<img\b", re.IGNORECASE)
_HTML_EQUATION_RE = re.compile(r"data-formula\b|class=[\"'][^\"']*(?:math|equation|formula)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SECTION_MARKDOWN_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_SECTION_STANDALONE_RE = re.compile(
    r"^\s*(综述|文献综述|引言|绪论|Introduction|Literature Review|Review|Discussion|Methods?|Results?)\s*[:：]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CITATION_PATTERNS = (
    re.compile(r"\[(?:\d{1,3})(?:\s*[-,]\s*\d{1,3})*\]"),
    re.compile(r"\[\^cite:[^\]]+\]"),
    re.compile(r"\[chunk:[^\]]+\]"),
    re.compile(r"\[evidence_pack:[^\]]+\]"),
    re.compile(r"\([A-Z][A-Za-z\-]+(?:\s+et\s+al\.)?,?\s+(?:19|20)\d{2}[a-z]?\)"),
    re.compile(r"（[^）]{1,40}(?:19|20)\d{2}[a-z]?）"),
)
_EVIDENCE_REF_RE = re.compile(r"\[(?:chunk|evidence_pack):[^\]]+\]|\[\^cite:[^\]]+\]")
_EVIDENCE_PACK_REF_RE = re.compile(r"evidence_pack:[^\s\]\),;，。]+")
_FIGURE_RE = re.compile(
    r"(?:图\s*\d+|Figure\s*\d+|Fig\.\s*\d+|SEQ\s+Figure|REF\s+litassist_figure_\d+|<figcaption\b|<figure\b|<img\b)",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(
    r"(?:表\s*\d+|Table\s*\d+|SEQ\s+Table|REF\s+litassist_table_\d+|<table\b|<tr\b|<td\b|<th\b|<w:tbl\b)",
    re.IGNORECASE,
)
_EQUATION_RE = re.compile(
    r"(?:式\s*[（(]?\s*\d+\s*[）)]?|公式\s*\d+|Equation\s*[（(]?\s*\d+\s*[）)]?|Eq\.\s*[（(]?\s*\d+\s*[）)]?|SEQ\s+Equation|REF\s+litassist_equation_\d+|data-formula\b|<m:oMath\b|\\begin\{equation\})",
    re.IGNORECASE,
)
_ZH_CONNECTORS = (
    "因此",
    "然而",
    "此外",
    "同时",
    "进一步",
    "表明",
    "说明",
    "支持",
    "影响",
    "机制",
    "关键",
    "相比",
    "由于",
    "导致",
    "揭示",
    "验证",
)
_EN_CONNECTORS = (
    "therefore",
    "however",
    "furthermore",
    "moreover",
    "in contrast",
    "suggests",
    "indicates",
    "supports",
    "mechanism",
    "consequently",
    "whereas",
    "because",
    "driven by",
)
_CONVERSATIONAL_PATTERNS = (
    re.compile(r"作为\s*AI|作为一个(?:人工智能|AI)|下面我|我将|首先我会|本文档将|这篇文章将会"),
    re.compile(r"\b(?:here is|here are|as an ai|i will|i can|let's|we will now)\b", re.IGNORECASE),
    re.compile(r"请注意|希望这(?:能|可以)帮助|如果你(?:需要|想)"),
)
_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "review": ("综述", "文献综述", "review", "literature review"),
    "literature review": ("综述", "文献综述", "review", "literature review"),
    "综述": ("综述", "文献综述", "review", "literature review"),
    "introduction": ("引言", "绪论", "introduction"),
    "intro": ("引言", "绪论", "introduction"),
    "引言": ("引言", "绪论", "introduction"),
    "methods": ("方法", "材料与方法", "method", "methods"),
    "results": ("结果", "results"),
    "discussion": ("讨论", "discussion"),
}


def lint_academic_writing(request: AcademicWritingLintRequest) -> AcademicWritingLintResponse:
    """Lint scholarly draft text for evidence, structure, tone, and references.

    Args:
        request: Validated lint request. At least one of ``text`` or ``html``
            must contain non-whitespace content.

    Returns:
        A deterministic quality report with bounded metrics and recommendations.

    Raises:
        TypeError: ``request`` is not an ``AcademicWritingLintRequest``.
        ValueError: Input content, language, content type, or style profile is
            outside the supported deterministic contract.
    """

    if not isinstance(request, AcademicWritingLintRequest):
        raise TypeError("request must be AcademicWritingLintRequest")
    raw_html = str(request.html or "")
    raw_text = str(request.text or "")
    source_text = raw_html if raw_html.strip() else raw_text
    if not source_text.strip():
        raise ValueError("text or html must be non-empty")
    normalized_text = _normalize_to_plain_text(raw_text=raw_text, raw_html=raw_html)
    if not normalized_text:
        raise ValueError("normalized academic writing text is empty")

    language = _resolve_language(normalized_text, request.language)
    section_titles = _extract_section_titles(raw_text=raw_text, raw_html=raw_html, plain_text=normalized_text)
    metrics = _build_metrics(
        plain_text=normalized_text,
        raw_html=raw_html,
        section_titles=section_titles,
        language=language,
    )
    issues: list[AcademicWritingLintIssue] = []
    issues.extend(_section_issues(request, section_titles, normalized_text))
    issues.extend(_evidence_issues(request, metrics))
    issues.extend(_tone_issues(normalized_text))
    issues.extend(_reasoning_issues(metrics, language))
    issues.extend(_length_issues(request.content_type, metrics))
    issues.extend(_figure_table_equation_issues(request, metrics))
    issues.extend(_style_profile_issues(request.style_profile, metrics))

    score = _score_issues(issues)
    passed = score >= 70.0 and not any(issue.severity == "error" for issue in issues)
    audit = _build_audit_trail(
        request=request,
        metrics=metrics,
        normalized_text=normalized_text,
        passed=passed,
    )
    return AcademicWritingLintResponse(
        passed=passed,
        score=score,
        content_type=request.content_type,
        language=language,
        metrics=metrics,
        audit=audit,
        issues=issues,
        recommendations=_recommendations(issues),
    )


def _normalize_to_plain_text(*, raw_text: str, raw_html: str) -> str:
    """Return whitespace-normalized text while preserving heading words."""

    source = raw_html if raw_html.strip() else raw_text
    if raw_html.strip():
        source = _HTML_HEADING_RE.sub(lambda match: f"\n{_strip_tags(match.group(2))}\n", raw_html)
        source = _TAG_RE.sub(" ", source)
    return _WHITESPACE_RE.sub(" ", html_lib.unescape(source)).strip()


def _strip_tags(value: str) -> str:
    """Remove HTML tags from a small fragment."""

    return _WHITESPACE_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", str(value or "")))).strip()


def _resolve_language(text: str, requested: AcademicLintLanguage) -> Literal["zh", "en"]:
    """Resolve ``auto`` language to Chinese or English."""

    if requested in {"zh", "en"}:
        return requested
    if requested != "auto":
        raise ValueError("language must be zh, en, or auto")
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"\b[A-Za-z]{3,}\b", text))
    return "zh" if zh_chars >= max(8, latin_words // 2) else "en"


def _extract_section_titles(*, raw_text: str, raw_html: str, plain_text: str) -> list[str]:
    """Extract visible section headings from Markdown, HTML, and standalone labels."""

    titles: list[str] = []
    if raw_html.strip():
        for match in _HTML_HEADING_RE.finditer(raw_html):
            title = _strip_tags(match.group(2))
            if title:
                titles.append(title)
    for match in _SECTION_MARKDOWN_RE.finditer(raw_text):
        title = match.group(1).strip()
        if title:
            titles.append(title)
    for match in _SECTION_STANDALONE_RE.finditer(raw_text):
        title = match.group(1).strip()
        if title:
            titles.append(title)
    if not titles:
        for match in re.finditer(r"(文献综述|综述|引言|绪论|Introduction|Literature Review|Review)", plain_text, re.IGNORECASE):
            titles.append(match.group(1))
    deduped: list[str] = []
    seen: set[str] = set()
    for title in titles:
        normalized = title.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(title.strip())
    return deduped


def _build_metrics(
    *,
    plain_text: str,
    raw_html: str,
    section_titles: list[str],
    language: Literal["zh", "en"],
) -> AcademicWritingLintMetrics:
    """Compute deterministic metrics without exposing draft content."""

    citation_count = sum(len(pattern.findall(plain_text)) for pattern in _CITATION_PATTERNS)
    evidence_ref_count = len(_EVIDENCE_REF_RE.findall(plain_text))
    figure_ref_count = len(_FIGURE_RE.findall(raw_html or plain_text))
    table_ref_count = len(_TABLE_RE.findall(raw_html or plain_text))
    equation_ref_count = len(_EQUATION_RE.findall(raw_html or plain_text))
    connector_terms = _ZH_CONNECTORS if language == "zh" else _EN_CONNECTORS
    connector_count = sum(_count_term(plain_text, term) for term in connector_terms)
    conversational_count = sum(len(pattern.findall(plain_text)) for pattern in _CONVERSATIONAL_PATTERNS)
    return AcademicWritingLintMetrics(
        char_count=len(plain_text),
        word_count=_word_count(plain_text, language),
        section_count=len(section_titles),
        citation_count=citation_count,
        evidence_ref_count=evidence_ref_count,
        figure_ref_count=figure_ref_count,
        table_ref_count=table_ref_count,
        equation_ref_count=equation_ref_count,
        academic_connector_count=connector_count,
        conversational_phrase_count=conversational_count,
    )


def _word_count(text: str, language: Literal["zh", "en"]) -> int:
    """Return approximate word count for English or Chinese text."""

    if language == "zh":
        zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_words = len(re.findall(r"\b[A-Za-z0-9][A-Za-z0-9\-]*\b", text))
        return zh_chars + latin_words
    return len(re.findall(r"\b[A-Za-z0-9][A-Za-z0-9\-]*\b", text))


def _count_term(text: str, term: str) -> int:
    """Count academic connector occurrences with English word boundaries."""

    if re.search(r"[A-Za-z]", term):
        return len(re.findall(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE))
    return text.count(term)


def _section_issues(
    request: AcademicWritingLintRequest,
    section_titles: list[str],
    text: str,
) -> list[AcademicWritingLintIssue]:
    """Return structure issues for required scholarly sections."""

    required = list(request.required_sections)
    if not required and request.content_type == "review":
        required = ["review"]
    elif not required and request.content_type == "introduction":
        required = ["introduction"]
    elif not required and request.content_type == "manuscript":
        required = ["introduction", "review"]
    issues: list[AcademicWritingLintIssue] = []
    searchable = " ".join([*section_titles, text[:500]]).lower()
    for name in required:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            continue
        aliases = _SECTION_ALIASES.get(normalized_name.lower(), (normalized_name,))
        if not any(alias.lower() in searchable for alias in aliases):
            issues.append(
                AcademicWritingLintIssue(
                    code="missing_required_section",
                    severity="error",
                    message=f"缺少必要学术章节: {normalized_name}",
                )
            )
    if request.content_type in {"review", "manuscript"} and not section_titles:
        issues.append(
            AcademicWritingLintIssue(
                code="missing_section_headings",
                severity="warning",
                message="文本缺少清晰章节标题，综述/论文结构不可审计。",
            )
        )
    return issues


def _evidence_issues(
    request: AcademicWritingLintRequest,
    metrics: AcademicWritingLintMetrics,
) -> list[AcademicWritingLintIssue]:
    """Return citation/evidence grounding issues."""

    if not request.require_evidence_refs:
        return []
    if metrics.citation_count == 0 and metrics.evidence_ref_count == 0:
        return [
            AcademicWritingLintIssue(
                code="missing_evidence_refs",
                severity="error",
                message="正文缺少引用或证据锚点，不能证明论断来源。",
            )
        ]
    if metrics.evidence_ref_count == 0:
        return [
            AcademicWritingLintIssue(
                code="missing_machine_readable_evidence_refs",
                severity="warning",
                message="正文有传统引用，但缺少 chunk/evidence_pack/cite 等机器可追溯证据锚点。",
            )
        ]
    return []


def _tone_issues(text: str) -> list[AcademicWritingLintIssue]:
    """Return issues for conversational or AI-assistant phrasing."""

    issues: list[AcademicWritingLintIssue] = []
    for pattern in _CONVERSATIONAL_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(
                AcademicWritingLintIssue(
                    code="conversational_or_ai_tone",
                    severity="error",
                    message="出现聊天式或 AI 助手式表达，应改为客观科研论文语体。",
                    span={"start": match.start(), "end": match.end(), "text": match.group(0)[:40]},
                )
            )
            break
    return issues


def _reasoning_issues(
    metrics: AcademicWritingLintMetrics,
    language: Literal["zh", "en"],
) -> list[AcademicWritingLintIssue]:
    """Return issues for weak logical connectors and academic reasoning cues."""

    minimum = 2 if metrics.char_count >= 500 else 1
    if metrics.academic_connector_count >= minimum:
        return []
    message = "缺少学术逻辑连接词和论证动词，论证链可能像资料堆砌。"
    if language == "en":
        message = "Academic connectors and claim verbs are sparse; the argument may read as a list of facts."
    return [
        AcademicWritingLintIssue(
            code="weak_academic_reasoning_markers",
            severity="warning",
            message=message,
        )
    ]


def _length_issues(
    content_type: AcademicLintContentType,
    metrics: AcademicWritingLintMetrics,
) -> list[AcademicWritingLintIssue]:
    """Return short-content issues using section-specific thresholds."""

    minimum_chars = {
        "introduction": 180,
        "review": 350,
        "manuscript": 500,
        "section": 120,
    }[content_type]
    if metrics.char_count >= minimum_chars:
        return []
    return [
        AcademicWritingLintIssue(
            code="too_short_for_academic_unit",
            severity="warning",
            message=f"当前文本长度不足以支撑 {content_type} 的完整学术论证。",
        )
    ]


def _figure_table_equation_issues(
    request: AcademicWritingLintRequest,
    metrics: AcademicWritingLintMetrics,
) -> list[AcademicWritingLintIssue]:
    """Return figure/table/equation reference completeness issues."""

    if not request.require_figure_table_formula_refs:
        return []
    issues: list[AcademicWritingLintIssue] = []
    if metrics.figure_ref_count == 0:
        issues.append(
            AcademicWritingLintIssue(
                code="missing_figure_reference",
                severity="error",
                message="要求图表公式完整引用时，正文至少需要一个图引用或图题注。",
            )
        )
    if metrics.table_ref_count == 0:
        issues.append(
            AcademicWritingLintIssue(
                code="missing_table_reference",
                severity="error",
                message="要求图表公式完整引用时，正文至少需要一个表引用或表格元素。",
            )
        )
    if metrics.equation_ref_count == 0:
        issues.append(
            AcademicWritingLintIssue(
                code="missing_equation_reference",
                severity="error",
                message="要求图表公式完整引用时，正文至少需要一个公式/式号引用。",
            )
        )
    return issues


def _style_profile_issues(
    style_profile: str | None,
    metrics: AcademicWritingLintMetrics,
) -> list[AcademicWritingLintIssue]:
    """Return journal/style-profile expectation issues."""

    if style_profile is None or not str(style_profile).strip():
        return []
    normalized = str(style_profile).strip().lower().replace("-", "_")
    if len(normalized) > 80 or not all(char.isalnum() or char == "_" for char in normalized):
        raise ValueError("style_profile must be an identifier-like string up to 80 characters")
    numeric_required = normalized in {"gb_t_7714_review", "ieee", "nature"}
    author_year_required = normalized == "apa"
    issues: list[AcademicWritingLintIssue] = []
    if numeric_required and metrics.citation_count > 0:
        # Numeric citations are included in citation_count together with other
        # citation forms, so inspect via style-specific issue only when no
        # citation was present at all; missing evidence already covers that.
        return issues
    if numeric_required and metrics.citation_count == 0:
        issues.append(
            AcademicWritingLintIssue(
                code="style_profile_requires_numeric_citations",
                severity="warning",
                message=f"{style_profile} 通常需要数字顺序引用，当前未检测到数字引用。",
            )
        )
    if author_year_required and metrics.citation_count == 0:
        issues.append(
            AcademicWritingLintIssue(
                code="style_profile_requires_author_year_citations",
                severity="warning",
                message="APA 风格通常需要作者-年份引用，当前未检测到作者-年份引用。",
            )
        )
    return issues


def _build_audit_trail(
    *,
    request: AcademicWritingLintRequest,
    metrics: AcademicWritingLintMetrics,
    normalized_text: str,
    passed: bool,
) -> AcademicWritingAuditTrail:
    """Build a bounded provenance trail for direct and agent-mediated lint."""

    context = request.audit_context or AcademicWritingAuditContext()
    surface = context.invocation_surface
    used_tools = _sanitize_audit_list(context.used_mcp_tools)
    tool_chain = _sanitize_audit_list(context.tool_chain)
    if surface in {"external_mcp", "api_chat_local_tools"} and "literature.academic_writing_lint" not in used_tools:
        used_tools.append("literature.academic_writing_lint")
    evidence_pack_refs = sorted(set(_EVIDENCE_PACK_REF_RE.findall(normalized_text)))
    retrieval_diagnostics = _sanitize_diagnostics(context.retrieval_diagnostics)
    reasoning_trace = _sanitize_audit_list(context.reasoning_trace)
    if retrieval_diagnostics is not None:
        for item in retrieval_diagnostics.get("reasoning_trace", []):
            if isinstance(item, str):
                sanitized_item = _sanitize_optional_audit_text(item, max_chars=180)
                if sanitized_item and sanitized_item not in reasoning_trace:
                    reasoning_trace.append(sanitized_item)
                    if len(reasoning_trace) >= 16:
                        break
    checks = [
        "structure",
        "evidence_refs" if request.require_evidence_refs else "evidence_refs_optional",
        "academic_tone",
        "logical_reasoning",
    ]
    if request.require_figure_table_formula_refs:
        checks.append("figure_table_equation_refs")
    if request.style_profile:
        checks.append("journal_style_profile")
    agent_mediated = surface in {"external_mcp", "api_chat_local_tools"} or bool(used_tools)
    mcp_tool_calls_used = bool(used_tools) or surface == "external_mcp"
    disclosure_required = agent_mediated
    return AcademicWritingAuditTrail(
        invocation_surface=surface,
        agent_mediated=agent_mediated,
        mcp_tool_calls_used=mcp_tool_calls_used,
        agent_host=_sanitize_optional_audit_text(context.agent_host, max_chars=80),
        source=_sanitize_optional_audit_text(context.source, max_chars=80),
        project_id=_sanitize_optional_audit_text(context.project_id, max_chars=128),
        tool_chain=tool_chain,
        used_mcp_tools=used_tools,
        style_profile=_sanitize_optional_audit_text(request.style_profile, max_chars=80),
        evidence_ref_count=metrics.evidence_ref_count,
        evidence_pack_ref_count=len(evidence_pack_refs),
        retrieval_diagnostics=retrieval_diagnostics,
        reasoning_trace=reasoning_trace,
        quality_gate="passed" if passed else "failed",
        checks=checks,
        disclosure_required=disclosure_required,
        disclosure_note=(
            "AI/MCP-assisted drafting should remain author-verified and disclosed according to the target journal."
            if disclosure_required
            else None
        ),
    )


def _sanitize_audit_list(values: list[str]) -> list[str]:
    """Return deduplicated short audit labels without free-form manuscript text."""

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _sanitize_optional_audit_text(value, max_chars=120)
        if label is None or label in seen:
            continue
        seen.add(label)
        cleaned.append(label)
    return cleaned


def _sanitize_optional_audit_text(value: str | None, *, max_chars: int) -> str | None:
    """Keep audit labels bounded and single-line."""

    if value is None:
        return None
    text = _WHITESPACE_RE.sub(" ", str(value)).strip()
    if not text:
        return None
    return text[:max_chars]


def _sanitize_diagnostics(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return bounded retrieval diagnostics for writing-audit output."""

    if not isinstance(value, dict):
        return None
    allowed_keys = {
        "retrieval_method",
        "embedding_status",
        "rerank_status",
        "fallback_reason",
        "project_weight",
        "wiki_weight",
        "joint_recall",
        "reasoning_trace",
        "notes",
    }
    cleaned: dict[str, Any] = {}
    for key in allowed_keys:
        if key not in value:
            continue
        raw = value[key]
        if key == "joint_recall":
            sanitized_joint = _sanitize_joint_recall(raw)
            if sanitized_joint:
                cleaned[key] = sanitized_joint
            continue
        if key in {"reasoning_trace", "notes"}:
            if isinstance(raw, list):
                cleaned[key] = _sanitize_audit_list([str(item) for item in raw[:16]])
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            cleaned[key] = float(raw)
            continue
        if isinstance(raw, str):
            cleaned_value = _sanitize_optional_audit_text(raw, max_chars=240)
            if cleaned_value is not None:
                cleaned[key] = cleaned_value
    return cleaned or None


def _sanitize_joint_recall(value: Any) -> dict[str, Any] | None:
    """Return bounded wiki+project fusion diagnostics for audit output."""

    if not isinstance(value, dict):
        return None
    allowed_scalar_keys = {
        "enabled",
        "status",
        "reason",
        "fusion_method",
        "project_weight",
        "wiki_weight",
        "project_hit_count",
        "wiki_hit_count",
        "wiki_share_after_fusion",
    }
    cleaned: dict[str, Any] = {}
    for key in allowed_scalar_keys:
        if key not in value:
            continue
        raw = value[key]
        if isinstance(raw, bool):
            cleaned[key] = raw
        elif isinstance(raw, (int, float)):
            cleaned[key] = float(raw)
        elif isinstance(raw, str):
            text = _sanitize_optional_audit_text(raw, max_chars=160)
            if text is not None:
                cleaned[key] = text
    source_counts = value.get("source_counts")
    if isinstance(source_counts, dict):
        cleaned["source_counts"] = {
            key: int(raw)
            for key, raw in source_counts.items()
            if key in {"project", "wiki"} and isinstance(raw, int) and raw >= 0
        }
    top_doc_ids = value.get("top_doc_ids")
    if isinstance(top_doc_ids, list):
        cleaned["top_doc_ids"] = _sanitize_audit_list([str(item) for item in top_doc_ids[:5]])
    wiki_summaries = value.get("wiki_summaries")
    if isinstance(wiki_summaries, list):
        bounded_summaries: list[dict[str, str]] = []
        for item in wiki_summaries[:3]:
            if not isinstance(item, dict):
                continue
            summary: dict[str, str] = {}
            for key, limit in {
                "doc_id": 160,
                "ref_id": 160,
                "read_endpoint": 300,
                "title": 160,
                "summary": 240,
                "page_path": 240,
                "source": 80,
            }.items():
                text = _sanitize_optional_audit_text(str(item.get(key) or ""), max_chars=limit)
                if text is not None:
                    summary[key] = text
            if summary:
                bounded_summaries.append(summary)
        cleaned["wiki_summaries"] = bounded_summaries
    return cleaned or None


def _score_issues(issues: list[AcademicWritingLintIssue]) -> float:
    """Return a bounded 0-100 score from issue penalties."""

    penalties = {"error": 25.0, "warning": 9.0, "info": 3.0}
    score = 100.0 - sum(penalties[issue.severity] for issue in issues)
    return round(max(0.0, min(100.0, score)), 1)


def _recommendations(issues: list[AcademicWritingLintIssue]) -> list[str]:
    """Return stable recommendations mapped from issue codes."""

    by_code = {
        "missing_required_section": "补齐目标期刊/稿件类型要求的章节标题，并把论证内容放到对应章节下。",
        "missing_section_headings": "使用清晰的 Markdown/HTML 标题，让综述、引言、讨论等结构可解析。",
        "missing_evidence_refs": "每个关键论断至少绑定一个文献引用、chunk ref 或 evidence_pack ref。",
        "missing_machine_readable_evidence_refs": "把传统引用同步到 chunk/evidence_pack/cite 锚点，便于 MCP 追溯原文。",
        "conversational_or_ai_tone": "删除“我将/Here is/作为AI”等助手口吻，改写为客观陈述。",
        "weak_academic_reasoning_markers": "增加“表明、因此、然而、机制、支持”等逻辑连接和论证动词。",
        "too_short_for_academic_unit": "扩展背景、争议点、证据比较和小结，避免只列事实。",
        "missing_figure_reference": "补充图编号、图题注或正文中的图引用。",
        "missing_table_reference": "补充表编号、表题或正文中的表引用。",
        "missing_equation_reference": "补充公式编号并在正文中引用。",
        "style_profile_requires_numeric_citations": "按目标样式改为数字顺序引用，并与参考文献表保持一致。",
        "style_profile_requires_author_year_citations": "按 APA 等作者-年份样式补齐正文引用。",
    }
    recommendations: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        recommendation = by_code.get(issue.code)
        if recommendation and recommendation not in seen:
            seen.add(recommendation)
            recommendations.append(recommendation)
    return recommendations


def lint_academic_writing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and lint a JSON-like payload.

    Args:
        payload: Request dictionary from API/MCP callers.

    Returns:
        JSON-serializable lint response.
    """

    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")
    request = AcademicWritingLintRequest.model_validate(payload)
    return lint_academic_writing(request).model_dump(mode="json")
