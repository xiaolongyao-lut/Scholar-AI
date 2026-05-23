# -*- coding: utf-8 -*-
"""Upload / search / document-serving endpoints split out of resources_router.__init__.

All references to module-level helpers go through ``_rr.X`` (absolute import
of the package) so that pytest ``monkeypatch.setattr(rr, "X", ...)`` keeps
affecting the live endpoint behaviour.
"""

from pathlib import Path
from typing import Any

from fastapi import HTTPException, Query, UploadFile, File, Form

import routers.resources_router as _rr


# =========================================================================
# Upload Endpoints
# =========================================================================

@_rr.router.post("/upload")
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a document file, extract text content, and store as a material."""
    store = _rr._ensure_upload_project(project_id)
    try:
        return await _rr._ingest_uploaded_document(project_id, file, store=store)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@_rr.router.post("/upload/batch")
async def upload_documents_batch(
    project_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload multiple knowledge-base documents in one request and summarize outcomes."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    store = _rr._ensure_upload_project(project_id)
    results: list[dict[str, Any]] = []
    total_chunks = 0
    successful_files = 0
    failed_files = 0
    duplicate_files = 0

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            result = await _rr._ingest_uploaded_document(project_id, upload, store=store)
            if result.get("status") == "duplicate":
                duplicate_files += 1
            else:
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
        "duplicate_files": duplicate_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "results": results,
    }


# =========================================================================
# Documents / Chunks Read Endpoints
# =========================================================================

@_rr.router.get("/documents")
async def get_project_documents(project_id: str = Query(...)) -> list[dict[str, str]]:
    """Get all document contents for a project (for RAG context)."""
    doc_store = _rr._load_doc_store(project_id)
    return [
        {"material_id": mid, "title": doc["title"], "content": doc["content"]}
        for mid, doc in doc_store.items()
    ]


@_rr.router.get("/chunks")
async def get_project_chunks(
    project_id: str = Query(...),
    material_id: str | None = Query(None, description="Filter by material"),
) -> dict[str, Any]:
    """Get chunked document content for a project (for smarter RAG context).

    Returns chunks instead of full documents, allowing the frontend to
    send only relevant chunks to the LLM.
    """
    chunk_store = _rr._ensure_project_chunks(project_id, material_id=material_id)
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


def find_chunk_locator(
    chunk_store: dict[str, list[dict[str, Any]]],
    chunk_id: str,
) -> dict[str, Any] | None:
    """Locate a chunk by id inside an already-loaded chunk store.

    Pure read; no chunk store mutation, no persistence call. Returns
    ``None`` when the chunk_id is not present in any material under the
    project, otherwise the locator dict the endpoint serializes.
    """
    if not isinstance(chunk_id, str) or not chunk_id:
        return None
    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            if chunk.get("chunk_id") != chunk_id:
                continue
            page_value = chunk.get("page")
            page = int(page_value) if isinstance(page_value, int) and page_value >= 1 else None
            chunk_index_value = chunk.get("chunk_index")
            chunk_index = (
                int(chunk_index_value)
                if isinstance(chunk_index_value, int) and chunk_index_value >= 0
                else None
            )
            return {
                "material_id": material_id,
                "chunk_id": chunk_id,
                "page": page,
                "chunk_index": chunk_index,
            }
    return None


@_rr.router.get("/chunks/{chunk_id}/locator", tags=["Resources"])
async def locate_chunk(
    chunk_id: str,
    project_id: str = Query(..., min_length=1, description="Project that owns the chunk"),
) -> dict[str, Any]:
    """Resolve a chunk_id to {material_id, chunk_id, page, chunk_index}.

    Read-only over the existing chunk store. Returns:
      - 200 with the locator dict on success.
      - 404 when chunk_id is not present in the project chunk store.
      - 422 when project_id is missing or blank (FastAPI Query validation).
    """
    chunk_store = _rr._load_chunk_store(project_id)
    locator = find_chunk_locator(chunk_store, chunk_id)
    if locator is None:
        raise HTTPException(
            status_code=404,
            detail=f"chunk_id 未在项目 chunk store 中找到: {chunk_id}",
        )
    return locator


@_rr.router.get("/chunks/search")
async def search_chunks(
    project_id: str = Query(...),
    query: str = Query(..., min_length=1, description="搜索词"),
    top_k: int = Query(10, ge=1, le=50, description="返回最相关的 N 个chunk"),
    ingest_mode: str = Query("none", description="提问前置入库模式：none/query/full"),
    ingest_limit: int = Query(8, ge=1, le=128, description="query 模式最多入库候选文件数"),
    scan_mode: str = Query("fast", description="入库执行模式：legacy/fast"),
    scan_batch_size: int = Query(24, ge=1, le=256, description="入库批大小"),
    scan_max_workers: int = Query(8, ge=1, le=64, description="入库并发 worker 数"),
) -> dict[str, Any]:
    """Chunk search with optional query-driven pre-ingestion.

    - ingest_mode=none: pure retrieval on existing chunks
    - ingest_mode=query: ingest only query-relevant pending files
    - ingest_mode=full: ingest all pending files before retrieval
    """
    # When called directly (not via FastAPI DI), Query params are descriptor objects
    if hasattr(ingest_mode, "default"):
        ingest_mode = ingest_mode.default
    normalized_ingest_mode = str(ingest_mode or "").strip().lower()
    if normalized_ingest_mode not in _rr._INGEST_MODES:
        raise HTTPException(status_code=400, detail=f"ingest_mode 不支持: {ingest_mode}，可选值: none, query, full")

    ingest_meta: dict[str, Any] = {
        "enabled": normalized_ingest_mode != "none",
        "mode": normalized_ingest_mode,
        "indexed": 0,
        "queued": 0,
        "failed": 0,
        "skipped": 0,
        "workers": 1,
    }

    if normalized_ingest_mode != "none":
        store = _rr._ensure_upload_project(project_id)
        project_obj = _rr.get_writing_resource_store().get_project(project_id)
        source_folder = str((project_obj.metadata.get("source_folder") if project_obj else "") or "").strip()

        if source_folder:
            folder_path = Path(source_folder).expanduser().resolve()
            if folder_path.is_dir():
                candidate_payload = _rr._collect_pending_scan_candidates(project_id, folder_path)
                pending_candidates = list(candidate_payload["pending"])
                pending_total = len(pending_candidates)
                ingest_meta["skipped"] = len(candidate_payload["skipped_results"])
                ingest_meta["failed"] = len(candidate_payload["failed_results"])
                ingest_meta["already_indexed"] = len(candidate_payload.get("existing_fingerprints") or [])

                zotero_title_map = _rr._load_zotero_title_map(folder_path)
                if normalized_ingest_mode == "query":
                    pending_candidates = _rr._select_query_pending_candidates(
                        pending_candidates,
                        query=query,
                        zotero_title_map=zotero_title_map,
                        ingest_limit=ingest_limit,
                    )

                ingest_meta["queued"] = len(pending_candidates)
                _rr.logger.info(
                    "chunks_search_ingest: project_id=%s mode=%s query=%r "
                    "pending_total=%d already_indexed=%d query_selected=%d "
                    "skipped=%d failed=%d source_folder=%s",
                    project_id, normalized_ingest_mode, query[:80],
                    pending_total, ingest_meta["already_indexed"], len(pending_candidates),
                    ingest_meta["skipped"], ingest_meta["failed"], folder_path,
                )
                if pending_candidates:
                    ingest_payload = _rr._ingest_pending_candidates(
                        project_id,
                        store=store,
                        pending_candidates=pending_candidates,
                        zotero_title_map=zotero_title_map,
                        scan_mode=scan_mode,
                        batch_size=scan_batch_size,
                        max_workers=scan_max_workers,
                        existing_titles=candidate_payload["existing_titles"],
                        existing_fingerprints=candidate_payload["existing_fingerprints"],
                    )
                    ingest_meta["indexed"] = int(ingest_payload["indexed"])
                    ingest_meta["failed"] = int(ingest_meta["failed"]) + int(ingest_payload["failed"])
                    ingest_meta["workers"] = int(ingest_payload["workers"])
                    _rr.logger.info(
                        "chunks_search_ingest_done: project_id=%s indexed=%d failed=%d workers=%d",
                        project_id, ingest_meta["indexed"], ingest_meta["failed"], ingest_meta["workers"],
                    )
            else:
                ingest_meta["error"] = f"source_folder 无法访问: {folder_path}"
                _rr.logger.warning(
                    "chunks_search_ingest_skip: project_id=%s reason=source_folder_unreachable path=%s",
                    project_id, folder_path,
                )
        else:
            ingest_meta["error"] = "项目未配置 source_folder，已跳过前置入库"
            _rr.logger.warning(
                "chunks_search_ingest_skip: project_id=%s reason=no_source_folder", project_id,
            )

    chunk_store = _rr._ensure_project_chunks(project_id)
    all_chunks: list[dict[str, Any]] = []
    for chunks in chunk_store.values():
        all_chunks.extend(chunks)

    if not all_chunks:
        return {"project_id": project_id, "query": query, "ingest": ingest_meta, "results": []}

    top = _rr._select_diverse_top_chunks(
        _rr._score_chunks_for_query(all_chunks, query),
        top_k=top_k,
    )
    return {
        "project_id": project_id,
        "query": query,
        "ingest": ingest_meta,
        "results": [{"score": round(s, 2), **c} for s, c in top if s > 0],
    }


# =========================================================================
# Document File Serving
# =========================================================================

@_rr.router.get("/document/{material_id}/file", tags=["Resources"])
async def serve_document_file(material_id: str, as_: str = Query("", alias="as")):
    """Serve the original file for a material (e.g. PDF for in-app viewing).

    ``?as=bin`` returns the bytes with media_type=application/octet-stream so
    browser download-manager extensions (IDM, FlashGet, 迅雷, etc.) don't
    recognise it as a PDF and divert the in-app reader's fetch into a save
    dialog. Used by the in-app PDF viewer; everything else (default) keeps
    the natural MIME so e.g. right-click "open in new tab" still works.
    """
    store = _rr.get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        _rr.logger.warning(
            "serve_document_file: material_not_found material_id=%s", material_id
        )
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    project_id = material.project_id
    doc_store = _rr._load_doc_store(project_id)
    doc_entry = doc_store.get(material_id, {})
    source_relative = doc_entry.get("source_relative_path", "")

    if not source_relative:
        _rr.logger.warning(
            "serve_document_file: no_source_path material_id=%s project_id=%s",
            material_id, project_id,
        )
        raise HTTPException(status_code=404, detail="无原始文件路径记录")

    source_folder = _rr._get_project_source_folder(project_id)
    # 0.1.8.1 hotfix: try the user-root source_files/ fallback first when the
    # project doesn't have a configured source_folder, so files coming from the
    # upload button (which now persist there) resolve correctly. Falls through
    # to the legacy behaviour for projects that do have source_folder set.
    from project_paths import project_data_path
    candidates: list[Path] = []
    if source_folder:
        candidates.append(Path(source_folder).expanduser().resolve() / source_relative)
        candidates.append(project_data_path(project_id, "source_files", source_relative))
    else:
        candidates.append(project_data_path(project_id, "source_files", source_relative))
        candidates.append(Path(source_relative).expanduser().resolve())

    candidate = next((p for p in candidates if p.exists()), candidates[0])

    if not candidate.exists():
        _rr.logger.warning(
            "serve_document_file: file_missing material_id=%s project_id=%s "
            "source_folder=%s source_relative=%s tried=%s",
            material_id, project_id, source_folder, source_relative,
            [str(p) for p in candidates],
        )
        raise HTTPException(status_code=404, detail=f"文件不存在: {candidate.name}")

    from fastapi.responses import FileResponse

    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }
    ext = candidate.suffix.lower()
    # 0.1.8.1: when the in-app reader requests ?as=bin we hand back the
    # bytes as a generic binary stream so browser download-manager
    # extensions don't recognise the response as a PDF and steal it from
    # the JS fetch. Other callers (right-click open in new tab, direct
    # link sharing) get the real MIME so the browser's native viewer
    # still works.
    if as_.strip().lower() == "bin":
        media_type = "application/octet-stream"
    else:
        media_type = media_types.get(ext, "application/octet-stream")
    response = FileResponse(path=str(candidate), media_type=media_type)
    safe_name = candidate.name.encode("utf-8").decode("latin-1", errors="ignore")
    response.headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
    return response


@_rr.router.get("/document/{material_id}/file_b64", tags=["Resources"])
async def serve_document_file_base64(material_id: str) -> dict[str, Any]:
    """Return the original file as base64 inside a JSON envelope.

    0.1.8.1 hotfix: system-level download managers (FlashGet / 网际快车,
    IDM, 迅雷, JDownloader) hook the browser network layer and replace
    any binary response that looks like a file with status 204, hijacking
    the body for their own download queue. The in-app PDF reader can't
    receive bytes through that channel. Wrapping the bytes in a JSON
    envelope makes the response look like an API call, which those tools
    leave alone. The frontend atob-decodes and feeds pdf.js.
    """
    store = _rr.get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        _rr.logger.warning(
            "serve_document_file_base64: material_not_found material_id=%s", material_id,
        )
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    project_id = material.project_id
    doc_store = _rr._load_doc_store(project_id)
    doc_entry = doc_store.get(material_id, {})
    source_relative = doc_entry.get("source_relative_path", "")
    if not source_relative:
        raise HTTPException(status_code=404, detail="无原始文件路径记录")

    source_folder = _rr._get_project_source_folder(project_id)
    from project_paths import project_data_path
    cand_list: list[Path] = []
    if source_folder:
        cand_list.append(Path(source_folder).expanduser().resolve() / source_relative)
        cand_list.append(project_data_path(project_id, "source_files", source_relative))
    else:
        cand_list.append(project_data_path(project_id, "source_files", source_relative))
        cand_list.append(Path(source_relative).expanduser().resolve())

    target = next((p for p in cand_list if p.exists()), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"文件不存在: {Path(source_relative).name}")

    import base64
    raw = target.read_bytes()
    ext_l = target.suffix.lower()
    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(ext_l, "application/octet-stream")
    return {
        "data": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
        "mime": mime,
        "name": target.name,
    }
