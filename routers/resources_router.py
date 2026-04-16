# -*- coding: utf-8 -*-
"""Resources API Router - Manages projects, sections, drafts, and associations."""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Mapping
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from models import (
    ProjectPayload,
    SectionPayload,
    MaterialPayload,
    DraftPayload,
    RevisionPayload,
    WritingAssociationPayload,
    CreateProjectRequest,
    CreateSectionRequest,
    CreateMaterialRequest,
    CreateDraftRequest,
    SaveDraftRequest,
    BuildAssociationRequest,
    PaginatedResponse,
    PaginationMeta,
    paginate,
    MessageResponse,
)

logger = logging.getLogger("ResourcesRouter")
router = APIRouter(prefix="/resources", tags=["Resources"])
_ai_adapter_instance: Any | None = None

# Document content store — default location (overridden when project has source_folder)
_DOC_STORE_DIR = Path(__file__).resolve().parent.parent / "output" / "doc_store"
_DOC_STORE_DIR.mkdir(parents=True, exist_ok=True)

# Chunk store — default location (overridden when project has source_folder)
_CHUNK_STORE_DIR = Path(__file__).resolve().parent.parent / "output" / "chunk_store"
_CHUNK_STORE_DIR.mkdir(parents=True, exist_ok=True)

# Sub-directory name used when storing data alongside literature files
_SCHOLAR_SUBDIR = ".scholarai"

# Chunking settings (learned from open-webui / quivr-core)
CHUNK_SIZE = 800       # chars per chunk
CHUNK_OVERLAP = 150    # overlap chars between adjacent chunks
MAX_CHUNKS_PER_MATERIAL = 5  # max chunks returned per document in RAG search (was 2)

# Supported file extensions for folder scanning
_SCAN_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}


def _get_project_source_folder(project_id: str) -> str:
    """Return the source_folder stored in the project's metadata (or empty string)."""
    try:
        from writing_resources import get_writing_resource_store
        store = get_writing_resource_store()
        project = store.get_project(project_id)
        if project:
            return str(project.metadata.get("source_folder", "")).strip()
    except Exception:
        pass
    return ""


def _resolve_data_dir(project_id: str) -> tuple[Path, Path]:
    """Return (doc_store_dir, chunk_store_dir) for a project.

    When a project has a source_folder, both stores are placed in
    ``{source_folder}/.scholarai/`` so the index lives alongside
    the literature files and can be moved/backed-up with them.
    """
    source_folder = _get_project_source_folder(project_id)
    if source_folder:
        base = Path(source_folder).expanduser().resolve() / _SCHOLAR_SUBDIR
        base.mkdir(parents=True, exist_ok=True)
        return base, base
    return _DOC_STORE_DIR, _CHUNK_STORE_DIR


def _get_doc_store_path(project_id: str) -> Path:
    """Return the JSON doc store path for a given project."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in "_-")
    doc_dir, _ = _resolve_data_dir(project_id)
    return doc_dir / f"{safe_id}.json"


def _load_doc_store(project_id: str) -> dict[str, dict[str, str]]:
    """Load document content store for a project."""
    path = _get_doc_store_path(project_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: check default location (in case project was migrated)
    fallback = _DOC_STORE_DIR / f"{''.join(c for c in project_id if c.isalnum() or c in '_-')}.json"
    if fallback.exists() and fallback != path:
        try:
            return json.loads(fallback.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_doc_store(project_id: str, store: dict[str, dict[str, str]]) -> None:
    """Persist document content store."""
    path = _get_doc_store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Chunk store helpers — splits documents into overlapping chunks for RAG
# ---------------------------------------------------------------------------

def _get_chunk_store_path(project_id: str) -> Path:
    """Return the JSON chunk store path for a given project."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in "_-")
    _, chunk_dir = _resolve_data_dir(project_id)
    return chunk_dir / f"{safe_id}_chunks.json"


def _load_chunk_store(project_id: str) -> dict[str, list[dict[str, Any]]]:
    """Load chunk store for a project: { material_id: [chunk_dicts] }."""
    path = _get_chunk_store_path(project_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: legacy filename without _chunks suffix
    safe_id = "".join(c for c in project_id if c.isalnum() or c in "_-")
    fallback = _CHUNK_STORE_DIR / f"{safe_id}.json"
    if fallback.exists() and fallback != path:
        try:
            return json.loads(fallback.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_chunk_store(project_id: str, store: dict[str, list[dict[str, Any]]]) -> None:
    """Persist chunk store."""
    path = _get_chunk_store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def _tokenize_search_text(text: str) -> set[str]:
    """Tokenize mixed Chinese/English text for lightweight keyword retrieval."""
    normalized = text.lower().strip()
    if not normalized:
        return set()

    latin_tokens = re.findall(r"[a-z0-9_]+", normalized)
    cjk_chars = [ch for ch in normalized if "\u4e00" <= ch <= "\u9fff"]
    cjk_bigrams = ["".join(cjk_chars[idx:idx + 2]) for idx in range(len(cjk_chars) - 1)]
    cjk_tokens = cjk_bigrams or cjk_chars
    return set(latin_tokens + cjk_tokens)


def _normalize_chunk_dedup_key(content: str) -> str:
    """Create a lightweight dedupe key for near-identical chunk content."""
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return normalized[:300]


def _select_diverse_top_chunks(
    scored_chunks: list[tuple[float, dict[str, Any]]],
    top_k: int,
    max_chunks_per_material: int = MAX_CHUNKS_PER_MATERIAL,
) -> list[tuple[float, dict[str, Any]]]:
    """Select top chunks while preserving material diversity for RAG context.

    The first pass prefers the strongest chunk from each material so the LLM sees
    broader evidence coverage. Later passes add additional chunks from the same
    material only when there is still room.
    """
    positive_chunks = [(score, chunk) for score, chunk in scored_chunks if score > 0]
    if not positive_chunks:
        return []

    grouped: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    material_order: list[str] = []
    for score, chunk in positive_chunks:
        material_key = str(chunk.get("material_id") or "")
        if material_key not in grouped:
            grouped[material_key] = []
            material_order.append(material_key)
        grouped[material_key].append((score, chunk))

    selected: list[tuple[float, dict[str, Any]]] = []
    seen_content_keys: set[tuple[str, str]] = set()

    for rank in range(max_chunks_per_material):
        added_this_round = False
        for material_key in material_order:
            material_chunks = grouped.get(material_key, [])
            if rank >= len(material_chunks):
                continue

            score, chunk = material_chunks[rank]
            content_key = _normalize_chunk_dedup_key(str(chunk.get("content") or ""))
            dedupe_key = (material_key, content_key)
            if dedupe_key in seen_content_keys:
                continue

            selected.append((score, chunk))
            seen_content_keys.add(dedupe_key)
            added_this_round = True

            if len(selected) >= top_k:
                return selected

        if not added_this_round:
            break

    return selected


def _ensure_project_chunks(
    project_id: str,
    material_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Backfill missing chunks from doc_store and prune stale chunk entries."""
    doc_store = _load_doc_store(project_id)
    chunk_store = _load_chunk_store(project_id)
    material_ids = {material_id} if material_id else set(doc_store.keys()) | set(chunk_store.keys())
    updated = False

    for mid in list(material_ids):
        document = doc_store.get(mid)
        if document is None:
            if mid in chunk_store:
                del chunk_store[mid]
                updated = True
            continue

        title = str(document.get("title") or mid)
        content = str(document.get("content") or "")
        existing_chunks = [chunk for chunk in (chunk_store.get(mid) or []) if str(chunk.get("content") or "").strip()]

        if not content.strip():
            if mid in chunk_store:
                del chunk_store[mid]
                updated = True
            continue

        if not existing_chunks:
            chunk_store[mid] = _chunk_document(mid, title, content)
            updated = True
            continue

        normalized_chunks: list[dict[str, Any]] = []
        for idx, chunk in enumerate(existing_chunks):
            normalized_chunk = dict(chunk)
            changed = False
            if normalized_chunk.get("material_id") != mid:
                normalized_chunk["material_id"] = mid
                changed = True
            if normalized_chunk.get("title") != title:
                normalized_chunk["title"] = title
                changed = True
            if normalized_chunk.get("chunk_index") != idx:
                normalized_chunk["chunk_index"] = idx
                changed = True
            expected_chunk_id = f"{mid}_chunk_{idx}"
            if normalized_chunk.get("chunk_id") != expected_chunk_id:
                normalized_chunk["chunk_id"] = expected_chunk_id
                changed = True
            char_count = len(str(normalized_chunk.get("content") or ""))
            if normalized_chunk.get("char_count") != char_count:
                normalized_chunk["char_count"] = char_count
                changed = True
            normalized_chunks.append(normalized_chunk)
            if changed:
                updated = True

        chunk_store[mid] = normalized_chunks

    if updated:
        _save_chunk_store(project_id, chunk_store)

    return chunk_store


def _split_text_into_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks using recursive separators.

    Uses paragraph → sentence → word boundaries, similar to
    LangChain RecursiveCharacterTextSplitter but without the dependency.
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    separators = ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " "]
    return _recursive_split(text, separators, chunk_size, chunk_overlap)


def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Recursively split text by trying each separator in order."""
    if len(text) <= chunk_size:
        return [text]

    # Find best separator for this text
    best_sep = ""
    for sep in separators:
        if sep in text:
            best_sep = sep
            break

    if not best_sep:
        # No separator found — force split by character
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start = end - chunk_overlap if end < len(text) else end
        return chunks

    # Split by separator and merge into chunks
    parts = text.split(best_sep)
    chunks = []
    current = ""

    for part in parts:
        test = current + best_sep + part if current else part
        if len(test) <= chunk_size:
            current = test
        else:
            if current:
                chunks.append(current)
            if len(part) > chunk_size:
                # Part itself is too long — recurse with next separator
                sub_chunks = _recursive_split(
                    part, separators[separators.index(best_sep) + 1:] if best_sep in separators else [],
                    chunk_size, chunk_overlap,
                )
                chunks.extend(sub_chunks)
                current = ""
            else:
                current = part

    if current:
        chunks.append(current)

    # Apply overlap between chunks
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
            overlapped.append(overlap_text + chunks[i])
        chunks = overlapped

    return chunks


def _chunk_document(
    material_id: str,
    title: str,
    content: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Chunk a document and return chunk metadata list."""
    raw_chunks = _split_text_into_chunks(content, chunk_size, chunk_overlap)
    chunks = []
    for idx, text in enumerate(raw_chunks):
        chunks.append({
            "chunk_id": f"{material_id}_chunk_{idx}",
            "material_id": material_id,
            "title": title,
            "chunk_index": idx,
            "content": text,
            "char_count": len(text),
        })
    return chunks


def get_writing_resource_store():
    """Import and return the writing resource store."""
    from writing_resources import get_writing_resource_store as get_store
    return get_store()


def _ensure_upload_project(project_id: str) -> Any:
    """Validate that the target project exists before ingesting uploaded files."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return store


def _extract_document_content(filename: str, raw: bytes) -> str:
    """Extract textual content from an uploaded document based on file type."""
    content = ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "txt" or ext == "md":
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
    elif ext == "bib":
        for enc in ("utf-8", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
    elif ext == "pdf":
        try:
            import io
            try:
                import pymupdf  # PyMuPDF (fitz)
                doc = pymupdf.open(stream=raw, filetype="pdf")
                pages = []
                for page in doc:
                    pages.append(page.get_text())
                content = "\n\n".join(pages)
                doc.close()
            except ImportError:
                try:
                    from PyPDF2 import PdfReader
                    reader = PdfReader(io.BytesIO(raw))
                    pages = [page.extract_text() or "" for page in reader.pages]
                    content = "\n\n".join(pages)
                except ImportError:
                    content = f"[PDF 文件: {filename}，需安装 pymupdf 或 PyPDF2 才能提取文本]"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            content = f"[PDF 解析失败: {exc}]"
    elif ext in ("docx",):
        try:
            import io
            from docx import Document as DocxDocument
            doc = DocxDocument(io.BytesIO(raw))
            content = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        except ImportError:
            content = f"[DOCX 文件: {filename}，需安装 python-docx 才能提取文本]"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            content = f"[DOCX 解析失败: {exc}]"
    else:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = f"[未知格式文件: {filename}]"

    return content


def _truncate_document_content(content: str) -> str:
    """Limit oversized extracted text so upload responses stay stable."""
    max_content_len = 200_000
    if len(content) <= max_content_len:
        return content
    return content[:max_content_len] + f"\n\n[...文档内容已截断，总长度 {len(content)} 字符]"


def _normalize_project_title_for_cleanup(title: str) -> str:
    """Normalize project title for duplicate detection in maintenance cleanup."""
    normalized = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    return normalized


def _is_extraction_failure_placeholder(content: str) -> bool:
    """Check whether a stored document content is an extraction placeholder."""
    normalized = str(content or "").strip()
    if not normalized:
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in (
            "[PDF 文件:",
            "[PDF 解析失败:",
            "[DOCX 文件:",
            "[DOCX 解析失败:",
            "[未知格式文件:",
        )
    )


def _resource_richness_score(store: Any, project_id: str) -> tuple[int, int, int]:
    """Return a tuple score to keep the most valuable project in duplicate groups."""
    section_count = len(store.list_sections(project_id))
    draft_count = len(store.list_drafts(project_id))
    material_count = len(store.list_materials(project_id))
    return (material_count, draft_count, section_count)


def _analyze_cleanup_candidates(store: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect duplicate project and empty material cleanup candidates."""
    projects = store.list_projects()
    grouped_by_title: dict[str, list[Any]] = {}
    for project in projects:
        key = _normalize_project_title_for_cleanup(getattr(project, "title", ""))
        if not key:
            continue
        grouped_by_title.setdefault(key, []).append(project)

    duplicate_projects: list[dict[str, Any]] = []
    duplicate_project_ids: set[str] = set()
    for normalized_title, grouped_projects in grouped_by_title.items():
        if len(grouped_projects) <= 1:
            continue
        # Keep the project with richest content first; tie-breaker by updated_at desc.
        sorted_group = sorted(
            grouped_projects,
            key=lambda project: (
                _resource_richness_score(store, project.project_id),
                str(getattr(project, "updated_at", "")),
            ),
            reverse=True,
        )
        keeper = sorted_group[0]
        for project in sorted_group[1:]:
            duplicate_project_ids.add(project.project_id)
            duplicate_projects.append(
                {
                    "project_id": project.project_id,
                    "title": getattr(project, "title", ""),
                    "normalized_title": normalized_title,
                    "keep_project_id": keeper.project_id,
                    "keep_project_title": getattr(keeper, "title", ""),
                }
            )

    empty_materials: list[dict[str, Any]] = []
    for project in projects:
        if project.project_id in duplicate_project_ids:
            continue
        doc_store = _load_doc_store(project.project_id)
        chunk_store = _load_chunk_store(project.project_id)
        for material in store.list_materials(project.project_id):
            material_id = material.material_id
            doc_record = doc_store.get(material_id, {})
            content = str(doc_record.get("content") or "")
            chunks = chunk_store.get(material_id) or []
            has_non_empty_chunk = any(str(chunk.get("content") or "").strip() for chunk in chunks)

            if _is_extraction_failure_placeholder(content) or not has_non_empty_chunk:
                empty_materials.append(
                    {
                        "project_id": project.project_id,
                        "project_title": getattr(project, "title", ""),
                        "material_id": material_id,
                        "material_title": getattr(material, "title", ""),
                        "reason": "no_extracted_text",
                    }
                )

    return duplicate_projects, empty_materials


def _persist_uploaded_document(
    project_id: str,
    filename: str,
    content: str,
    *,
    store: Any,
) -> dict[str, Any]:
    """Create a material entry and persist its document/chunk payload."""
    summary = content[:200].replace("\n", " ").strip() if content else f"从文件 {filename} 导入"
    material = store.create_material(
        project_id=project_id,
        title=filename,
        title_en=filename,
        summary=summary,
        summary_en="",
        material_type="reference",
    )

    doc_store = _load_doc_store(project_id)
    doc_store[material.material_id] = {"title": filename, "content": content}
    _save_doc_store(project_id, doc_store)

    chunks = _chunk_document(material.material_id, filename, content)
    chunk_store = _load_chunk_store(project_id)
    chunk_store[material.material_id] = chunks
    _save_chunk_store(project_id, chunk_store)

    return {
        "material_id": material.material_id,
        "title": filename,
        "content_length": len(content),
        "chunks": len(chunks),
        "status": "ok",
    }


async def _ingest_uploaded_document(
    project_id: str,
    upload: UploadFile,
    *,
    store: Any,
) -> dict[str, Any]:
    """Read one uploaded file and persist it into the project knowledge base."""
    filename = upload.filename or "unnamed"
    raw = await upload.read()
    content = _truncate_document_content(_extract_document_content(filename, raw))

    normalized = str(content or "").strip()
    known_extract_failures = (
        normalized.startswith("[PDF 文件:"),
        normalized.startswith("[PDF 解析失败:"),
        normalized.startswith("[DOCX 文件:"),
        normalized.startswith("[DOCX 解析失败:"),
        normalized.startswith("[未知格式文件:"),
    )
    if (not normalized) or any(known_extract_failures):
        raise ValueError(
            f"文件“{filename}”未提取到可检索文本。可能是扫描版 PDF、加密文件或解析依赖缺失（建议安装 pymupdf / PyPDF2 / python-docx）"
        )

    return _persist_uploaded_document(project_id, filename, content, store=store)


def get_memory_adapter():
    """Import and return the shared memory adapter when available."""
    from python_adapter_server import get_memory_adapter as get_adapter
    return get_adapter()


def get_ai_adapter() -> Any:
    """Import and return the shared AI adapter used by association AI mode."""
    global _ai_adapter_instance
    if _ai_adapter_instance is not None:
        return _ai_adapter_instance

    try:
        from layers.ai_adapter import AIAdapter

        _ai_adapter_instance = AIAdapter(
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY") or os.environ.get("SILICONFLOW_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL") or os.environ.get("ARK_BASE_URL"),
            model=os.environ.get("OPENAI_MODEL") or os.environ.get("ARK_MODEL"),
        )
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("AI association adapter unavailable: %s", exc)
        _ai_adapter_instance = None
    return _ai_adapter_instance


def _memory_hit_to_dict(raw_hit: Any) -> dict[str, Any] | None:
    """Normalize a memory hit object into a plain mapping for the store layer."""
    if hasattr(raw_hit, "to_dict"):
        normalized = raw_hit.to_dict()
        return normalized if isinstance(normalized, dict) else None
    if isinstance(raw_hit, Mapping):
        return dict(raw_hit)
    return None


def _association_error_to_http_status(message: str) -> int:
    """Map association-layer validation failures to stable HTTP status codes."""
    lowered = message.lower()
    if "not found" in lowered:
        return 404
    return 400


def _clone_association_bundle(
    base_bundle: Any,
    *,
    mode: str,
    ai_enhanced: bool,
    association_angles: Any | None = None,
    continuation_prompts: Any | None = None,
    evidence_gaps: Any | None = None,
    recommended_memory_queries: Any | None = None,
) -> Any:
    """Rebuild a bundle while preserving the stable evidence ranking."""
    from writing_resources import WritingAssociationBundle

    return WritingAssociationBundle(
        project_id=base_bundle.project_id,
        query=base_bundle.query,
        generated_at=base_bundle.generated_at,
        draft_id=base_bundle.draft_id,
        section_id=base_bundle.section_id,
        mode=mode,
        ai_enhanced=ai_enhanced,
        focus_terms=list(base_bundle.focus_terms),
        memory_used=base_bundle.memory_used,
        memory_hit_count=base_bundle.memory_hit_count,
        related_signals=list(base_bundle.related_signals),
        association_angles=list(association_angles if association_angles is not None else base_bundle.association_angles),
        continuation_prompts=list(
            continuation_prompts if continuation_prompts is not None else base_bundle.continuation_prompts
        ),
        evidence_gaps=list(evidence_gaps if evidence_gaps is not None else base_bundle.evidence_gaps),
        recommended_memory_queries=list(
            recommended_memory_queries
            if recommended_memory_queries is not None
            else base_bundle.recommended_memory_queries
        ),
    )


async def _apply_association_mode(base_bundle: Any, mode: str, angle_limit: int) -> Any:
    """Apply AI or No-AI post-processing without mutating the evidence base."""
    adapter = get_ai_adapter()
    from writing_resources import apply_association_mode

    return await asyncio.to_thread(
        apply_association_mode,
        base_bundle,
        mode,
        adapter,
        angle_limit,
    )


@router.post("/project", response_model=ProjectPayload)
async def create_project(request: CreateProjectRequest) -> ProjectPayload:
    """Create a new writing project."""
    from writing_resources import ContentType
    store = get_writing_resource_store()
    try:
        content_type = ContentType(request.content_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid content_type: {request.content_type}")

    project = store.create_project(
        title=request.title,
        description=request.description,
        content_type=content_type,
        user_id=request.user_id,
        tags=request.tags,
        metadata={"source_folder": request.source_folder} if request.source_folder else {},
    )
    d = project.to_dict()
    d["source_folder"] = str(project.metadata.get("source_folder", ""))
    # If a source_folder is provided, create the .scholarai subdirectory upfront
    if request.source_folder:
        try:
            (Path(request.source_folder).expanduser().resolve() / _SCHOLAR_SUBDIR).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create .scholarai dir in source_folder: %s", exc)
    return ProjectPayload(**d)


@router.get("/project/{project_id}", response_model=ProjectPayload)
async def get_project(project_id: str) -> ProjectPayload:
    """Get a project by ID."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    d = project.to_dict()
    d["source_folder"] = str(project.metadata.get("source_folder", ""))
    return ProjectPayload(**d)


@router.get("/projects", response_model=list[ProjectPayload])
async def list_projects(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> list[ProjectPayload]:
    """List all projects, optionally filtered by user. Supports pagination via query params."""
    store = get_writing_resource_store()
    projects = store.list_projects(user_id=user_id)
    all_payloads = []
    for p in projects:
        d = p.to_dict()
        d["source_folder"] = str(p.metadata.get("source_folder", ""))
        all_payloads.append(ProjectPayload(**d))
    # Pagination is opt-in: if caller doesn't pass page/page_size, returns full list
    return all_payloads


@router.put("/project/{project_id}/status")
async def update_project_status(
    project_id: str,
    status: str = Query(..., description="New status"),
) -> ProjectPayload:
    """Update project status."""
    from writing_resources import ProjectStatus
    store = get_writing_resource_store()
    try:
        project_status = ProjectStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    project = store.update_project_status(project_id, project_status)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    d = project.to_dict()
    d["source_folder"] = str(project.metadata.get("source_folder", ""))
    return ProjectPayload(**d)


@router.put("/project/{project_id}/source-folder")
async def update_project_source_folder(
    project_id: str,
    source_folder: str = Query(..., description="绝对路径，留空则恢复默认存储位置"),
) -> ProjectPayload:
    """Update the source_folder of a project.

    When set, chunk / doc store JSON files will be saved inside
    ``{source_folder}/.scholarai/`` alongside the user's literature files.
    """
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    new_metadata = dict(project.metadata)
    new_metadata["source_folder"] = source_folder.strip()
    updated = store.update_project(project_id, metadata=new_metadata)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update project metadata")
    if source_folder.strip():
        try:
            (Path(source_folder.strip()).expanduser().resolve() / _SCHOLAR_SUBDIR).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create .scholarai dir: %s", exc)
    d = updated.to_dict()
    d["source_folder"] = str(updated.metadata.get("source_folder", ""))
    return ProjectPayload(**d)


@router.delete("/project/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project and all its associated resources."""
    store = get_writing_resource_store()
    deleted = store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    # Clean up doc_store JSON for this project
    doc_store_path = _get_doc_store_path(project_id)
    if doc_store_path.exists():
        try:
            doc_store_path.unlink()
        except OSError:
            logger.warning("Failed to remove doc_store file: %s", doc_store_path)
    chunk_store_path = _get_chunk_store_path(project_id)
    if chunk_store_path.exists():
        try:
            chunk_store_path.unlink()
        except OSError:
            logger.warning("Failed to remove chunk_store file: %s", chunk_store_path)
    return {"status": "deleted", "project_id": project_id}


@router.post("/project/{project_id}/scan-folder")
async def scan_project_folder(project_id: str) -> dict[str, Any]:
    """Scan the project's source_folder and ingest all literature files.

    Reads all supported files (.pdf, .docx, .doc, .txt, .md) from the project's
    source_folder and indexes them into the knowledge base.  Already-indexed
    files (same filename) are skipped.  Returns a summary of what was processed.
    """
    store = _ensure_upload_project(project_id)
    project_obj = get_writing_resource_store().get_project(project_id)
    if not project_obj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    source_folder = str(project_obj.metadata.get("source_folder", "")).strip()
    if not source_folder:
        raise HTTPException(
            status_code=400,
            detail="该项目没有设置文献文件夹（source_folder）。请先在项目设置中指定文件夹路径。",
        )
    folder_path = Path(source_folder).expanduser().resolve()
    if not folder_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"文件夹不存在或无法访问：{folder_path}",
        )

    # Collect candidate files
    candidates = [
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in _SCAN_EXTENSIONS
    ]

    # Get already-indexed titles to skip duplicates
    existing_doc_store = _load_doc_store(project_id)
    existing_titles = {v["title"] for v in existing_doc_store.values()}

    results: list[dict[str, Any]] = []
    total_chunks = 0
    skipped = 0
    failed = 0

    for file_path in candidates:
        filename = file_path.name
        if filename in existing_titles:
            skipped += 1
            results.append({"title": filename, "status": "skipped", "reason": "已索引"})
            continue
        try:
            raw = file_path.read_bytes()

            # Reuse the existing content extractor
            class _FakeUpload:
                def __init__(self, name: str, data: bytes):
                    self.filename = name
                    self._data = data
                async def read(self) -> bytes:
                    return self._data

            content = _truncate_document_content(_extract_document_content(filename, raw))
            normalized = str(content or "").strip()
            if not normalized or normalized.startswith("["):
                failed += 1
                results.append({"title": filename, "status": "error", "reason": "无法提取文本"})
                continue

            result = _persist_uploaded_document(project_id, filename, content, store=store)
            total_chunks += int(result.get("chunks") or 0)
            results.append({"title": filename, "status": "ok", "chunks": result.get("chunks")})
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results.append({"title": filename, "status": "error", "reason": str(exc)})

    return {
        "project_id": project_id,
        "folder": str(folder_path),
        "total_files": len(candidates),
        "indexed": len(candidates) - skipped - failed,
        "skipped": skipped,
        "failed": failed,
        "total_chunks": total_chunks,
        "results": results,
    }


@router.post("/section", response_model=SectionPayload)
async def create_section(request: CreateSectionRequest) -> SectionPayload:
    """Create a section within a project."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    section = store.create_section(
        project_id=request.project_id,
        title=request.title,
        order=request.order,
        description=request.description,
    )
    return SectionPayload(**section.to_dict())


@router.get("/section/{section_id}", response_model=SectionPayload)
async def get_section(section_id: str) -> SectionPayload:
    """Get a section by ID."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")
    return SectionPayload(**section.to_dict())


@router.get("/sections", response_model=list[SectionPayload])
async def list_sections(project_id: str = Query(...)) -> list[SectionPayload]:
    """List all sections in a project."""
    store = get_writing_resource_store()
    sections = store.list_sections(project_id)
    return [SectionPayload(**s.to_dict()) for s in sections]


@router.post("/material", response_model=MaterialPayload)
async def create_material(request: CreateMaterialRequest) -> MaterialPayload:
    """Create a project-scoped reference material."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    material = store.create_material(
        project_id=request.project_id,
        title=request.title,
        title_en=request.title_en,
        summary=request.summary,
        summary_en=request.summary_en,
        material_type=request.type,
        focus_points=request.focus_points,
        focus_points_en=request.focus_points_en,
    )
    return MaterialPayload(**material.to_dict())


@router.get("/material/{material_id}", response_model=MaterialPayload)
async def get_material(material_id: str) -> MaterialPayload:
    """Get a project-scoped material by ID."""
    store = get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"Material not found: {material_id}")
    return MaterialPayload(**material.to_dict())


@router.get("/materials", response_model=list[MaterialPayload])
async def list_materials(project_id: str = Query(...)) -> list[MaterialPayload]:
    """List all materials attached to a project."""
    store = get_writing_resource_store()
    materials = store.list_materials(project_id)
    return [MaterialPayload(**material.to_dict()) for material in materials]


@router.post("/upload")
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a document file, extract text content, and store as a material."""
    store = _ensure_upload_project(project_id)
    try:
        return await _ingest_uploaded_document(project_id, file, store=store)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/upload/batch")
async def upload_documents_batch(
    project_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload multiple knowledge-base documents in one request and summarize outcomes."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    store = _ensure_upload_project(project_id)
    results: list[dict[str, Any]] = []
    total_chunks = 0
    successful_files = 0
    failed_files = 0

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            result = await _ingest_uploaded_document(project_id, upload, store=store)
            total_chunks += int(result.get("chunks") or 0)
            successful_files += 1
            results.append(result)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            failed_files += 1
            results.append({
                "title": filename,
                "status": "error",
                "error": str(exc),
            })

    return {
        "project_id": project_id,
        "total_files": len(files),
        "successful_files": successful_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "results": results,
    }


@router.get("/documents")
async def get_project_documents(project_id: str = Query(...)) -> list[dict[str, str]]:
    """Get all document contents for a project (for RAG context)."""
    doc_store = _load_doc_store(project_id)
    return [
        {"material_id": mid, "title": doc["title"], "content": doc["content"]}
        for mid, doc in doc_store.items()
    ]


@router.get("/chunks")
async def get_project_chunks(
    project_id: str = Query(...),
    material_id: str | None = Query(None, description="Filter by material"),
) -> dict[str, Any]:
    """Get chunked document content for a project (for smarter RAG context).

    Returns chunks instead of full documents, allowing the frontend to
    send only relevant chunks to the LLM.
    """
    chunk_store = _ensure_project_chunks(project_id, material_id=material_id)
    all_chunks: list[dict[str, Any]] = []
    for mid, chunks in chunk_store.items():
        if material_id and mid != material_id:
            continue
        all_chunks.extend(chunks)
    return {
        "project_id": project_id,
        "total_chunks": len(all_chunks),
        "chunks": all_chunks,
    }


@router.get("/chunks/search")
async def search_chunks(
    project_id: str = Query(...),
    query: str = Query(..., min_length=1, description="搜索词"),
    top_k: int = Query(10, ge=1, le=50, description="返回最相关的 N 个chunk"),
) -> dict[str, Any]:
    """Simple keyword-based chunk search for RAG context retrieval.

    Scores chunks by keyword overlap with the query. For production use,
    this should be replaced with embedding-based vector search.
    """
    chunk_store = _ensure_project_chunks(project_id)
    all_chunks: list[dict[str, Any]] = []
    for chunks in chunk_store.values():
        all_chunks.extend(chunks)

    if not all_chunks:
        return {"project_id": project_id, "query": query, "results": []}

    query_text = query.lower().strip()
    query_tokens = _tokenize_search_text(query_text)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in all_chunks:
        title = str(chunk.get("title", "")).lower()
        text = str(chunk.get("content", "")).lower()
        combined = f"{title}\n{text}".strip()
        chunk_tokens = _tokenize_search_text(combined)

        score = 0.0
        if query_text and query_text in combined:
            score += 12.0
        if query_text and query_text in title:
            score += 4.0

        matched_tokens = query_tokens & chunk_tokens
        score += len(matched_tokens) * 2.0
        if query_tokens:
            score += (len(matched_tokens) / len(query_tokens)) * 4.0

        for token in query_tokens:
            if len(token) > 1 and token in title:
                score += 1.5

        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = _select_diverse_top_chunks(scored, top_k=top_k)
    return {
        "project_id": project_id,
        "query": query,
        "results": [{"score": round(s, 2), **c} for s, c in top if s > 0],
    }


@router.get("/material/{material_id}/chunks")
async def get_material_chunks(
    material_id: str,
    project_id: str = Query(...),
) -> dict[str, Any]:
    """Get chunks for a specific material."""
    chunk_store = _ensure_project_chunks(project_id, material_id=material_id)
    chunks = chunk_store.get(material_id, [])
    return {
        "material_id": material_id,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }


@router.post("/draft", response_model=DraftPayload)
async def create_draft(request: CreateDraftRequest) -> DraftPayload:
    """Create a new draft."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    if request.section_id:
        section = store.get_section(request.section_id)
        if not section:
            raise HTTPException(status_code=404, detail=f"Section not found: {request.section_id}")

    draft = store.create_draft(
        project_id=request.project_id,
        title=request.title,
        content=request.content,
        section_id=request.section_id,
        edited_by=request.edited_by,
        citation_anchors=[anchor.model_dump() for anchor in request.citation_anchors],
    )
    return DraftPayload(**draft.to_dict())


@router.get("/draft/{draft_id}", response_model=DraftPayload)
async def get_draft(draft_id: str) -> DraftPayload:
    """Get a draft by ID."""
    store = get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@router.get("/drafts", response_model=list[DraftPayload])
async def list_drafts(
    project_id: str = Query(...),
    section_id: str | None = Query(None),
) -> list[DraftPayload]:
    """List all drafts, optionally filtered by section."""
    store = get_writing_resource_store()
    drafts = store.list_drafts(project_id, section_id=section_id)
    return [DraftPayload(**d.to_dict()) for d in drafts]


@router.put("/draft/{draft_id}")
async def save_draft(draft_id: str, request: SaveDraftRequest) -> DraftPayload:
    """Save draft content."""
    store = get_writing_resource_store()
    draft = store.save_draft(
        draft_id,
        request.content,
        edited_by=request.edited_by,
        citation_anchors=[anchor.model_dump() for anchor in request.citation_anchors],
        create_revision=True,
    )
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@router.get("/revision/{revision_id}", response_model=RevisionPayload)
async def get_revision(revision_id: str) -> RevisionPayload:
    """Get a revision by ID."""
    store = get_writing_resource_store()
    revision = store.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail=f"Revision not found: {revision_id}")
    return RevisionPayload(**revision.to_dict())


@router.get("/revisions", response_model=list[RevisionPayload])
async def list_revisions(draft_id: str = Query(...)) -> list[RevisionPayload]:
    """List all revisions for a draft."""
    store = get_writing_resource_store()
    revisions = store.list_revisions(draft_id)
    return [RevisionPayload(**r.to_dict()) for r in revisions]


@router.post("/draft/{draft_id}/restore")
async def restore_revision(
    draft_id: str,
    revision_id: str = Query(...),
) -> DraftPayload:
    """Restore a draft from a revision."""
    store = get_writing_resource_store()
    draft = store.restore_revision(draft_id, revision_id)
    if not draft:
        raise HTTPException(
            status_code=404,
            detail=f"Draft {draft_id} or revision {revision_id} not found",
        )
    return DraftPayload(**draft.to_dict())


@router.post("/association", response_model=WritingAssociationPayload)
async def build_writing_association(
    request: BuildAssociationRequest,
) -> WritingAssociationPayload:
    """Build associative writing guidance from project state, retrieval evidence, and mode."""
    store = get_writing_resource_store()
    memory_hits: list[dict[str, Any]] = []

    if request.use_memory:
        adapter = get_memory_adapter()
        if adapter is not None:
            memory_query = request.memory_query.strip() if request.memory_query else request.query
            try:
                memory_response = adapter.search(
                    query=memory_query,
                    wing=request.wing,
                    room=request.room,
                    limit=request.memory_limit,
                )
            except Exception as exc:  # pragma: no cover - optional dependency path
                logger.warning("Memory association lookup failed: %s", exc)
                memory_response = None

            if memory_response is not None and getattr(memory_response, "available", False):
                raw_results = getattr(memory_response, "results", [])
                for raw_hit in raw_results:
                    normalized_hit = _memory_hit_to_dict(raw_hit)
                    if normalized_hit is not None:
                        memory_hits.append(normalized_hit)

    try:
        bundle = store.build_association_bundle(
            project_id=request.project_id,
            query=request.query,
            draft_id=request.draft_id,
            section_id=request.section_id,
            memory_hits=memory_hits,
            retrieval_hits=request.retrieval_hits,
            signal_limit=request.signal_limit,
            angle_limit=request.angle_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_association_error_to_http_status(str(exc)),
            detail=str(exc),
        ) from exc

    bundle = await _apply_association_mode(bundle, request.mode, request.angle_limit)
    return WritingAssociationPayload(**bundle.to_dict())


# =========================================================================
# Export Endpoints (learned from openhanako desk.js + open-webui export patterns)
# =========================================================================

class ProjectExportFormat(str, __import__("enum").Enum):
    MARKDOWN = "markdown"
    JSON = "json"


@router.get("/project/{project_id}/export", tags=["Export"])
async def export_project(
    project_id: str,
    format: ProjectExportFormat = Query(ProjectExportFormat.MARKDOWN, description="导出格式"),
) -> dict[str, Any]:
    """Export a complete project with its sections, drafts, and materials."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    sections = store.list_sections(project_id)
    drafts = store.list_drafts(project_id)
    materials = store.list_materials(project_id)
    doc_store = _load_doc_store(project_id)

    if format == ProjectExportFormat.JSON:
        return {
            "project": project.to_dict(),
            "sections": [s.to_dict() for s in sections],
            "drafts": [d.to_dict() for d in drafts],
            "materials": [m.to_dict() for m in materials],
            "document_count": len(doc_store),
        }

    # Markdown export
    lines = [f"# {project.title}\n"]
    if project.description:
        lines.append(f"> {project.description}\n")
    lines.append(f"状态: {project.status} | 创建: {project.created_at}\n")

    # Sort sections by order
    sorted_sections = sorted(sections, key=lambda s: s.order)
    section_map = {s.section_id: s for s in sorted_sections}

    for section in sorted_sections:
        lines.append(f"\n## {section.title}\n")
        if section.description:
            lines.append(f"{section.description}\n")
        section_drafts = [d for d in drafts if getattr(d, "section_id", None) == section.section_id]
        for draft in section_drafts:
            lines.append(f"\n### {draft.title}\n")
            lines.append(f"{draft.content}\n")

    # Orphan drafts (no section)
    orphans = [d for d in drafts if not getattr(d, "section_id", None)]
    if orphans:
        lines.append("\n## 未分类草稿\n")
        for draft in orphans:
            lines.append(f"\n### {draft.title}\n")
            lines.append(f"{draft.content}\n")

    # References
    if materials:
        lines.append("\n## 参考文献\n")
        for i, mat in enumerate(materials, 1):
            title = mat.title or mat.title_en or "无标题"
            lines.append(f"{i}. {title}")
            if mat.summary:
                lines.append(f"   摘要: {mat.summary[:100]}...")
            lines.append("")

    return {
        "project_id": project_id,
        "format": "markdown",
        "filename": f"{project.title}.md",
        "content": "\n".join(lines),
    }


# =========================================================================
# Statistics Endpoints (learned from open-webui analytics & openhanako diary)
# =========================================================================

@router.get("/project/{project_id}/stats", tags=["Statistics"])
async def get_project_stats(project_id: str) -> dict[str, Any]:
    """Get comprehensive statistics for a project."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    sections = store.list_sections(project_id)
    drafts = store.list_drafts(project_id)
    materials = store.list_materials(project_id)
    doc_store = _load_doc_store(project_id)

    # Word count across all drafts
    total_words = sum(len(d.content) for d in drafts if hasattr(d, "content") and d.content)

    # Revision count
    total_revisions = sum(
        len(store.list_revisions(d.draft_id)) for d in drafts
    )

    return {
        "project_id": project_id,
        "title": project.title,
        "status": project.status,
        "section_count": len(sections),
        "draft_count": len(drafts),
        "material_count": len(materials),
        "document_count": len(doc_store),
        "total_characters": total_words,
        "total_revisions": total_revisions,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.get("/stats/overview", tags=["Statistics"])
async def get_global_stats() -> dict[str, Any]:
    """Get global statistics across all projects."""
    store = get_writing_resource_store()
    projects = store.list_projects()
    total_drafts = 0
    total_materials = 0
    total_chars = 0
    status_counts: dict[str, int] = {}

    for p in projects:
        drafts = store.list_drafts(p.project_id)
        materials = store.list_materials(p.project_id)
        total_drafts += len(drafts)
        total_materials += len(materials)
        total_chars += sum(len(d.content) for d in drafts if hasattr(d, "content") and d.content)
        status = p.status if isinstance(p.status, str) else p.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "project_count": len(projects),
        "draft_count": total_drafts,
        "material_count": total_materials,
        "total_characters": total_chars,
        "projects_by_status": status_counts,
    }


# =========================================================================
# Batch Operations (learned from openhanako / open-webui bulk endpoints)
# =========================================================================

class BatchDeleteRequest(__import__("pydantic").BaseModel):
    material_ids: list[str] = __import__("pydantic").Field(..., min_length=1, max_length=50, description="要删除的素材 ID 列表")


class CleanupRequest(__import__("pydantic").BaseModel):
    dry_run: bool = True


@router.post("/maintenance/cleanup", tags=["Resources"])
async def cleanup_historical_dirty_data(request: CleanupRequest) -> dict[str, Any]:
    """Preview or execute cleanup for duplicate projects and non-extractable materials."""
    store = get_writing_resource_store()
    duplicate_projects, empty_materials = _analyze_cleanup_candidates(store)

    preview = {
        "duplicate_project_count": len(duplicate_projects),
        "empty_material_count": len(empty_materials),
        "duplicate_projects": duplicate_projects,
        "empty_materials": empty_materials,
    }

    if request.dry_run:
        return {
            "dry_run": True,
            "preview": preview,
            "deleted": {
                "duplicate_project_count": 0,
                "empty_material_count": 0,
                "duplicate_projects": [],
                "empty_materials": [],
            },
        }

    deleted_duplicate_projects: list[str] = []
    deleted_empty_materials: list[str] = []

    for item in duplicate_projects:
        project_id = str(item.get("project_id") or "")
        if not project_id:
            continue
        if store.delete_project(project_id):
            deleted_duplicate_projects.append(project_id)
            doc_store_path = _get_doc_store_path(project_id)
            if doc_store_path.exists():
                try:
                    doc_store_path.unlink()
                except OSError:
                    logger.warning("Failed to remove doc_store file during cleanup: %s", doc_store_path)
            chunk_store_path = _get_chunk_store_path(project_id)
            if chunk_store_path.exists():
                try:
                    chunk_store_path.unlink()
                except OSError:
                    logger.warning("Failed to remove chunk_store file during cleanup: %s", chunk_store_path)

    for item in empty_materials:
        project_id = str(item.get("project_id") or "")
        material_id = str(item.get("material_id") or "")
        if not material_id or not project_id:
            continue
        if store.delete_material(material_id):
            deleted_empty_materials.append(material_id)
            doc_store = _load_doc_store(project_id)
            if material_id in doc_store:
                del doc_store[material_id]
                _save_doc_store(project_id, doc_store)
            chunk_store = _load_chunk_store(project_id)
            if material_id in chunk_store:
                del chunk_store[material_id]
                _save_chunk_store(project_id, chunk_store)

    return {
        "dry_run": False,
        "preview": preview,
        "deleted": {
            "duplicate_project_count": len(deleted_duplicate_projects),
            "empty_material_count": len(deleted_empty_materials),
            "duplicate_projects": deleted_duplicate_projects,
            "empty_materials": deleted_empty_materials,
        },
    }


@router.post("/materials/batch-delete", tags=["Resources"])
async def batch_delete_materials(request: BatchDeleteRequest) -> dict[str, Any]:
    """Batch delete materials from a project."""
    store = get_writing_resource_store()
    deleted = []
    not_found = []
    for mid in request.material_ids:
        material = store.get_material(mid)
        if material:
            project_id = material.project_id
            store.delete_material(mid)

            doc_store = _load_doc_store(project_id)
            if mid in doc_store:
                del doc_store[mid]
                _save_doc_store(project_id, doc_store)

            chunk_store = _load_chunk_store(project_id)
            if mid in chunk_store:
                del chunk_store[mid]
                _save_chunk_store(project_id, chunk_store)

            deleted.append(mid)
        else:
            not_found.append(mid)
    return {
        "deleted": deleted,
        "not_found": not_found,
        "deleted_count": len(deleted),
    }


@router.delete("/material/{material_id}", tags=["Resources"])
async def delete_material(material_id: str) -> dict[str, str]:
    """Delete a single material by ID."""
    store = get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    # Also clean doc_store entry if exists
    project_id = material.project_id
    store.delete_material(material_id)

    doc_store = _load_doc_store(project_id)
    if material_id in doc_store:
        del doc_store[material_id]
        _save_doc_store(project_id, doc_store)

    chunk_store = _load_chunk_store(project_id)
    if material_id in chunk_store:
        del chunk_store[material_id]
        _save_chunk_store(project_id, chunk_store)

    return {"status": "deleted", "material_id": material_id}


@router.delete("/draft/{draft_id}", tags=["Resources"])
async def delete_draft(draft_id: str) -> dict[str, str]:
    """Delete a draft by ID."""
    store = get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"草稿不存在: {draft_id}")
    store.delete_draft(draft_id)
    return {"status": "deleted", "draft_id": draft_id}


@router.delete("/section/{section_id}", tags=["Resources"])
async def delete_section(section_id: str) -> dict[str, str]:
    """Delete a section by ID."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"章节不存在: {section_id}")
    store.delete_section(section_id)
    return {"status": "deleted", "section_id": section_id}


# =========================================================================
# Section / Draft Update Endpoints (RESTful completeness)
# =========================================================================

class UpdateSectionRequest(__import__("pydantic").BaseModel):
    title: str | None = None
    description: str | None = None
    order: int | None = None


@router.put("/section/{section_id}", tags=["Resources"])
async def update_section(section_id: str, request: UpdateSectionRequest) -> SectionPayload:
    """Update section title, description, or order."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"章节不存在: {section_id}")

    updates: dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.description is not None:
        updates["description"] = request.description
    if request.order is not None:
        updates["order"] = request.order

    if updates:
        updated = store.update_section(section_id, **updates)
        if updated:
            return SectionPayload(**updated.to_dict())

    return SectionPayload(**section.to_dict())


class UpdateProjectRequest(__import__("pydantic").BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


@router.put("/project/{project_id}", tags=["Resources"])
async def update_project(project_id: str, request: UpdateProjectRequest) -> ProjectPayload:
    """Update project title, description, or tags."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    updates: dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.description is not None:
        updates["description"] = request.description
    if request.tags is not None:
        updates["tags"] = request.tags

    if updates:
        updated = store.update_project(project_id, **updates)
        if updated:
            return ProjectPayload(**updated.to_dict())

    return ProjectPayload(**project.to_dict())
