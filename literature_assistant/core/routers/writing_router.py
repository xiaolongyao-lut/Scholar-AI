"""Writing API router - /api/writing/* aliases and extensions.

Provides user-friendly /api/writing/* endpoints that alias or extend
the existing /resources/* endpoints for writing projects, outlines,
citations, figures, and submissions.
"""

import asyncio
import inspect
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, TypedDict

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse

from models import (
    ProjectPayload,
    CreateProjectRequest,
    OutlineItemPayload,
    OutlinePayload,
    GenerateOutlineRequest,
    CitationSourcePayload,
    CitationSourceUpdate,
    CitationSuggestionPayload,
    SuggestCitationsRequest,
    FigureAssetPayload,
    CreateFigureAssetRequest,
    UpdateFigureAssetRequest,
    GenerateFigureAssetsRequest,
    GenerateFigureAssetsResponse,
    FigureTableCandidatePayload,
    SubmitForReviewRequest,
    SubmissionResponsePayload,
    ExportProjectRequest,
    ProjectExportPayload,
)

# Import resources router to reuse logic
import routers.resources_router as resources_router
from writing_resources import WritingMaterial

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/writing", tags=["Writing"])

_FIGURE_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}
_CITATION_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]+")
_CITATION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _figure_asset_payload(asset: Any) -> FigureAssetPayload:
    """Convert a persisted figure asset dataclass into the public API model."""
    if asset is None or not hasattr(asset, "to_dict"):
        raise HTTPException(status_code=500, detail="Invalid figure asset payload")
    return FigureAssetPayload(**asset.to_dict())


def _figure_asset_value(value: Any) -> Any:
    """Drop blank update values while preserving explicit non-empty updates."""
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized else None
    return value


def _figure_candidate_asset_path(candidate: FigureTableCandidatePayload) -> str:
    """Return the candidate asset path required for local generation."""
    asset_path = str(candidate.asset_path or "").strip()
    if not asset_path:
        raise HTTPException(
            status_code=400,
            detail="Only chunk-backed pixel candidates can be generated into figure assets",
        )
    return asset_path


def _candidate_to_create_asset_payload(
    request: GenerateFigureAssetsRequest,
    candidate: FigureTableCandidatePayload,
) -> dict[str, Any]:
    """Map one validated candidate to the existing asset creation contract."""
    asset_path = _figure_candidate_asset_path(candidate)
    caption = str(candidate.caption or "").strip() or f"{candidate.label}（切块图片）"
    numbering = str(candidate.label or "").strip()
    if not numbering:
        raise HTTPException(status_code=400, detail="Candidate label is required")
    return {
        "project_id": request.project_id,
        "kind": candidate.kind,
        "caption": caption,
        "numbering": numbering,
        "asset_path": asset_path,
        "material_id": candidate.material_id,
        "source_page": candidate.page,
        "bbox": candidate.bbox,
        "width": None,
        "height": None,
        "format": Path(asset_path).suffix.lstrip(".").lower() or None,
    }


def _path_is_inside(parent: Path, child: Path) -> bool:
    """Return true when ``child`` resolves under ``parent``."""
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _resolve_figure_file_path(project_id: str, asset_path: str) -> Path:
    """Resolve a project figure asset path without exposing arbitrary files."""
    normalized_project_id = str(project_id or "").strip()
    normalized_asset_path = str(asset_path or "").strip()
    if not normalized_project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if not normalized_asset_path:
        raise HTTPException(status_code=400, detail="path is required")
    if re.match(r"^[a-z][a-z0-9+.-]*://", normalized_asset_path, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Only local image asset paths can be served")

    from project_paths import REPO_ROOT, WORKSPACE_ARTIFACTS_ROOT, project_data_path

    project_root = project_data_path(normalized_project_id).resolve()
    workspace_root = WORKSPACE_ARTIFACTS_ROOT.resolve()
    repo_root = REPO_ROOT.resolve()
    source_folder_text = resources_router._get_project_source_folder(normalized_project_id)
    source_root = Path(source_folder_text).expanduser().resolve() if source_folder_text else None

    raw_path = Path(normalized_asset_path).expanduser()
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path.resolve())
    else:
        clean_relative = Path(*[part for part in raw_path.parts if part not in {"", ".", ".."}])
        candidates.extend([
            project_root / clean_relative,
            workspace_root / clean_relative,
            repo_root / clean_relative,
        ])
        if source_root is not None:
            candidates.append(source_root / clean_relative)

    allowed_roots = [project_root, workspace_root]
    if source_root is not None:
        allowed_roots.append(source_root)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.suffix.lower() not in _FIGURE_IMAGE_MEDIA_TYPES:
            continue
        if not resolved.is_file():
            continue
        if any(_path_is_inside(root, resolved) for root in allowed_roots):
            return resolved

    raise HTTPException(status_code=404, detail="图像文件不存在或不在项目允许目录内")


class _GeneratedOutlineItem(TypedDict):
    """Normalized outline item used before section persistence."""

    title: str
    description: str
    level: int
    parent_index: int | None


class _OutlineMaterialContext(TypedDict):
    """Bounded material context used for evidence-grounded outline generation."""

    material_id: str
    title: str
    summary: str
    focus_points: list[str]


def _coerce_outline_level(value: Any, default: int = 1) -> int:
    """Return a bounded Markdown heading level for API outline payloads."""
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = default
    return max(1, min(6, level))


def _clean_outline_title(value: Any, fallback: str) -> str:
    """Normalize model or fallback titles into compact section headings."""
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:#{1,6}\s*|\d+(?:\.\d+)*[.)、]?\s*|[-*•]\s*)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120] if text else fallback


def _clean_outline_description(value: Any) -> str:
    """Normalize optional section descriptions without leaking raw model noise."""
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text[:420]


def _bounded_outline_text(value: Any, *, max_chars: int) -> str:
    """Return compact text for outline prompts without unbounded source spill."""

    if not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_chars]


def _material_outline_summary(material: WritingMaterial, *, max_chars: int = 700) -> str:
    """Build a bounded source summary from material metadata.

    Args:
        material: Project-owned material record.
        max_chars: Maximum characters returned for prompt context.

    Returns:
        Compact summary text. Empty means the material has no usable summary.
    """

    parts = [
        getattr(material, "summary", ""),
        getattr(material, "summary_en", ""),
        "；".join(getattr(material, "focus_points", []) or []),
        "；".join(getattr(material, "focus_points_en", []) or []),
    ]
    summary = " ".join(_bounded_outline_text(part, max_chars=max_chars) for part in parts if str(part).strip())
    return _bounded_outline_text(summary, max_chars=max_chars)


def _chunk_outline_summary(project_id: str, material_id: str, *, max_chars: int = 700) -> str:
    """Return a bounded chunk-derived summary for materials without summaries."""

    if not project_id.strip() or not material_id.strip():
        return ""
    try:
        chunks = resources_router._load_chunk_store(project_id).get(material_id, [])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - outline generation must degrade to metadata when chunk store is unavailable.
        logger.info("Outline chunk context unavailable for material %s: %s", material_id, exc)
        return ""
    excerpts: list[str] = []
    for chunk in chunks[:3]:
        if not isinstance(chunk, Mapping):
            continue
        for key in ("summary", "abstract", "content", "text", "caption"):
            text = _bounded_outline_text(chunk.get(key), max_chars=260)
            if text:
                excerpts.append(text)
                break
        if sum(len(item) for item in excerpts) >= max_chars:
            break
    return _bounded_outline_text(" ".join(excerpts), max_chars=max_chars)


def _collect_outline_material_context(
    store: Any,
    request: GenerateOutlineRequest,
    *,
    max_materials: int = 12,
) -> list[_OutlineMaterialContext]:
    """Collect project-owned material summaries required for grounded outlines.

    Args:
        store: Writing resource store with ``get_material`` and ``list_materials``.
        request: Public outline-generation request.
        max_materials: Maximum source records included in the prompt.

    Returns:
        Bounded material context rows. The list is empty only when no usable
        project material evidence exists.
    """

    if not isinstance(max_materials, int) or max_materials < 1:
        raise ValueError("max_materials must be a positive integer")

    requested_ids = [str(item).strip() for item in request.existing_materials if str(item).strip()]
    if requested_ids:
        materials: list[WritingMaterial] = []
        for material_id in requested_ids[:max_materials]:
            material = store.get_material(material_id)
            if material is None:
                raise HTTPException(status_code=404, detail=f"Material not found: {material_id}")
            if material.project_id != request.project_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Material {material_id} does not belong to project {request.project_id}",
                )
            materials.append(material)
    else:
        materials = list(store.list_materials(request.project_id))[:max_materials]

    context: list[_OutlineMaterialContext] = []
    for material in materials:
        summary = _material_outline_summary(material)
        if not summary:
            summary = _chunk_outline_summary(request.project_id, material.material_id)
        title = _bounded_outline_text(material.title or material.title_en, max_chars=180)
        if not title or not summary:
            continue
        context.append(
            {
                "material_id": material.material_id,
                "title": title,
                "summary": summary,
                "focus_points": [
                    _bounded_outline_text(item, max_chars=80)
                    for item in (material.focus_points or material.focus_points_en or [])
                    if str(item).strip()
                ][:6],
            }
        )
    return context


def _format_outline_material_context(context: Sequence[_OutlineMaterialContext]) -> str:
    """Format material rows for an evidence-bounded outline prompt."""

    if not context:
        raise ValueError("context must contain at least one material row")
    lines: list[str] = []
    for index, item in enumerate(context, start=1):
        focus = f" Focus: {'; '.join(item['focus_points'])}." if item["focus_points"] else ""
        lines.append(
            f"{index}. [{item['material_id']}] {item['title']}: {item['summary']}{focus}"
        )
    return "\n".join(lines)


def _section_to_outline_item(section: Any) -> OutlineItemPayload:
    """Convert a stored section into the public outline item contract."""
    metadata = getattr(section, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    parent_id_raw = metadata.get("outline_parent_id")
    parent_id = str(parent_id_raw).strip() if parent_id_raw not in (None, "") else None
    section_id = str(getattr(section, "section_id"))
    return OutlineItemPayload(
        item_id=section_id,
        project_id=str(getattr(section, "project_id")),
        parent_id=parent_id,
        title=str(getattr(section, "title")),
        level=_coerce_outline_level(metadata.get("outline_level"), default=1),
        order=int(getattr(section, "order")),
        description=str(getattr(section, "description", "")),
        section_id=section_id,
        created_at=str(getattr(section, "created_at")),
        updated_at=str(getattr(section, "updated_at")),
    )


def _extract_json_candidate(text: str) -> str | None:
    """Extract the most likely JSON object or array from an LLM response."""
    normalized = text.strip()
    if not normalized:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", normalized, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        normalized = fenced.group(1).strip()
    if normalized.startswith("[") or normalized.startswith("{"):
        return normalized

    array_start = normalized.find("[")
    array_end = normalized.rfind("]")
    if 0 <= array_start < array_end:
        return normalized[array_start:array_end + 1]

    object_start = normalized.find("{")
    object_end = normalized.rfind("}")
    if 0 <= object_start < object_end:
        return normalized[object_start:object_end + 1]
    return None


def _outline_children(raw: Mapping[str, Any]) -> list[Any]:
    """Return child outline entries from common model output keys."""
    for key in ("children", "subsections", "sub_sections", "items", "sections"):
        value = raw.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return list(value)
    return []


def _append_normalized_outline_items(
    result: list[_GeneratedOutlineItem],
    raw_items: Sequence[Any],
    *,
    level: int,
    parent_index: int | None,
) -> None:
    """Flatten model-generated hierarchy while retaining parent links."""
    for raw in raw_items:
        if isinstance(raw, str):
            title = _clean_outline_title(raw, fallback=f"章节 {len(result) + 1}")
            description = ""
            children: list[Any] = []
            raw_level = level
        elif isinstance(raw, Mapping):
            title = _clean_outline_title(
                raw.get("title") or raw.get("heading") or raw.get("name"),
                fallback=f"章节 {len(result) + 1}",
            )
            description = _clean_outline_description(
                raw.get("description") or raw.get("summary") or raw.get("notes")
            )
            children = _outline_children(raw)
            raw_level = _coerce_outline_level(raw.get("level"), default=level)
        else:
            continue

        current_index = len(result)
        result.append(
            {
                "title": title,
                "description": description,
                "level": _coerce_outline_level(raw_level, default=level),
                "parent_index": parent_index,
            }
        )
        if children:
            _append_normalized_outline_items(
                result,
                children,
                level=_coerce_outline_level(raw_level, default=level) + 1,
                parent_index=current_index,
            )


def _parse_generated_outline(raw_text: str) -> list[_GeneratedOutlineItem]:
    """Parse AI JSON into a bounded outline list; invalid payloads return empty."""
    candidate = _extract_json_candidate(raw_text)
    if candidate is None:
        return []
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError:
        return []

    if isinstance(decoded, Mapping):
        for key in ("items", "outline", "sections"):
            value = decoded.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                decoded = value
                break
        else:
            decoded = [decoded]

    if not isinstance(decoded, Sequence) or isinstance(decoded, (str, bytes)):
        return []

    result: list[_GeneratedOutlineItem] = []
    _append_normalized_outline_items(result, list(decoded), level=1, parent_index=None)
    return result[:24]


def _fallback_outline_items(
    request: GenerateOutlineRequest,
    material_context: Sequence[_OutlineMaterialContext],
) -> list[_GeneratedOutlineItem]:
    """Build a deterministic, evidence-grounded outline when AI is unavailable."""
    topic = request.topic.strip()
    focus_areas = [str(item).strip() for item in request.focus_areas if str(item).strip()]
    primary = material_context[0]
    secondary = material_context[1] if len(material_context) > 1 else material_context[0]
    evidence_focus = focus_areas[0] if focus_areas else primary["title"]
    comparison_focus = focus_areas[1] if len(focus_areas) > 1 else secondary["title"]
    material_ids = "、".join(item["material_id"] for item in material_context[:4])
    target_note = f"目标篇幅约 {request.target_length} 字。" if request.target_length else "按学术论文常规篇幅组织。"
    rows: list[tuple[str, str]] = [
        ("研究背景与问题界定", f"基于材料 {material_ids} 说明 {topic} 的研究背景、核心概念、研究对象和写作边界。{target_note}"),
        ("文献证据与研究现状", f"围绕 {evidence_focus} 汇总已有文献的主要结论、证据强度和不足，并保留材料锚点。"),
        ("方法、材料与分析框架", f"交代检索、筛选、对比和论证方法，明确 {topic} 的分析框架。"),
        ("关键发现与对比讨论", f"比较 {comparison_focus}，提炼一致结论、分歧来源和可能机制。"),
        ("结论、局限与后续工作", f"总结可支撑的结论，标出证据边界、局限和下一步补证方向。"),
    ]
    return [
        {
            "title": title,
            "description": description,
            "level": 1,
            "parent_index": None,
        }
        for title, description in rows
    ]


def _extract_ai_text(response: Any) -> str:
    """Read text content from common OpenAI-compatible response shapes."""
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        choices = response.get("choices")
        if isinstance(choices, Sequence) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, Mapping):
                message = first_choice.get("message")
                if isinstance(message, Mapping):
                    return str(message.get("content") or "")
                return str(first_choice.get("text") or "")
        return str(response.get("content") or response.get("text") or "")
    choices = getattr(response, "choices", None)
    if isinstance(choices, Sequence) and choices:
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is not None:
            return str(getattr(message, "content", "") or "")
        return str(getattr(first_choice, "text", "") or "")
    return ""


async def _generate_outline_text_with_ai(adapter: Any, prompt: str) -> str:
    """Call the configured AI adapter when it exposes a supported generation API."""
    if adapter is None:
        return ""

    generate_text = getattr(adapter, "generate_text", None)
    if callable(generate_text):
        response = generate_text(prompt=prompt, max_tokens=2000, temperature=0.4)
        if inspect.isawaitable(response):
            response = await response
        return _extract_ai_text(response)

    if getattr(adapter, "enabled", False):
        chat = getattr(adapter, "_chat", None)
        if callable(chat):
            response = await asyncio.to_thread(
                chat,
                prompt,
                task="generation",
                overrides={"temperature": 0.4, "max_tokens": 2000},
                response_format={"type": "json_object"},
            )
            return _extract_ai_text(response)
    return ""


def _persist_generated_outline_items(
    store: Any,
    request: GenerateOutlineRequest,
    items: Sequence[_GeneratedOutlineItem],
) -> OutlinePayload:
    """Persist generated outline items as section-backed outline nodes."""
    existing_sections = store.list_sections(request.project_id)
    next_order = (max((section.order for section in existing_sections), default=-1) + 1)
    index_to_section_id: dict[int, str] = {}
    payload_items: list[OutlineItemPayload] = []

    for index, item in enumerate(items):
        parent_index = item["parent_index"]
        parent_section_id = index_to_section_id.get(parent_index) if parent_index is not None else None
        metadata = {
            "outline_generated": True,
            "outline_level": item["level"],
            "outline_parent_id": parent_section_id,
            "outline_source": "ai_or_fallback",
        }
        section = store.create_section(
            project_id=request.project_id,
            title=item["title"],
            order=next_order + index,
            description=item["description"],
            metadata=metadata,
        )
        index_to_section_id[index] = section.section_id
        payload_items.append(_section_to_outline_item(section))

    return OutlinePayload(
        project_id=request.project_id,
        items=payload_items,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _citation_terms(*values: Any) -> list[str]:
    """Extract bounded citation-matching terms from English and CJK text."""
    terms: list[str] = []
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        for token in _CITATION_TERM_PATTERN.findall(text):
            if token.isascii():
                if len(token) >= 2 and token not in _CITATION_STOPWORDS:
                    terms.append(token)
                continue
            if len(token) <= 4:
                terms.append(token)
            for width in (2, 3):
                if len(token) < width:
                    continue
                terms.extend(token[index:index + width] for index in range(len(token) - width + 1))
    return terms[:240]


def _material_text_fields(material: Any) -> list[str]:
    """Return citation-relevant material fields without exposing raw internals."""
    focus_points = getattr(material, "focus_points", []) or []
    focus_points_en = getattr(material, "focus_points_en", []) or []
    return [
        str(getattr(material, "title", "") or ""),
        str(getattr(material, "title_en", "") or ""),
        str(getattr(material, "summary", "") or ""),
        str(getattr(material, "summary_en", "") or ""),
        " ".join(str(item) for item in focus_points),
        " ".join(str(item) for item in focus_points_en),
    ]


def _trim_citation_excerpt(value: Any, fallback: str) -> str:
    """Return a compact excerpt for suggestion cards."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        text = fallback
    return text[:240]


def _normalize_relevance_score(value: Any, default: float = 0.5) -> float:
    """Clamp arbitrary retrieval scores to the public 0..1 response contract."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def _search_results_to_citation_suggestions(
    search_results: Sequence[Any],
    materials_by_id: Mapping[str, Any],
    *,
    context: str,
    max_suggestions: int,
) -> list[CitationSuggestionPayload]:
    """Convert retrieval hits into citation suggestions while deduplicating materials."""
    suggestions: list[CitationSuggestionPayload] = []
    seen_material_ids: set[str] = set()
    for raw_result in search_results:
        if not isinstance(raw_result, Mapping):
            continue
        material_id = str(
            raw_result.get("material_id")
            or raw_result.get("document_id")
            or raw_result.get("source_id")
            or ""
        ).strip()
        if not material_id or material_id in seen_material_ids:
            continue
        material = materials_by_id.get(material_id)
        title = str(
            raw_result.get("material_title")
            or raw_result.get("title")
            or getattr(material, "title", "")
            or material_id
        ).strip()
        excerpt = _trim_citation_excerpt(
            raw_result.get("text") or raw_result.get("content") or raw_result.get("excerpt"),
            fallback=title,
        )
        suggestions.append(
            CitationSuggestionPayload(
                material_id=material_id,
                title=title,
                excerpt=excerpt,
                relevance_score=_normalize_relevance_score(raw_result.get("score"), default=0.5),
                rationale=f"检索结果与上下文相关：{context[:80]}",
                suggested_position=None,
            )
        )
        seen_material_ids.add(material_id)
        if len(suggestions) >= max_suggestions:
            break
    return suggestions


def _material_metadata_citation_suggestions(
    materials: Sequence[Any],
    *,
    context: str,
    max_suggestions: int,
    excluded_material_ids: set[str] | None = None,
) -> list[CitationSuggestionPayload]:
    """Rank project materials by metadata overlap as a no-index fallback."""
    excluded = set(excluded_material_ids or set())
    context_terms = Counter(_citation_terms(context))
    if not context_terms:
        return []

    ranked: list[tuple[float, int, str, Any, list[str]]] = []
    for material in materials:
        material_id = str(getattr(material, "material_id", "") or "").strip()
        if not material_id or material_id in excluded:
            continue
        fields = _material_text_fields(material)
        material_terms = Counter(_citation_terms(*fields))
        if not material_terms:
            continue
        shared_terms = [
            term for term in context_terms.keys()
            if term in material_terms
        ]
        shared_weight = sum(min(context_terms[term], material_terms[term]) for term in shared_terms)
        if shared_weight <= 0:
            continue
        title_terms = set(_citation_terms(getattr(material, "title", ""), getattr(material, "title_en", "")))
        title_hits = sum(1 for term in shared_terms if term in title_terms)
        score = min(
            0.95,
            0.25
            + (shared_weight / max(1, sum(context_terms.values()))) * 0.55
            + min(0.15, title_hits * 0.03)
            + min(0.05, len(shared_terms) * 0.01),
        )
        ranked.append((score, shared_weight, material_id, material, shared_terms[:6]))

    ranked.sort(key=lambda item: (-item[0], -item[1], str(getattr(item[3], "title", "")).lower()))
    suggestions: list[CitationSuggestionPayload] = []
    for score, _, material_id, material, shared_terms in ranked[:max_suggestions]:
        title = str(getattr(material, "title", "") or getattr(material, "title_en", "") or material_id)
        summary = str(getattr(material, "summary", "") or getattr(material, "summary_en", "") or "")
        rationale = "元数据匹配：" + "、".join(shared_terms[:4])
        suggestions.append(
            CitationSuggestionPayload(
                material_id=material_id,
                title=title,
                excerpt=_trim_citation_excerpt(summary, fallback=title),
                relevance_score=round(score, 3),
                rationale=rationale,
                suggested_position=None,
            )
        )
    return suggestions


# =========================================================================
# Project aliases - H1
# =========================================================================

@router.get("/projects", response_model=list[ProjectPayload])
async def list_projects_alias(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> list[ProjectPayload]:
    """List all writing projects (alias to /resources/projects)."""
    from routers.resources_router.endpoints_projects import list_projects
    return await list_projects(user_id=user_id, page=page, page_size=page_size)


@router.get("/projects/{project_id}", response_model=ProjectPayload)
async def get_project_alias(project_id: str) -> ProjectPayload:
    """Get a writing project by ID (alias to /resources/project/{id})."""
    from routers.resources_router.endpoints_projects import get_project
    return await get_project(project_id)


@router.post("/projects", response_model=ProjectPayload)
async def create_project_alias(request: CreateProjectRequest) -> ProjectPayload:
    """Create a new writing project (alias to /resources/project)."""
    from routers.resources_router.endpoints_projects import create_project
    return await create_project(request)


@router.put("/projects/{project_id}/status", response_model=ProjectPayload)
async def update_project_status_alias(
    project_id: str,
    status: str = Query(..., description="New status"),
) -> ProjectPayload:
    """Update project status (alias to /resources/project/{id}/status)."""
    from routers.resources_router.endpoints_projects import update_project_status
    return await update_project_status(project_id, status)


@router.delete("/projects/{project_id}")
async def delete_project_alias(project_id: str) -> dict[str, str]:
    """Delete a writing project (alias to /resources/project/{id})."""
    from routers.resources_router.endpoints_projects import delete_project
    return await delete_project(project_id)


# =========================================================================
# Outline CRUD - H2
# =========================================================================

@router.get("/outline", response_model=OutlinePayload)
async def get_outline(
    project_id: str = Query(..., description="Project ID"),
) -> OutlinePayload:
    """Get outline for a project.

    Returns hierarchical outline structure. Currently maps to sections.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    sections = store.list_sections(project_id)

    items = [_section_to_outline_item(section) for section in sections]

    return OutlinePayload(
        project_id=project_id,
        items=items,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.put("/outline", response_model=OutlinePayload)
async def update_outline(
    project_id: str = Query(..., description="Project ID"),
    items: list[OutlineItemPayload] = Body(default_factory=list),
) -> OutlinePayload:
    """Update outline structure.

    Currently updates sections. Full hierarchical outline support pending.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # Update sections based on outline items and keep outline hierarchy metadata
    # aligned so Writer and Manuscript Studio read the same section names.
    for item in items:
        if item.section_id:
            section = store.get_section(item.section_id)
            if not section:
                continue
            if section.project_id != project_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Section {item.section_id} does not belong to project {project_id}",
                )
            metadata = dict(section.metadata or {})
            metadata["outline_level"] = item.level
            if item.parent_id:
                metadata["outline_parent_id"] = item.parent_id
            else:
                metadata.pop("outline_parent_id", None)
            store.update_section(
                item.section_id,
                title=item.title,
                order=item.order,
                description=item.description,
                metadata=metadata,
            )

    # Return updated outline
    return await get_outline(project_id=project_id)


@router.delete("/outline/{item_id}")
async def delete_outline_item(item_id: str) -> dict[str, str]:
    """Delete an outline item.

    Currently deletes the corresponding section.
    """
    from routers.resources_router.endpoints_projects import delete_section
    return await delete_section(item_id)


# =========================================================================
# Outline generation - H7
# =========================================================================

@router.post("/outline/generate", response_model=OutlinePayload)
async def generate_outline(request: GenerateOutlineRequest) -> OutlinePayload:
    """Generate an evidence-grounded outline from project materials.

    Why:
        Academic outlines should be constrained by project-owned source
        summaries rather than topic-only generation. The endpoint fails when no
        usable material context exists, preventing plausible but unsupported
        outlines from entering downstream MCP writing workflows.
    """
    from routers.resources_router import get_ai_adapter, get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")
    topic = request.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic must be non-empty")

    material_context = _collect_outline_material_context(store, request)
    if not material_context:
        raise HTTPException(
            status_code=400,
            detail="Outline generation requires at least one project material with summary or chunk text",
        )

    # Build context from existing materials
    context_parts = [f"Topic: {topic}"]
    if request.focus_areas:
        context_parts.append(f"Focus areas: {', '.join(request.focus_areas)}")
    if request.target_length:
        context_parts.append(f"Target length: ~{request.target_length} words")
    context_parts.append("Project materials:")
    context_parts.append(_format_outline_material_context(material_context))

    prompt = f"""Generate a structured outline for a {request.content_type} writing project.

{chr(10).join(context_parts)}

Generate a hierarchical outline with:
- 3-5 main sections (level 1)
- 2-4 subsections per main section (level 2)
- Brief description for each section
- Every section description must mention at least one material id in square brackets when that section makes a literature claim
- Do not introduce claims that are not supported by the listed project materials

Format as JSON array of outline items with: title, level, order, description"""

    generated_items: list[_GeneratedOutlineItem] = []
    try:
        ai_text = await _generate_outline_text_with_ai(get_ai_adapter(), prompt)
        if ai_text.strip():
            generated_items = _parse_generated_outline(ai_text)
    except Exception as exc:
        logger.warning("Writing outline AI generation failed; using fallback: %s", exc)

    if not generated_items:
        generated_items = _fallback_outline_items(request, material_context)

    return _persist_generated_outline_items(store, request, generated_items)


# =========================================================================
# Citation source metadata - H3
# =========================================================================

def _meta_str(meta: dict[str, object], key: str) -> str | None:
    value = meta.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _meta_int(meta: dict[str, object], key: str) -> int | None:
    value = meta.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _citation_source_from_material(
    material: WritingMaterial, citation_count: int = 0
) -> CitationSourcePayload:
    """Build a citation source payload from a material's stored CSL metadata.

    Bibliographic fields live in ``material.metadata`` (the resource
    extensibility slot) under keys aligned with the export bibliography builder:
    ``authors`` (list), ``year``, ``venue`` (container-title), ``doi``, ``url``,
    ``publisher``, ``volume``, ``issue``, ``pages``, ``csl_type``.
    """
    meta = material.metadata if isinstance(material.metadata, dict) else {}
    raw_authors = meta.get("authors")
    authors = (
        [str(a).strip() for a in raw_authors if str(a).strip()]
        if isinstance(raw_authors, list)
        else []
    )
    return CitationSourcePayload(
        source_id=material.material_id,
        material_id=material.material_id,
        project_id=material.project_id,
        title=material.title,
        authors=authors,
        year=_meta_int(meta, "year"),
        publication=_meta_str(meta, "venue"),
        doi=_meta_str(meta, "doi"),
        url=_meta_str(meta, "url"),
        publisher=_meta_str(meta, "publisher"),
        volume=_meta_str(meta, "volume"),
        issue=_meta_str(meta, "issue"),
        pages=_meta_str(meta, "pages"),
        csl_type=_meta_str(meta, "csl_type") or "article-journal",
        citation_count=citation_count,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.get("/citations/sources", response_model=list[CitationSourcePayload])
async def get_citation_sources(
    project_id: str = Query(..., description="Project ID"),
) -> list[CitationSourcePayload]:
    """Get citation source metadata for a project.

    Returns each material as a citation source, reading bibliographic fields
    from material metadata. This is NOT Word-style bibliography generation;
    formatting is done client-side (citeproc) or at export (pandoc).
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    materials = store.list_materials(project_id=project_id)
    return [_citation_source_from_material(material) for material in materials]


@router.put("/citations/sources/{source_id}", response_model=CitationSourcePayload)
async def update_citation_source(
    source_id: str,
    payload: CitationSourceUpdate,
) -> CitationSourcePayload:
    """Persist editable bibliographic metadata for a source material.

    Only provided (non-null) fields are written; the rest are preserved.
    ``publication`` is stored as ``venue`` to match the export bibliography
    builder's metadata keys.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    material = store.get_material(source_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    metadata_updates: dict[str, object] = {}
    if payload.authors is not None:
        metadata_updates["authors"] = [str(a).strip() for a in payload.authors if str(a).strip()]
    if payload.year is not None:
        metadata_updates["year"] = payload.year
    if payload.publication is not None:
        metadata_updates["venue"] = payload.publication.strip()
    if payload.doi is not None:
        metadata_updates["doi"] = payload.doi.strip()
    if payload.url is not None:
        metadata_updates["url"] = payload.url.strip()
    if payload.publisher is not None:
        metadata_updates["publisher"] = payload.publisher.strip()
    if payload.volume is not None:
        metadata_updates["volume"] = payload.volume.strip()
    if payload.issue is not None:
        metadata_updates["issue"] = payload.issue.strip()
    if payload.pages is not None:
        metadata_updates["pages"] = payload.pages.strip()
    if payload.csl_type is not None:
        metadata_updates["csl_type"] = payload.csl_type.strip() or "article-journal"

    updated = store.update_material(
        source_id,
        title=payload.title,
        metadata=metadata_updates or None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
    return _citation_source_from_material(updated)


# =========================================================================
# Citation AI suggestion - H8
# =========================================================================

@router.post("/citations/suggest", response_model=list[CitationSuggestionPayload])
async def suggest_citations(request: SuggestCitationsRequest) -> list[CitationSuggestionPayload]:
    """Suggest relevant citations for draft context via AI.

    Analyzes draft text and recommends materials to cite.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    draft = store.get_draft(request.draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {request.draft_id}")
    if draft.project_id != request.project_id:
        raise HTTPException(status_code=400, detail="Draft does not belong to the requested project")

    context = request.context.strip()
    if not context:
        raise HTTPException(status_code=400, detail="Citation suggestion context must not be empty")

    materials = store.list_materials(project_id=request.project_id)
    materials_by_id = {str(material.material_id): material for material in materials}

    # Search for relevant chunks based on context
    try:
        from main_rag_workflow import search_chunks

        search_results = search_chunks(
            query=context,
            project_id=request.project_id,
            top_k=request.max_suggestions,
        )
    except Exception as exc:
        # Fallback if search fails
        logger.info("Citation chunk search unavailable; using material metadata fallback: %s", exc)
        search_results = []

    if not isinstance(search_results, Sequence) or isinstance(search_results, (str, bytes)):
        search_results = []

    suggestions = _search_results_to_citation_suggestions(
        search_results,
        materials_by_id,
        context=context,
        max_suggestions=request.max_suggestions,
    )

    if len(suggestions) < request.max_suggestions:
        existing_ids = {suggestion.material_id for suggestion in suggestions}
        suggestions.extend(
            _material_metadata_citation_suggestions(
                materials,
                context=context,
                max_suggestions=request.max_suggestions - len(suggestions),
                excluded_material_ids=existing_ids,
            )
        )

    return suggestions[:request.max_suggestions]


# =========================================================================
# Figure/table assets - H4
# =========================================================================

@router.get("/figures", response_model=list[FigureAssetPayload])
async def list_figure_assets(
    project_id: str = Query(..., description="Project ID"),
) -> list[FigureAssetPayload]:
    """List real figure/table assets for a project.

    Returns actual extracted/uploaded figures with asset files.
    Distinct from text-derived candidates.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    assets = store.list_figure_assets(project_id)
    return [_figure_asset_payload(asset) for asset in assets]


@router.post("/figures", response_model=FigureAssetPayload)
async def create_figure_asset(request: CreateFigureAssetRequest) -> FigureAssetPayload:
    """Create a figure/table asset.

    Registers an extracted or uploaded figure/table with asset file.
    """
    from routers.resources_router import get_writing_resource_store
    import uuid

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")
    asset = store.create_figure_asset(
        project_id=request.project_id,
        kind=request.kind,
        caption=request.caption,
        numbering=request.numbering,
        asset_path=request.asset_path,
        material_id=request.material_id,
        source_page=request.source_page,
        bbox=request.bbox,
        width=request.width,
        height=request.height,
        format=request.format,
    )
    return _figure_asset_payload(asset)


@router.put("/figures/{asset_id}", response_model=FigureAssetPayload)
async def update_figure_asset(
    asset_id: str,
    request: UpdateFigureAssetRequest | None = None,
    caption: str | None = Query(None),
    numbering: str | None = Query(None),
) -> FigureAssetPayload:
    """Update figure/table asset metadata."""
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    asset = store.get_figure_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")

    payload = request or UpdateFigureAssetRequest()
    updated = store.update_figure_asset(
        asset_id,
        kind=_figure_asset_value(payload.kind),
        caption=_figure_asset_value(payload.caption if payload.caption is not None else caption),
        numbering=_figure_asset_value(payload.numbering if payload.numbering is not None else numbering),
        material_id=_figure_asset_value(payload.material_id),
        source_page=payload.source_page,
        bbox=payload.bbox,
        asset_path=_figure_asset_value(payload.asset_path),
        width=payload.width,
        height=payload.height,
        format=_figure_asset_value(payload.format),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    return _figure_asset_payload(updated)


@router.delete("/figures/{asset_id}")
async def delete_figure_asset(asset_id: str) -> dict[str, str]:
    """Delete a figure/table asset."""
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    if not store.delete_figure_asset(asset_id):
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    return {"status": "deleted", "asset_id": asset_id}


@router.get("/figures/file")
async def serve_figure_asset_file(
    project_id: str = Query(..., description="Project ID"),
    path: str = Query(..., description="Local asset path recorded on the figure/table item"),
) -> FileResponse:
    """Serve a project-scoped figure/table image for in-app preview and paste."""
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    resolved = _resolve_figure_file_path(project_id, path)
    media_type = _FIGURE_IMAGE_MEDIA_TYPES[resolved.suffix.lower()]
    response = FileResponse(path=str(resolved), media_type=media_type)
    safe_name = resolved.name.encode("utf-8").decode("latin-1", errors="ignore")
    response.headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
    return response


@router.post("/figures/generate", response_model=GenerateFigureAssetsResponse)
async def generate_figure_assets(request: GenerateFigureAssetsRequest) -> GenerateFigureAssetsResponse:
    """Generate local figure/table assets from existing chunk-backed candidates.

    This endpoint intentionally does not call an image model. It materializes
    already extracted pixel candidates into persisted writing assets while
    preserving source material, page, bbox, and local asset path provenance.
    """
    from routers.resources_router import get_writing_resource_store
    from routers.resources_router import _ensure_project_chunks
    from routers.resources_router.endpoints_search_upload import derive_figure_table_candidates

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    chunk_store = _ensure_project_chunks(request.project_id)
    candidates = derive_figure_table_candidates(
        request.project_id,
        chunk_store,
        limit=200,
        pixel_only=True,
        render_pdf_fallback=False,
    )
    candidate_ids = {candidate_id.strip() for candidate_id in request.candidate_ids if candidate_id.strip()}
    existing_asset_paths = {
        str(asset.asset_path).strip()
        for asset in store.list_figure_assets(request.project_id)
        if str(asset.asset_path).strip()
    }

    generated_assets: list[FigureAssetPayload] = []
    skipped_candidate_ids: list[str] = []
    for candidate in candidates:
        if request.kind is not None and candidate.kind != request.kind:
            continue
        if candidate_ids and candidate.id not in candidate_ids:
            continue
        asset_path = str(candidate.asset_path or "").strip()
        if not asset_path:
            skipped_candidate_ids.append(candidate.id)
            continue
        if not request.overwrite_existing and asset_path in existing_asset_paths:
            skipped_candidate_ids.append(candidate.id)
            continue

        payload = _candidate_to_create_asset_payload(request, candidate)
        asset = store.create_figure_asset(**payload)
        existing_asset_paths.add(asset.asset_path)
        generated_assets.append(_figure_asset_payload(asset))
        if len(generated_assets) >= request.max_items:
            break

    if candidate_ids:
        matched_ids = {candidate.id for candidate in candidates if candidate.id in candidate_ids}
        skipped_candidate_ids.extend(sorted(candidate_ids - matched_ids))

    generated_count = len(generated_assets)
    return GenerateFigureAssetsResponse(
        project_id=request.project_id,
        generated_count=generated_count,
        generated_assets=generated_assets,
        skipped_candidate_ids=sorted(set(skipped_candidate_ids)),
        message=(
            f"已生成 {generated_count} 个本地图表资产。"
            if generated_count
            else "没有可生成的本地图表资产；请先完成文献切块或图表加载。"
        ),
    )


@router.get("/figures/candidates", response_model=list[FigureTableCandidatePayload])
async def list_figure_candidates_alias(
    project_id: str = Query(..., description="Project ID"),
    limit: int = Query(96, ge=1, le=200, description="Maximum number of candidates"),
    pixel_only: bool = Query(False, description="Return only chunk records that already include image assets"),
    render_pdf_fallback: bool = Query(True, description="Allow PDF page/crop rendering when chunk assets are missing"),
) -> list[FigureTableCandidatePayload]:
    """List text-derived figure/table candidates (alias to /resources/figure-table-candidates).

    Returns candidates extracted from chunk text, not real assets.
    """
    from routers.resources_router.endpoints_search_upload import list_figure_table_candidates
    return await list_figure_table_candidates(
        project_id=project_id,
        limit=limit,
        pixel_only=pixel_only,
        render_pdf_fallback=render_pdf_fallback,
    )


# =========================================================================
# Reviewer submission - H5
# =========================================================================

@router.post("/submit", response_model=SubmissionResponsePayload)
async def submit_for_review(request: SubmitForReviewRequest) -> SubmissionResponsePayload:
    """Submit project for review.

    Packages project content for reviewer access.
    """
    from routers.resources_router import get_writing_resource_store
    from project_paths import output_path
    import uuid

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    submission_id = f"sub_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    sections = [section.to_dict() for section in store.list_sections(request.project_id)]
    drafts = [draft.to_dict() for draft in store.list_drafts(request.project_id)] if request.include_drafts else []
    materials = [material.to_dict() for material in store.list_materials(request.project_id)] if request.include_materials else []
    package_dir = output_path("writing_submissions", request.project_id, submission_id)
    package_dir.mkdir(parents=True, exist_ok=True)

    package_payload = {
        "submission_id": submission_id,
        "project": project.to_dict(),
        "sections": sections,
        "drafts": drafts,
        "materials": materials,
        "reviewer_email": request.reviewer_email,
        "message": request.message,
        "include_drafts": request.include_drafts,
        "include_materials": request.include_materials,
        "submitted_at": now,
    }
    manifest_path = package_dir / "submission_manifest.json"
    manifest_path.write_text(
        json.dumps(package_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    overview_path = package_dir / "README.md"
    overview_path.write_text(
        "\n".join(
            [
                f"# {project.title}",
                "",
                f"- Submission ID: `{submission_id}`",
                f"- Submitted at: `{now}`",
                f"- Reviewer: `{request.reviewer_email or 'not specified'}`",
                f"- Sections: {len(sections)}",
                f"- Drafts: {len(drafts)}",
                f"- Materials: {len(materials)}",
                "",
                request.message.strip() if request.message.strip() else "No reviewer note provided.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return SubmissionResponsePayload(
        submission_id=submission_id,
        project_id=request.project_id,
        status="submitted",
        submitted_at=now,
        reviewer_email=request.reviewer_email,
        package_path=str(package_dir),
    )


# =========================================================================
# Project export - H10
# =========================================================================

@router.post("/export", response_model=ProjectExportPayload)
async def export_project(request: ExportProjectRequest) -> ProjectExportPayload:
    """Export project in specified format.

    Supports JSON, Markdown, Word, LaTeX, and PDF formats.
    """
    try:
        from routers.resources_router import ProjectExportFormat
        from routers.resources_router.endpoints_export_stats import export_project as export_project_resource
        export_format = ProjectExportFormat(request.format)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported export format: {request.format}",
        ) from exc

    return await export_project_resource(
        project_id=request.project_id,
        format=export_format,
        include_evidence=request.include_evidence,
        include_citations=request.include_citations,
        style_profile=request.style_profile,
    )
