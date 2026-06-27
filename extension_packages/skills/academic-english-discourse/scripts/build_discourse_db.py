#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build a local academic-English discourse database for Scholar AI."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

from literature_assistant.core.pdf_backends import OcrEngine, OcrRuntimeConfig, select_ocr_engine


BUILDER_VERSION = "0.2.0"
SCHEMA_VERSION = "0.2"
DEFAULT_PHRASEBANK_URL = "https://www.phrasebank.manchester.ac.uk/"
DEFAULT_OUTPUT_PARTS = ("workspace_artifacts", "generated", "output", "english_discourse")
DEFAULT_DOWNLOAD_FILENAMES = (
    "WritingScienceinPlainEnglish.pdf",
    "writing_science_in_plain_english_2023.pdf",
    "Writing_Science_Joshua_Schimel.pdf",
    "1693305941.pdf",
    "AWFGS.pdf",
    "English+for+Writing+Research+Papers.pdf",
    "science_writing_for_non-native_engish_speakers.pdf",
)


MOVE_RULES: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "territory": (
        "建立研究领域或背景",
        (
            r"\b(?:has become|is increasingly|plays? (?:an )?important role|is central to|is widely used)\b",
            r"\b(?:in recent years|over the past|a growing body of|research on)\b",
        ),
    ),
    "gap": (
        "指出不足、争议或未解决问题",
        (
            r"\b(?:however|nevertheless|despite|although|whereas|while)\b",
            r"\b(?:little is known|remains unclear|has not been|few studies|limited evidence|underexplored|open question)\b",
        ),
    ),
    "aim": (
        "说明本文、研究或段落目的",
        (
            r"\b(?:this (?:paper|study|review|section)|we)\s+(?:aim|seek|examine|investigate|propose|present|evaluate)\b",
            r"\b(?:the aim|the objective|the purpose)\s+(?:of|is)\b",
        ),
    ),
    "method": (
        "描述方法、数据、材料或流程",
        (
            r"\b(?:we used|we conducted|we collected|we measured|was performed|were performed|dataset|sample|method)\b",
            r"\b(?:participants|materials|procedure|analysis|model|experiment|simulation)\b",
        ),
    ),
    "result": (
        "报告结果或观察",
        (
            r"\b(?:results? (?:show|indicate|suggest|demonstrate)|we found|was observed|were observed)\b",
            r"\b(?:increased|decreased|improved|reduced|significant|non-significant|correlated)\b",
        ),
    ),
    "interpretation": (
        "解释结果含义",
        (
            r"\b(?:these findings|this suggests|this indicates|may reflect|can be interpreted|taken together)\b",
            r"\b(?:likely|possibly|therefore|thus|accordingly)\b",
        ),
    ),
    "comparison": (
        "比较、对照或综合多项研究",
        (
            r"\b(?:compared with|in contrast|similarly|consistent with|contrary to|whereas|while)\b",
            r"\b(?:previous studies|prior work|earlier research|the literature)\b",
        ),
    ),
    "causality": (
        "表达机制、因果或影响",
        (
            r"\b(?:because|therefore|thus|consequently|leads? to|results? in|driven by|due to)\b",
            r"\b(?:mechanism|pathway|mediates?|moderates?|affects?|influences?)\b",
        ),
    ),
    "limitation": (
        "限定范围、承认证据边界",
        (
            r"\b(?:limited by|limitation|caution|should be interpreted|cannot be ruled out|small sample)\b",
            r"\b(?:may not|might not|does not necessarily|further research is needed)\b",
        ),
    ),
    "implication": (
        "说明贡献、启示或后续方向",
        (
            r"\b(?:implications?|contributes? to|provides? evidence|future research|could inform)\b",
            r"\b(?:practice|policy|theory|clinical|design|application)\b",
        ),
    ),
    "transition": (
        "组织段落或章节过渡",
        (
            r"\b(?:first|second|finally|in addition|moreover|furthermore|next|overall)\b",
            r"\b(?:the following section|as discussed above|in summary)\b",
        ),
    ),
    "citation": (
        "引用、归因或文献综合",
        (
            r"\b(?:argue|suggest|report|demonstrate|show|find|found|according to)\b",
            r"\([A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,?\s+\d{4}[a-z]?\)",
        ),
    ),
}


FEATURE_RULES: Mapping[str, tuple[str, ...]] = {
    "hedging": (
        r"\b(?:may|might|could|appears? to|seems? to|suggests?|indicates?|likely|possibly|potentially)\b",
    ),
    "stance": (
        r"\b(?:important|notable|surprising|robust|weak|strong|substantial|marginal)\b",
    ),
    "citation": (
        r"\b(?:et al\.|according to|reported by|as shown by)\b",
        r"\([A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,?\s+\d{4}[a-z]?\)",
    ),
    "contrast": (
        r"\b(?:however|nevertheless|whereas|while|in contrast|despite|although)\b",
    ),
    "causal_link": (
        r"\b(?:because|therefore|thus|due to|leads? to|results? in|consequently)\b",
    ),
    "quantification": (
        r"\b\d+(?:\.\d+)?\s*(?:%|percent|fold|times|kg|mg|mm|cm|years?|months?|days?)\b",
    ),
    "method_focus": (
        r"\b(?:method|dataset|sample|experiment|model|analysis|procedure|measured|estimated)\b",
    ),
    "limitation": (
        r"\b(?:limitation|limited|caution|uncertain|further research|cannot)\b",
    ),
    "metadiscourse": (
        r"\b(?:this paper|this study|this section|we argue|we propose|we review)\b",
    ),
}


STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "also",
        "although",
        "among",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "could",
        "during",
        "each",
        "from",
        "further",
        "have",
        "however",
        "into",
        "more",
        "most",
        "other",
        "over",
        "such",
        "than",
        "that",
        "their",
        "there",
        "these",
        "this",
        "those",
        "through",
        "under",
        "using",
        "were",
        "where",
        "which",
        "while",
        "with",
        "within",
        "would",
    }
)


@dataclass(frozen=True)
class SourceDocument:
    """Normalized source unit extracted from a PDF, text file, or HTML page."""

    source_id: str
    source_type: str
    title: str
    locator: str
    section: str
    text: str
    origin_path: str


@dataclass(frozen=True)
class DiscourseChunk:
    """Searchable discourse chunk persisted as JSONL and SQLite rows."""

    chunk_id: str
    source_id: str
    source_type: str
    source_path: str
    source_hash: str
    title: str
    locator: str
    section: str
    text: str
    summary: str
    content_hash: str
    span_start: int
    span_end: int
    rhetorical_moves: list[str]
    features: list[str]
    keywords: list[str]
    char_count: int
    word_count: int


@dataclass(frozen=True)
class PhraseCandidate:
    """Reusable wording pattern derived from a local source."""

    phrase_id: str
    source_id: str
    source_type: str
    source_path: str
    source_hash: str
    text: str
    normalized: str
    content_hash: str
    span_start: int
    span_end: int
    move: str
    features: list[str]
    section: str
    locator: str
    adaptation_note: str


@dataclass(frozen=True)
class BuildSettings:
    """Serializable extraction settings for manifest and audit records."""

    chunk_size: int
    chunk_overlap: int
    max_phrasebank_pages: int
    distilled_only: bool
    include_phrasebank: bool
    ocr_engine: str
    ocr_language: str
    ocr_scale: float


def _sha256_text(value: str, *, length: int = 16) -> str:
    """Return a short deterministic id for a non-empty text value."""

    if not isinstance(value, str) or not value:
        raise ValueError("value must be a non-empty string")
    if length < 8 or length > 64:
        raise ValueError("length must be between 8 and 64")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _sha256_text_full(value: str) -> str:
    """Return a full SHA-256 digest for runtime provenance payloads."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    """Return a full SHA-256 digest for an existing file artifact."""

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _repo_root_from_script() -> Path:
    """Resolve the repository root from the script location or current working directory."""

    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / "literature_assistant").exists() and (candidate / "workspace_artifacts").exists():
            return candidate
        if (candidate / "AI_WORKSPACE_GUIDE.md").exists():
            return candidate
    return Path.cwd()


def _default_output_dir() -> Path:
    """Return the canonical generated-output directory for Scholar AI."""

    return _repo_root_from_script().joinpath(*DEFAULT_OUTPUT_PARTS)


def _clean_text(value: str) -> str:
    """Normalize source text while preserving sentence and paragraph boundaries."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    text = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def _word_count(value: str) -> int:
    """Count whitespace-delimited lexical tokens for schema metadata."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*|\d+(?:\.\d+)?", value))


def _sentences(value: str) -> list[str]:
    """Split English prose into conservative sentence-like units."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    normalized = _clean_text(value)
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", normalized)
    return [part.strip() for part in parts if _word_count(part) >= 4]


def _recursive_chunks(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text by paragraph and sentence while keeping coherent local context."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if chunk_size < 120:
        raise ValueError("chunk_size must be at least 120 characters")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    cleaned = _clean_text(text)
    if len(cleaned) <= chunk_size:
        return [cleaned] if cleaned else []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
            continue
        units.extend(_sentences(paragraph))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        if len(current) + 1 + len(unit) <= chunk_size:
            current = f"{current} {unit}"
            continue
        chunks.append(current.strip())
        overlap = current[-chunk_overlap:].strip() if chunk_overlap else ""
        current = f"{overlap} {unit}".strip() if overlap else unit
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if _word_count(chunk) >= 8]


def _detect_by_rules(text: str, rules: Mapping[str, tuple[str, ...]] | Mapping[str, tuple[str, tuple[str, ...]]]) -> list[str]:
    """Return rule keys whose regex patterns match the provided text."""

    if not isinstance(text, str) or not text.strip():
        return []
    found: list[str] = []
    for key, raw_rule in rules.items():
        patterns: tuple[str, ...]
        if len(raw_rule) == 2 and isinstance(raw_rule[1], tuple):  # MOVE_RULES
            patterns = raw_rule[1]  # type: ignore[index]
        else:
            patterns = raw_rule  # type: ignore[assignment]
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            found.append(key)
    return found


def _detect_moves(text: str) -> list[str]:
    """Infer rhetorical moves from a text chunk."""

    moves = _detect_by_rules(text, MOVE_RULES)
    return moves or ["general_academic_prose"]


def _detect_features(text: str) -> list[str]:
    """Infer academic style features from a text chunk."""

    return _detect_by_rules(text, FEATURE_RULES)


def _keywords(text: str, *, limit: int = 12) -> list[str]:
    """Extract compact lowercase keywords without external NLP dependencies."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)
        if word.lower() not in STOPWORDS
    ]
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for index, word in enumerate(words):
        counts[word] = counts.get(word, 0) + 1
        order.setdefault(word, index)
    ranked = sorted(counts, key=lambda item: (-counts[item], order[item], item))
    return ranked[:limit]


def _summary(text: str, *, max_chars: int = 280) -> str:
    """Return a compact source preview without adding model-generated claims."""

    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    first_sentence = _sentences(text)
    candidate = first_sentence[0] if first_sentence else _clean_text(text)
    if len(candidate) <= max_chars:
        return candidate
    return candidate[: max_chars - 1].rstrip() + "..."


def _text_span(haystack: str, needle: str, *, start_hint: int = 0) -> tuple[int, int]:
    """Return a best-effort source span for generated knowledge records."""

    if not isinstance(haystack, str):
        raise TypeError("haystack must be a string")
    if not isinstance(needle, str):
        raise TypeError("needle must be a string")
    if start_hint < 0:
        raise ValueError("start_hint must be non-negative")
    if not needle:
        return 0, 0
    bounded_hint = min(start_hint, len(haystack))
    start = haystack.find(needle, bounded_hint)
    if start < 0:
        start = haystack.find(needle)
    if start < 0:
        return 0, len(needle)
    return start, start + len(needle)


def _adaptation_note(move: str, features: Sequence[str]) -> str:
    """Return a concise Chinese note for adapting a phrase pattern."""

    move_label = MOVE_RULES.get(move, ("通用学术表达", ()))[0]
    feature_text = "、".join(features) if features else "无明显附加特征"
    return f"用于{move_label}；改写时先替换研究对象、证据范围和确定性强度；风格特征：{feature_text}。"


def _source_id(source_type: str, locator: str, title: str) -> str:
    """Build a stable source id from source metadata."""

    if not source_type or not locator or not title:
        raise ValueError("source_type, locator, and title are required")
    return f"{source_type}_{_sha256_text(source_type + '|' + locator + '|' + title, length=14)}"


def _extract_pdf_with_pymupdf(path: Path) -> list[SourceDocument]:
    """Extract page-level text from a PDF using PyMuPDF when available."""

    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception:
        try:
            import fitz as pymupdf  # type: ignore[import-not-found,no-redef]
        except Exception as exc:
            raise RuntimeError("PyMuPDF is not available") from exc

    documents: list[SourceDocument] = []
    title = path.stem
    with pymupdf.open(str(path)) as pdf_doc:  # type: ignore[attr-defined]
        for page_index, page in enumerate(pdf_doc, start=1):
            try:
                text = page.get_text("text", sort=True)
            except TypeError:
                text = page.get_text()
            cleaned = _clean_text(str(text))
            if _word_count(cleaned) < 8:
                continue
            locator = f"{path.name}#page={page_index}"
            documents.append(
                SourceDocument(
                    source_id=_source_id("pdf", locator, title),
                    source_type="pdf",
                    title=title,
                    locator=locator,
                    section=f"page {page_index}",
                    text=cleaned,
                    origin_path=str(path),
                )
            )
    return documents


def _extract_pdf_with_pypdf(path: Path) -> list[SourceDocument]:
    """Extract page-level text from a PDF using pypdf as a fallback."""

    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError("Neither PyMuPDF nor pypdf is available") from exc

    reader = PdfReader(str(path))
    title = path.stem
    documents: list[SourceDocument] = []
    for page_index, page in enumerate(reader.pages, start=1):
        cleaned = _clean_text(page.extract_text() or "")
        if _word_count(cleaned) < 8:
            continue
        locator = f"{path.name}#page={page_index}"
        documents.append(
            SourceDocument(
                source_id=_source_id("pdf", locator, title),
                source_type="pdf",
                title=title,
                locator=locator,
                section=f"page {page_index}",
                text=cleaned,
                origin_path=str(path),
            )
        )
    return documents


def _select_core_ocr_engine(ocr_engine: str, *, language_tag: str) -> OcrEngine | None:
    """Select the shared Scholar AI OCR engine for scanned PDF fallback.

    Args:
        ocr_engine: ``auto`` to use the runtime policy or ``windows`` to require
            the local Windows adapter.
        language_tag: Non-empty OCR language tag passed into the shared runtime
            config.

    Returns:
        Selected OCR engine, or ``None`` when ``auto`` finds no available
        engine.

    Raises:
        ValueError: If the requested engine or language tag is invalid.
        RuntimeError: If an explicitly requested engine is unavailable.
    """

    normalized = str(ocr_engine or "").strip().lower()
    language = str(language_tag or "").strip()
    if not language:
        raise ValueError("OCR language must be non-empty")
    if normalized == "auto":
        config = OcrRuntimeConfig(policy="auto", language=language)
    elif normalized == "windows":
        config = OcrRuntimeConfig(policy="engine", engine="windows", language=language)
    else:
        raise ValueError(f"unsupported OCR engine: {ocr_engine}")

    engine, warning = select_ocr_engine(config)
    if engine is None and normalized == "windows":
        raise RuntimeError(warning or "Windows OCR engine is unavailable")
    return engine


def _extract_pdf_with_ocr_engine(
    path: Path,
    *,
    ocr_output_dir: Path,
    language_tag: str,
    scale: float,
    engine: OcrEngine,
) -> list[SourceDocument]:
    """Extract page-level OCR text from a scanned PDF using a shared engine.

    Args:
        path: Existing PDF path to render page by page.
        ocr_output_dir: Directory for cached page PNGs.
        language_tag: OCR language tag for the selected engine.
        scale: PyMuPDF render scale in the inclusive range [1.0, 4.0].
        engine: Shared Scholar AI OCR image-to-text engine.

    Returns:
        Page-level OCR source documents with stable locators.
    """

    if scale < 1.0 or scale > 4.0:
        raise ValueError("OCR render scale must be between 1.0 and 4.0")
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception:
        try:
            import fitz as pymupdf  # type: ignore[import-not-found,no-redef]
        except Exception as exc:
            raise RuntimeError("PyMuPDF is required for OCR page rendering") from exc

    title = path.stem
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._-") or "pdf"
    render_root = ocr_output_dir / f"{safe_name}_{_sha256_text(str(path), length=10)}"
    render_root.mkdir(parents=True, exist_ok=True)
    documents: list[SourceDocument] = []
    with pymupdf.open(str(path)) as pdf_doc:  # type: ignore[attr-defined]
        matrix = pymupdf.Matrix(scale, scale)  # type: ignore[attr-defined]
        for page_index, page in enumerate(pdf_doc, start=1):
            image_path = render_root / f"page_{page_index:04d}.png"
            if not image_path.exists():
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(str(image_path))
            text = _clean_text(engine.ocr_image(image_path, language=language_tag))
            if _word_count(text) < 4:
                continue
            locator = f"{path.name}#ocr-page={page_index}"
            documents.append(
                SourceDocument(
                    source_id=_source_id("ocr_pdf", locator, title),
                    source_type="ocr_pdf",
                    title=title,
                    locator=locator,
                    section=f"ocr page {page_index}",
                    text=text,
                    origin_path=str(path),
                )
            )
    return documents


def _extract_pdf_with_windows_ocr(
    path: Path,
    *,
    ocr_output_dir: Path,
    language_tag: str,
    scale: float,
) -> list[SourceDocument]:
    """Extract page-level OCR text using the shared Windows OCR adapter."""

    engine = _select_core_ocr_engine("windows", language_tag=language_tag)
    if engine is None:
        raise RuntimeError("Windows OCR engine is unavailable")
    return _extract_pdf_with_ocr_engine(
        path,
        ocr_output_dir=ocr_output_dir,
        language_tag=language_tag,
        scale=scale,
        engine=engine,
    )


def extract_pdf(
    path: Path,
    *,
    ocr_engine: str = "none",
    ocr_output_dir: Path | None = None,
    ocr_language: str = "en-GB",
    ocr_scale: float = 2.0,
) -> list[SourceDocument]:
    """Extract readable PDF text with a primary and fallback backend.

    Args:
        path: Existing PDF path.
        ocr_engine: ``none``, ``auto``, or ``windows``. OCR runs only when
            normal text extraction returns no readable pages.
        ocr_output_dir: Directory for rendered page images when OCR is used.
        ocr_language: BCP-47 language tag for Windows OCR.
        ocr_scale: PyMuPDF render scale for OCR images.

    Returns:
        Page-level source documents with stable locators.

    Raises:
        FileNotFoundError: If the PDF path does not exist.
        ValueError: If the path is not a PDF file.
        RuntimeError: If no supported extraction backend is available.
    """

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {path}")
    try:
        documents = _extract_pdf_with_pymupdf(path)
    except Exception:
        documents = _extract_pdf_with_pypdf(path)
    if documents:
        return documents
    if ocr_engine == "none":
        return []
    if ocr_engine not in {"auto", "windows"}:
        raise ValueError(f"unsupported OCR engine: {ocr_engine}")
    if ocr_output_dir is None:
        raise ValueError("ocr_output_dir is required when OCR is enabled")
    if ocr_engine == "windows":
        return _extract_pdf_with_windows_ocr(
            path,
            ocr_output_dir=ocr_output_dir,
            language_tag=ocr_language,
            scale=ocr_scale,
        )
    engine = _select_core_ocr_engine(ocr_engine, language_tag=ocr_language)
    if engine is None:
        return []
    return _extract_pdf_with_ocr_engine(
        path,
        ocr_output_dir=ocr_output_dir,
        language_tag=ocr_language,
        scale=ocr_scale,
        engine=engine,
    )


def extract_text_file(path: Path) -> list[SourceDocument]:
    """Load a plain text or markdown file as one source document."""

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"text file not found: {path}")
    if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
        raise ValueError(f"expected .txt or .md text file: {path}")
    text = _clean_text(path.read_text(encoding="utf-8", errors="replace"))
    if _word_count(text) < 8:
        return []
    title = path.stem
    locator = path.name
    return [
        SourceDocument(
            source_id=_source_id("text", locator, title),
            source_type="text",
            title=title,
            locator=locator,
            section="document",
            text=text,
            origin_path=str(path),
        )
    ]


def _html_to_sections(content: str, *, locator: str, title_fallback: str, origin_path: str) -> list[SourceDocument]:
    """Extract section-level text from one HTML document."""

    if not isinstance(content, str) or not content.strip():
        return []
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except Exception:
        plain = re.sub(r"<script\b.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
        plain = re.sub(r"<style\b.*?</style>", " ", plain, flags=re.IGNORECASE | re.DOTALL)
        plain = re.sub(r"<[^>]+>", " ", plain)
        text = _clean_text(plain)
        source_id = _source_id("phrasebank", locator, title_fallback)
        return [
            SourceDocument(
                source_id=source_id,
                source_type="phrasebank",
                title=title_fallback,
                locator=locator,
                section="document",
                text=text,
                origin_path=origin_path,
            )
        ] if _word_count(text) >= 8 else []

    soup = BeautifulSoup(content, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "form"]):
        element.decompose()
    title_node = soup.find(["h1", "title"])
    title = _clean_text(title_node.get_text(" ", strip=True)) if title_node else title_fallback
    body = soup.find("main") or soup.find("article") or soup.find(class_=re.compile("entry|content", re.I)) or soup.body or soup
    sections: list[SourceDocument] = []
    current_heading = "document"
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_parts
        text = _clean_text("\n".join(current_parts))
        if _word_count(text) >= 8:
            section_locator = f"{locator}#{_sha256_text(current_heading, length=8)}"
            sections.append(
                SourceDocument(
                    source_id=_source_id("phrasebank", section_locator, title),
                    source_type="phrasebank",
                    title=title,
                    locator=section_locator,
                    section=current_heading,
                    text=text,
                    origin_path=origin_path,
                )
            )
        current_parts = []

    for node in body.find_all(["h1", "h2", "h3", "h4", "p", "li"], recursive=True):
        text = _clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if node.name in {"h1", "h2", "h3", "h4"}:
            flush()
            current_heading = text[:160]
        else:
            current_parts.append(text)
    flush()
    return sections


def _extract_links(content: str, *, base_url: str) -> list[str]:
    """Extract same-site links from HTML for bounded Phrasebank crawling."""

    if _looks_like_xml_document(content):
        return []
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except Exception:
        hrefs = re.findall(r"href=[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE)
    else:
        soup = BeautifulSoup(content, "html.parser")
        hrefs = [str(a.get("href", "")) for a in soup.find_all("a")]

    base = urlparse(base_url)
    links: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urldefrag(urljoin(base_url, href))[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != base.netloc:
            continue
        lowered_path = parsed.path.lower()
        if any(lowered_path.endswith(suffix) for suffix in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".xml")):
            continue
        if lowered_path.endswith("/feed/") or "/wp-json/" in lowered_path:
            continue
        normalized = absolute.rstrip("/") + "/"
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


def _looks_like_xml_document(content: str) -> bool:
    """Return true for XML feeds or sitemaps that should not be parsed as HTML."""

    if not isinstance(content, str):
        raise TypeError("content must be a string")
    prefix = content.lstrip()[:240].lower()
    return (
        prefix.startswith("<?xml")
        or "<urlset" in prefix
        or "<rss" in prefix
        or "<feed" in prefix
        or "<rdf:rdf" in prefix
    )


def _fetch_url(url: str, *, timeout: float) -> str:
    """Fetch one URL as UTF-8-ish text with a bounded timeout."""

    if not url.startswith(("http://", "https://")):
        raise ValueError(f"unsupported URL: {url}")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    request = Request(
        url,
        headers={
            "User-Agent": "ScholarAI-AcademicEnglishDiscourseBuilder/0.1 (+local user workspace)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - user supplied public URL, bounded local builder.
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def crawl_phrasebank(base_url: str, *, max_pages: int, timeout: float) -> list[SourceDocument]:
    """Fetch and section the public Academic Phrasebank website.

    Args:
        base_url: Starting URL for Phrasebank.
        max_pages: Maximum same-site HTML pages to fetch.
        timeout: Per-request timeout in seconds.

    Returns:
        Section-level source documents extracted from fetched pages.

    Raises:
        ValueError: If bounds are invalid.
    """

    if max_pages < 1 or max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    queue: deque[str] = deque([base_url.rstrip("/") + "/"])
    visited: set[str] = set()
    documents: list[SourceDocument] = []

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            content = _fetch_url(url, timeout=timeout)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        if _looks_like_xml_document(content):
            continue
        documents.extend(
            _html_to_sections(
                content,
                locator=url,
                title_fallback="Academic Phrasebank",
                origin_path=url,
            )
        )
        for link in _extract_links(content, base_url=base_url):
            if link not in visited and len(visited) + len(queue) < max_pages * 2:
                queue.append(link)
        time.sleep(0.05)
    return documents


def extract_phrasebank_html_dir(path: Path) -> list[SourceDocument]:
    """Extract Phrasebank-like sections from local HTML fixtures or saved pages."""

    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"HTML directory not found: {path}")
    documents: list[SourceDocument] = []
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in {".html", ".htm"}:
            continue
        content = file_path.read_text(encoding="utf-8", errors="replace")
        documents.extend(
            _html_to_sections(
                content,
                locator=file_path.relative_to(path).as_posix(),
                title_fallback=file_path.stem,
                origin_path=str(file_path),
            )
        )
    return documents


def build_chunks(
    documents: Sequence[SourceDocument],
    *,
    chunk_size: int,
    chunk_overlap: int,
    distilled_only: bool,
) -> list[DiscourseChunk]:
    """Create discourse chunks from extracted documents."""

    if not documents:
        return []
    chunks: list[DiscourseChunk] = []
    seen_ids: set[str] = set()
    for document in documents:
        source_hash = _sha256_text_full(document.text)
        source_path = f"source:{Path(document.origin_path).name}" if Path(document.origin_path).name else document.origin_path
        next_span_hint = 0
        for index, text in enumerate(_recursive_chunks(document.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
            moves = _detect_moves(text)
            features = _detect_features(text)
            chunk_id = "chunk_" + _sha256_text(
                "|".join([document.source_id, document.locator, str(index), text]),
                length=20,
            )
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            span_start, span_end = _text_span(document.text, text, start_hint=next_span_hint)
            next_span_hint = max(span_start, span_end - chunk_overlap)
            chunks.append(
                DiscourseChunk(
                    chunk_id=chunk_id,
                    source_id=document.source_id,
                    source_type=document.source_type,
                    source_path=source_path,
                    source_hash=source_hash,
                    title=document.title,
                    locator=document.locator,
                    section=document.section,
                    text="" if distilled_only else text,
                    summary=_summary(text),
                    content_hash=_sha256_text_full(text),
                    span_start=span_start,
                    span_end=span_end,
                    rhetorical_moves=moves,
                    features=features,
                    keywords=_keywords(text),
                    char_count=len(text),
                    word_count=_word_count(text),
                )
            )
    return chunks


def _candidate_phrases_from_sentence(sentence: str, *, source_type: str) -> list[str]:
    """Extract reusable academic wording candidates from one sentence."""

    cleaned = _clean_text(sentence)
    if _word_count(cleaned) < 4:
        return []
    if source_type == "phrasebank":
        if _word_count(cleaned) <= 30:
            return [cleaned]
        return []

    patterns = (
        r"\b(?:however|nevertheless|despite|although|whereas|while|in contrast)[^.;]{10,160}",
        r"\b(?:these findings|this suggests|this indicates|taken together)[^.;]{10,160}",
        r"\b(?:previous studies|prior work|the literature)[^.;]{10,160}",
        r"\b(?:this paper|this study|this review|we)\s+(?:aim|argue|show|propose|examine|review)[^.;]{10,160}",
        r"\b(?:may|might|could|appears? to|is likely to)[^.;]{10,160}",
    )
    phrases: list[str] = []
    for pattern in patterns:
        phrases.extend(match.group(0).strip(" ,;:") for match in re.finditer(pattern, cleaned, re.IGNORECASE))
    return [phrase for phrase in phrases if 4 <= _word_count(phrase) <= 28]


def build_phrases(documents: Sequence[SourceDocument]) -> list[PhraseCandidate]:
    """Create phrase-pattern records from local source documents."""

    phrases: list[PhraseCandidate] = []
    seen_normalized: set[str] = set()
    for document in documents:
        source_hash = _sha256_text_full(document.text)
        source_path = f"source:{Path(document.origin_path).name}" if Path(document.origin_path).name else document.origin_path
        next_span_hint = 0
        for sentence in _sentences(document.text):
            sentence_start, sentence_end = _text_span(document.text, sentence, start_hint=next_span_hint)
            next_span_hint = max(sentence_start, sentence_end)
            for phrase in _candidate_phrases_from_sentence(sentence, source_type=document.source_type):
                normalized = re.sub(r"\s+", " ", phrase.lower()).strip()
                if normalized in seen_normalized:
                    continue
                moves = _detect_moves(phrase)
                move = moves[0] if moves else "general_academic_prose"
                features = _detect_features(phrase)
                phrase_id = "phrase_" + _sha256_text(
                    "|".join([document.source_id, document.locator, normalized]),
                    length=20,
                )
                seen_normalized.add(normalized)
                span_start, span_end = _text_span(document.text, phrase, start_hint=sentence_start)
                phrases.append(
                    PhraseCandidate(
                        phrase_id=phrase_id,
                        source_id=document.source_id,
                        source_type=document.source_type,
                        source_path=source_path,
                        source_hash=source_hash,
                        text=phrase,
                        normalized=normalized,
                        content_hash=_sha256_text_full(phrase),
                        span_start=span_start,
                        span_end=span_end,
                        move=move,
                        features=features,
                        section=document.section,
                        locator=document.locator,
                        adaptation_note=_adaptation_note(move, features),
                    )
                )
    return phrases


def discourse_frames() -> list[dict[str, Any]]:
    """Return curated discourse frames used as fallback guidance."""

    return [
        {
            "move": "territory",
            "cn_name": "建立研究领域",
            "purpose": "Introduce the research area and why it matters.",
            "when_to_use": "Opening a paragraph, section, or review topic.",
            "translation_strategy": "先给研究对象，再给重要性或发展趋势，避免直接从中文背景铺陈开始。",
            "quality_checks": ["scope is clear", "importance is not exaggerated", "topic terms are stable"],
            "starter_patterns": [
                "Research on {topic} has increasingly focused on {focus}.",
                "{Topic} plays a central role in {field/context}.",
            ],
        },
        {
            "move": "gap",
            "cn_name": "指出研究缺口",
            "purpose": "Mark what remains unknown, contested, or methodologically limited.",
            "when_to_use": "After summarizing prior work or before stating the aim.",
            "translation_strategy": "把'不足/尚未'翻译成具体的 evidence boundary，不要只写 is insufficient。",
            "quality_checks": ["gap is specific", "prior work is represented fairly", "claim is not absolute unless justified"],
            "starter_patterns": [
                "However, little is known about {specific issue}.",
                "Despite these advances, {problem} remains unclear.",
            ],
        },
        {
            "move": "aim",
            "cn_name": "说明本文目的",
            "purpose": "State what this paper, study, review, or section does.",
            "when_to_use": "End of introduction or paragraph transition into the present work.",
            "translation_strategy": "用研究动作动词承接缺口，如 examine, evaluate, synthesize, propose。",
            "quality_checks": ["verb matches task", "object is explicit", "claim does not preview unsupported result"],
            "starter_patterns": [
                "This study examines {object} in order to {purpose}.",
                "Here, we synthesize evidence on {topic} with a focus on {focus}.",
            ],
        },
        {
            "move": "citation",
            "cn_name": "引用与归因",
            "purpose": "Attribute claims and synthesize sources without source-by-source listing.",
            "when_to_use": "Literature review and background sections.",
            "translation_strategy": "把中文'有研究表明'具体化为 claim + source relation。",
            "quality_checks": ["citation supports exact claim", "synthesis relation is explicit", "reporting verb is accurate"],
            "starter_patterns": [
                "Several studies have linked {factor} to {outcome}.",
                "Prior work has primarily examined {topic} through {approach}.",
            ],
        },
        {
            "move": "comparison",
            "cn_name": "比较与综合",
            "purpose": "Show convergence, divergence, extension, or contrast across sources.",
            "when_to_use": "When moving from annotated bibliography style to synthesis.",
            "translation_strategy": "优先翻译研究之间的关系，而不是逐句翻译每篇文献做了什么。",
            "quality_checks": ["comparison basis is shared", "contrast is meaningful", "connector matches relation"],
            "starter_patterns": [
                "In contrast to {study/group}, {study/group} emphasizes {focus}.",
                "These findings converge on {shared claim}, but differ in {dimension}.",
            ],
        },
        {
            "move": "result",
            "cn_name": "报告结果",
            "purpose": "Report findings with calibrated certainty.",
            "when_to_use": "Results, abstract, or literature-review synthesis.",
            "translation_strategy": "区分 observed/found/showed/suggested，避免所有结果都写 prove。",
            "quality_checks": ["tense fits source", "statistics are attached", "certainty is calibrated"],
            "starter_patterns": [
                "The results indicate that {finding}.",
                "{Measure} was higher in {condition} than in {comparison}.",
            ],
        },
        {
            "move": "interpretation",
            "cn_name": "解释发现",
            "purpose": "Explain what a result implies without overstating causality.",
            "when_to_use": "Discussion sections and synthesis paragraphs.",
            "translation_strategy": "中文'说明'常需按证据强度译为 suggest/indicate/may reflect。",
            "quality_checks": ["inference is bounded", "mechanism is marked as mechanism", "alternative explanations are not erased"],
            "starter_patterns": [
                "Taken together, these findings suggest that {interpretation}.",
                "This pattern may reflect {mechanism_or_condition}.",
            ],
        },
        {
            "move": "limitation",
            "cn_name": "范围与限制",
            "purpose": "Mark limits of data, method, population, or inference.",
            "when_to_use": "Discussion, review evaluation, and translation of cautious Chinese claims.",
            "translation_strategy": "不要只写 has limitations；说明限制来自样本、方法、语境还是推断。",
            "quality_checks": ["limit source is explicit", "does not invalidate entire study", "future work follows logically"],
            "starter_patterns": [
                "These findings should be interpreted in light of {limitation}.",
                "Because {boundary}, the results may not generalize to {scope}.",
            ],
        },
    ]


def _habit_policy_path() -> Path:
    """Return the package-local Markdown policy path.

    Returns:
        Absolute path to the authoritative human-readable academic-English policy.
    """

    return Path(__file__).resolve().parent.parent / "references" / "english_discourse_habits.md"


def _read_habit_policy_markdown(policy_path: Path) -> tuple[str, str, bool]:
    """Read the authoritative Markdown policy without making it mandatory.

    Args:
        policy_path: Absolute or relative path to the Markdown policy file.

    Returns:
        Tuple of policy markdown, source label, and load status. Missing files
        degrade to an empty policy so database builds remain recoverable.
    """

    if not isinstance(policy_path, Path):
        raise TypeError("policy_path must be a pathlib.Path")
    if not policy_path.exists():
        return "", "", False
    if not policy_path.is_file():
        return "", "", False
    return policy_path.read_text(encoding="utf-8"), "references/english_discourse_habits.md", True


def _policy_load_status(policy_path: Path, *, loaded: bool) -> str:
    """Classify the authoritative habit policy source for manifest gates."""

    if not isinstance(policy_path, Path):
        raise TypeError("policy_path must be a pathlib.Path")
    if loaded:
        return "loaded"
    if not policy_path.exists():
        return "missing"
    if not policy_path.is_file():
        return "not_file"
    return "unloaded"


def academic_english_habits() -> dict[str, Any]:
    """Return distilled academic-English thinking rules for writing and translation.

    Returns:
        A JSON-serializable knowledge object. It contains local, source-informed
        abstractions only and must not contain copied source passages.
    """

    policy_path = _habit_policy_path()
    policy_markdown, policy_source, policy_loaded = _read_habit_policy_markdown(policy_path)
    policy_content_hash = _sha256_text_full(policy_markdown) if policy_loaded else ""
    return {
        "schema_version": SCHEMA_VERSION,
        "knowledge_type": "academic_english_habits",
        "policy_markdown": policy_markdown,
        "policy_source": policy_source,
        "policy_source_path": str(policy_path),
        "policy_loaded": policy_loaded,
        "policy_load_status": _policy_load_status(policy_path, loaded=policy_loaded),
        "policy_content_hash": policy_content_hash,
        "policy_char_count": len(policy_markdown),
        "purpose": (
            "Help Scholar AI plan English academic prose by discourse function, "
            "information flow, evidential strength, and translation restructuring "
            "before selecting surface wording."
        ),
        "source_principles": [
            {
                "name": "move_step_argument",
                "cn_name": "话语动作先行",
                "principle": (
                    "Treat each sentence as a rhetorical move before choosing words: "
                    "establish territory, identify a niche, occupy the niche, report evidence, "
                    "interpret, limit, or transition."
                ),
                "application": "先判断句子在论文里的功能，再检索短语或生成英文。",
            },
            {
                "name": "old_to_new_information",
                "cn_name": "已知到新信息",
                "principle": (
                    "Begin from shared context or the previous sentence, then introduce the "
                    "new claim, contrast, evidence, or implication."
                ),
                "application": "把中文的主题铺陈改写为英语的 context -> claim -> evidence/scope。",
            },
            {
                "name": "claim_evidence_scope",
                "cn_name": "主张-证据-范围",
                "principle": (
                    "A scholarly sentence should reveal what is claimed, what supports it, "
                    "and how far the claim can travel."
                ),
                "application": "生成时显式绑定 citation、dataset、method、population 或 boundary。",
            },
            {
                "name": "calibrated_certainty",
                "cn_name": "确定性校准",
                "principle": (
                    "Match verbs and modality to evidence strength: direct observations can be "
                    "reported firmly; inference, mechanism, and generalization require caution."
                ),
                "application": "不要把 suggest/indicate/show/demonstrate/prove 混用。",
            },
            {
                "name": "stable_terms",
                "cn_name": "术语稳定",
                "principle": (
                    "One concept should keep one English term across a draft unless the writer "
                    "is intentionally marking a conceptual distinction."
                ),
                "application": "中英翻译先建立术语表，再改句子，不为流畅而漂移术语。",
            },
            {
                "name": "synthesis_over_listing",
                "cn_name": "综合优先于罗列",
                "principle": (
                    "A literature review should express relations among studies rather than "
                    "presenting one citation per isolated sentence."
                ),
                "application": "优先生成 convergence/divergence/extension/challenge 的关系句。",
            },
        ],
        "sentence_diagnostics": [
            {
                "check": "discourse_move",
                "question": "What is this sentence doing in the argument?",
                "reject_if": "It merely sounds fluent but has no identifiable academic function.",
            },
            {
                "check": "subject_and_action",
                "question": "Who or what performs the scholarly action?",
                "reject_if": "The English hides the actor, object, or analytical relation without reason.",
            },
            {
                "check": "certainty",
                "question": "Does the verb strength match the evidence?",
                "reject_if": "A limited observation is written as proof or a settled fact is over-hedged.",
            },
            {
                "check": "citation_attachment",
                "question": "Is the citation attached to the exact claim it supports?",
                "reject_if": "The citation floats at paragraph end or supports only part of the sentence.",
            },
            {
                "check": "information_flow",
                "question": "Does the sentence connect old information to new information?",
                "reject_if": "The paragraph jumps topics without a transition relation.",
            },
        ],
        "translation_rewrite_rules": [
            {
                "cn_pattern": "由于/随着/在...背景下 + 很长背景 + 本文",
                "english_strategy": "Move the research object or problem into subject position early, then attach context as scope.",
                "template": "Against this background, this study examines {object} in {scope}.",
            },
            {
                "cn_pattern": "说明/表明/证明",
                "english_strategy": "Choose suggests, indicates, shows, or demonstrates according to evidence strength.",
                "template": "These findings {evidence_verb} that {claim}.",
            },
            {
                "cn_pattern": "目前研究较少/不足",
                "english_strategy": "Specify what is underexamined: population, method, mechanism, dataset, theory, or context.",
                "template": "However, little is known about {specific_gap} in {scope}.",
            },
            {
                "cn_pattern": "有学者认为/已有研究发现",
                "english_strategy": "Replace vague attribution with a reporting verb and a synthesis relation.",
                "template": "Prior studies have {reporting_verb} {claim}, particularly in {context}.",
            },
            {
                "cn_pattern": "具有重要意义",
                "english_strategy": "State the academic or practical implication instead of using generic importance.",
                "template": "This distinction matters because it {specific_implication}.",
            },
            {
                "cn_pattern": "但是/然而",
                "english_strategy": "Name the contrast relation: limitation, contradiction, exception, or unresolved scope.",
                "template": "However, this evidence is limited by {boundary}.",
            },
        ],
        "paragraph_protocols": [
            {
                "name": "literature_review_synthesis",
                "steps": [
                    "Introduce the shared topic or construct.",
                    "Group prior studies by relation, method, population, or finding.",
                    "State convergence or divergence across groups.",
                    "Name the precise gap or unresolved boundary.",
                    "End with why the next paragraph or present study is needed.",
                ],
                "avoid": [
                    "one-citation-one-sentence listing",
                    "generic praise such as important or significant without consequence",
                    "unsupported global claims about all studies",
                ],
            },
            {
                "name": "chinese_to_english_academic_paragraph",
                "steps": [
                    "Identify the paragraph's dominant move.",
                    "Build a term map for recurring concepts.",
                    "Reorder topic-comment sentences into English claim-support order.",
                    "Calibrate evidential verbs and modality.",
                    "Add restrained connectors only where the logical relation is real.",
                ],
                "avoid": [
                    "literal connector translation",
                    "synonym drift for technical nouns",
                    "turning every Chinese '说明' into demonstrates",
                ],
            },
            {
                "name": "discussion_interpretation",
                "steps": [
                    "Restate the main finding without repeating all numbers.",
                    "Interpret the mechanism or theoretical meaning cautiously.",
                    "Compare with prior work.",
                    "Mark alternative explanations or limits.",
                    "Close with implication or future work.",
                ],
                "avoid": [
                    "causal overstatement from correlational evidence",
                    "unsupported mechanism claims",
                    "limitations that invalidate the entire contribution",
                ],
            },
        ],
        "lexical_calibration": {
            "weak_inference": ["may", "might", "could", "appears to", "is likely to"],
            "evidence_suggestion": ["suggests", "indicates", "points to", "is consistent with"],
            "direct_observation": ["shows", "reveals", "was observed", "was associated with"],
            "strong_evidence": ["demonstrates", "establishes"],
            "avoid_without_decisive_evidence": ["proves", "confirms", "fully explains"],
            "synthesis_verbs": ["converge", "diverge", "extend", "challenge", "corroborate", "complicate"],
            "reporting_verbs": ["argues", "reports", "finds", "observes", "proposes", "attributes"],
        },
        "quality_floor": [
            "Every generated paragraph must have a visible discourse arc.",
            "Every citation-sensitive claim must remain evidence-bound.",
            "Every translated technical term must be stable unless intentionally contrasted.",
            "Every hedge must reflect uncertainty, not timid style.",
            "Every connector must encode a real relation.",
        ],
    }


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    """Write JSON Lines records and return the number of rows written."""

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _json_dump(value: Any) -> str:
    """Serialize nested values for SQLite text columns."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_sqlite(path: Path, sources: Sequence[SourceDocument], chunks: Sequence[DiscourseChunk], phrases: Sequence[PhraseCandidate]) -> None:
    """Write the searchable SQLite mirror with optional FTS5 tables."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(
            """
            CREATE TABLE sources (
                source_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                locator TEXT NOT NULL,
                section TEXT NOT NULL,
                origin_path TEXT NOT NULL
            );
            CREATE TABLE chunks (
                rowid INTEGER PRIMARY KEY,
                chunk_id TEXT UNIQUE NOT NULL,
                source_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                locator TEXT NOT NULL,
                section TEXT NOT NULL,
                text TEXT NOT NULL,
                summary TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                span_start INTEGER NOT NULL,
                span_end INTEGER NOT NULL,
                rhetorical_moves TEXT NOT NULL,
                features TEXT NOT NULL,
                keywords TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                word_count INTEGER NOT NULL
            );
            CREATE TABLE phrases (
                rowid INTEGER PRIMARY KEY,
                phrase_id TEXT UNIQUE NOT NULL,
                source_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                span_start INTEGER NOT NULL,
                span_end INTEGER NOT NULL,
                move TEXT NOT NULL,
                features TEXT NOT NULL,
                section TEXT NOT NULL,
                locator TEXT NOT NULL,
                adaptation_note TEXT NOT NULL
            );
            CREATE TABLE build_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        source_rows = {
            source.source_id: (
                source.source_id,
                source.source_type,
                source.title,
                source.locator,
                source.section,
                source.origin_path,
            )
            for source in sources
        }
        conn.executemany(
            "INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?)",
            sorted(source_rows.values()),
        )
        conn.executemany(
            """
            INSERT INTO chunks (
                chunk_id, source_id, source_type, source_path, source_hash, title,
                locator, section, text, summary, content_hash, span_start, span_end,
                rhetorical_moves, features, keywords, char_count, word_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.source_type,
                    chunk.source_path,
                    chunk.source_hash,
                    chunk.title,
                    chunk.locator,
                    chunk.section,
                    chunk.text,
                    chunk.summary,
                    chunk.content_hash,
                    chunk.span_start,
                    chunk.span_end,
                    _json_dump(chunk.rhetorical_moves),
                    _json_dump(chunk.features),
                    _json_dump(chunk.keywords),
                    chunk.char_count,
                    chunk.word_count,
                )
                for chunk in chunks
            ],
        )
        conn.executemany(
            """
            INSERT INTO phrases (
                phrase_id, source_id, source_type, source_path, source_hash, text,
                normalized, content_hash, span_start, span_end, move, features,
                section, locator, adaptation_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    phrase.phrase_id,
                    phrase.source_id,
                    phrase.source_type,
                    phrase.source_path,
                    phrase.source_hash,
                    phrase.text,
                    phrase.normalized,
                    phrase.content_hash,
                    phrase.span_start,
                    phrase.span_end,
                    phrase.move,
                    _json_dump(phrase.features),
                    phrase.section,
                    phrase.locator,
                    phrase.adaptation_note,
                )
                for phrase in phrases
            ],
        )
        conn.executemany(
            "INSERT INTO build_meta VALUES (?, ?)",
            [
                ("schema_version", SCHEMA_VERSION),
                ("builder_version", BUILDER_VERSION),
                ("built_at", _utc_now()),
            ],
        )
        try:
            conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id, title, section, text, summary, keywords)")
            conn.execute("CREATE VIRTUAL TABLE phrases_fts USING fts5(phrase_id, text, normalized, move, section, adaptation_note)")
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, chunk_id, title, section, text, summary, keywords)
                SELECT rowid, chunk_id, title, section, text, summary, keywords FROM chunks
                """
            )
            conn.execute(
                """
                INSERT INTO phrases_fts(rowid, phrase_id, text, normalized, move, section, adaptation_note)
                SELECT rowid, phrase_id, text, normalized, move, section, adaptation_note FROM phrases
                """
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()


def _artifact_metadata(path: Path | None, *, rows: int | None = None, status: str = "written") -> dict[str, Any]:
    """Return machine-readable generated-artifact provenance."""

    if path is not None and not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path or None")
    if rows is not None and rows < 0:
        raise ValueError("rows must be non-negative")
    if not isinstance(status, str) or not status:
        raise ValueError("status must be a non-empty string")
    if path is None:
        metadata: dict[str, Any] = {
            "path": "",
            "exists": False,
            "bytes": 0,
            "sha256": "",
            "status": status,
        }
    else:
        exists = path.exists() and path.is_file()
        metadata = {
            "path": str(path),
            "exists": exists,
            "bytes": path.stat().st_size if exists else 0,
            "sha256": _sha256_file(path) if exists else "",
            "status": status if exists else "missing",
        }
    if rows is not None:
        metadata["rows"] = rows
    return metadata


def _source_summary(sources: Sequence[SourceDocument]) -> list[dict[str, Any]]:
    """Return compact source metadata for the build manifest."""

    grouped: dict[str, dict[str, Any]] = {}
    for source in sources:
        item = grouped.setdefault(
            source.origin_path,
            {
                "origin_path": source.origin_path,
                "source_type": source.source_type,
                "title": source.title,
                "sections": 0,
                "words": 0,
                "source_hash": "",
                "_texts": [],
            },
        )
        item["sections"] = int(item["sections"]) + 1
        item["words"] = int(item["words"]) + _word_count(source.text)
        texts = item.get("_texts")
        if isinstance(texts, list):
            texts.append(source.text)
    summaries: list[dict[str, Any]] = []
    for item in grouped.values():
        texts = item.pop("_texts", [])
        item["source_hash"] = _sha256_text_full("\n\n".join(texts)) if isinstance(texts, list) else ""
        summaries.append(item)
    return sorted(summaries, key=lambda item: (str(item["source_type"]), str(item["origin_path"])))


def write_report(path: Path, manifest: Mapping[str, Any]) -> None:
    """Write a human-readable build report."""

    counts = manifest.get("counts", {})
    sources = manifest.get("sources", [])
    lines = [
        "# Academic English Discourse Build Report",
        "",
        f"- Built at: {manifest.get('built_at', '')}",
        f"- Schema version: {manifest.get('schema_version', '')}",
        f"- Sources: {counts.get('sources', 0)}",
        f"- Chunks: {counts.get('chunks', 0)}",
        f"- Phrases: {counts.get('phrases', 0)}",
        f"- Habit principles: {counts.get('habit_principles', 0)}",
        "",
        "## Sources",
        "",
    ]
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            lines.append(
                f"- {source.get('source_type', '')}: {source.get('title', '')} "
                f"({source.get('sections', 0)} sections, {source.get('words', 0)} words)"
            )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def collect_download_preset() -> list[Path]:
    """Return existing default PDFs from the user's Downloads directory."""

    downloads = Path.home() / "Downloads"
    return [downloads / name for name in DEFAULT_DOWNLOAD_FILENAMES if (downloads / name).exists()]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments for the database builder."""

    parser = argparse.ArgumentParser(
        description="Build the Scholar AI academic-English discourse database.",
    )
    parser.add_argument("--pdf", action="append", default=[], help="PDF source path. Can be provided multiple times.")
    parser.add_argument("--text", action="append", default=[], help="UTF-8 text or markdown source path. Can be provided multiple times.")
    parser.add_argument("--downloads-preset", action="store_true", help="Use the known writing-science PDFs from ~/Downloads when present.")
    parser.add_argument("--include-phrasebank", action="store_true", help="Fetch Academic Phrasebank pages from the web.")
    parser.add_argument("--phrasebank-url", default=DEFAULT_PHRASEBANK_URL, help="Academic Phrasebank base URL.")
    parser.add_argument("--phrasebank-html-dir", default="", help="Local directory of saved Phrasebank-like HTML pages.")
    parser.add_argument("--output-dir", default=str(_default_output_dir()), help="Output directory for generated DB files.")
    parser.add_argument("--chunk-size", type=int, default=900, help="Target chunk size in characters.")
    parser.add_argument("--chunk-overlap", type=int, default=160, help="Character overlap between chunks.")
    parser.add_argument("--max-phrasebank-pages", type=int, default=80, help="Maximum Phrasebank pages to fetch.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request Phrasebank timeout in seconds.")
    parser.add_argument("--distilled-only", action="store_true", help="Omit raw chunk text from generated chunk records.")
    parser.add_argument(
        "--ocr-engine",
        choices=("none", "auto", "windows"),
        default="auto",
        help="OCR backend for PDFs with no extractable text. auto uses Windows OCR when available.",
    )
    parser.add_argument("--ocr-language", default="en-GB", help="BCP-47 OCR language tag for Windows OCR.")
    parser.add_argument("--ocr-scale", type=float, default=2.0, help="PDF render scale for OCR fallback images.")
    parser.add_argument("--no-sqlite", action="store_true", help="Skip SQLite generation.")
    return parser.parse_args(list(argv))


def _coerce_paths(values: Sequence[str]) -> list[Path]:
    """Resolve CLI path values into absolute paths."""

    paths: list[Path] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        paths.append(Path(raw).expanduser().resolve())
    return paths


def build_database(args: argparse.Namespace) -> dict[str, Any]:
    """Build all local discourse artifacts from parsed CLI arguments."""

    chunk_size = int(args.chunk_size)
    chunk_overlap = int(args.chunk_overlap)
    if chunk_size < 120:
        raise ValueError("--chunk-size must be at least 120")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("--chunk-overlap must be non-negative and smaller than --chunk-size")

    output_dir = Path(str(args.output_dir)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ocr_engine = str(args.ocr_engine)
    ocr_language = str(args.ocr_language)
    ocr_scale = float(args.ocr_scale)
    if ocr_scale < 1.0 or ocr_scale > 4.0:
        raise ValueError("--ocr-scale must be between 1.0 and 4.0")

    pdf_paths = _coerce_paths(args.pdf)
    if bool(args.downloads_preset):
        pdf_paths.extend(collect_download_preset())
    text_paths = _coerce_paths(args.text)

    documents: list[SourceDocument] = []
    errors: list[str] = []
    warnings: list[str] = []
    for pdf_path in dict.fromkeys(pdf_paths):
        try:
            extracted = extract_pdf(
                pdf_path,
                ocr_engine=ocr_engine,
                ocr_output_dir=output_dir / "ocr_pages",
                ocr_language=ocr_language,
                ocr_scale=ocr_scale,
            )
            if not extracted:
                warnings.append(f"{pdf_path}: no extractable text found; OCR may be required")
            documents.extend(extracted)
        except Exception as exc:
            errors.append(f"{pdf_path}: {exc}")
    for text_path in dict.fromkeys(text_paths):
        try:
            documents.extend(extract_text_file(text_path))
        except Exception as exc:
            errors.append(f"{text_path}: {exc}")
    phrasebank_html_dir = str(args.phrasebank_html_dir).strip()
    if phrasebank_html_dir:
        documents.extend(extract_phrasebank_html_dir(Path(phrasebank_html_dir).expanduser().resolve()))
    if bool(args.include_phrasebank):
        documents.extend(
            crawl_phrasebank(
                str(args.phrasebank_url),
                max_pages=int(args.max_phrasebank_pages),
                timeout=float(args.timeout),
            )
        )

    if not documents:
        detail = "; ".join(errors) if errors else "no readable source documents were provided"
        raise RuntimeError(f"database build has no input documents: {detail}")

    settings = BuildSettings(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        max_phrasebank_pages=int(args.max_phrasebank_pages),
        distilled_only=bool(args.distilled_only),
        include_phrasebank=bool(args.include_phrasebank),
        ocr_engine=ocr_engine,
        ocr_language=ocr_language,
        ocr_scale=ocr_scale,
    )
    chunks = build_chunks(
        documents,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        distilled_only=settings.distilled_only,
    )
    phrases = build_phrases(documents)
    frames = discourse_frames()
    habits = academic_english_habits()
    if not habits.get("policy_loaded"):
        warnings.append("english_discourse_habits.md missing; policy_markdown is empty")

    chunks_path = output_dir / "chunks.jsonl"
    phrases_path = output_dir / "phrases.jsonl"
    frames_path = output_dir / "discourse_frames.json"
    habits_path = output_dir / "academic_english_habits.json"
    sqlite_path = output_dir / "academic_english_discourse.sqlite3"
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "build_report.md"

    chunk_rows = write_jsonl(chunks_path, (asdict(chunk) for chunk in chunks))
    phrase_rows = write_jsonl(phrases_path, (asdict(phrase) for phrase in phrases))
    frames_path.write_text(json.dumps(frames, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    habits_path.write_text(json.dumps(habits, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not bool(args.no_sqlite):
        write_sqlite(sqlite_path, documents, chunks, phrases)

    outputs = {
        "chunks_jsonl": str(chunks_path),
        "phrases_jsonl": str(phrases_path),
        "discourse_frames_json": str(frames_path),
        "academic_english_habits_json": str(habits_path),
        "sqlite": "" if bool(args.no_sqlite) else str(sqlite_path),
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "built_at": _utc_now(),
        "sources": _source_summary(documents),
        "counts": {
            "source_sections": len(documents),
            "sources": len({source.origin_path for source in documents}),
            "chunks": len(chunks),
            "phrases": len(phrases),
            "frames": len(frames),
            "habit_principles": len(habits.get("source_principles", [])),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
        "outputs": outputs,
        "write_counts": {
            "chunks": chunk_rows,
            "phrases": phrase_rows,
        },
        "knowledge_sources": {
            "academic_english_habits": {
                "source_path": str(habits.get("policy_source_path", "")),
                "source_label": str(habits.get("policy_source", "")),
                "loaded": bool(habits.get("policy_loaded", False)),
                "load_status": str(habits.get("policy_load_status", "missing")),
                "content_hash": str(habits.get("policy_content_hash", "")),
                "char_count": int(habits.get("policy_char_count", 0)),
            }
        },
        "output_artifacts": {
            "chunks_jsonl": _artifact_metadata(chunks_path, rows=chunk_rows),
            "phrases_jsonl": _artifact_metadata(phrases_path, rows=phrase_rows),
            "discourse_frames_json": _artifact_metadata(frames_path),
            "academic_english_habits_json": _artifact_metadata(habits_path),
            "sqlite": _artifact_metadata(None, status="disabled") if bool(args.no_sqlite) else _artifact_metadata(sqlite_path),
        },
        "settings": asdict(settings),
    }
    write_report(report_path, manifest)
    manifest["output_artifacts"]["report"] = _artifact_metadata(report_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument sequence. Uses ``sys.argv`` when omitted.

    Returns:
        Process exit code.
    """

    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        manifest = build_database(args)
    except Exception as exc:
        print(f"academic-english-discourse build failed: {exc}", file=sys.stderr)
        return 2
    counts = manifest.get("counts", {})
    outputs = manifest.get("outputs", {})
    print(
        "academic-english-discourse build complete: "
        f"{counts.get('chunks', 0)} chunks, {counts.get('phrases', 0)} phrases, "
        f"output={outputs.get('manifest', '')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
