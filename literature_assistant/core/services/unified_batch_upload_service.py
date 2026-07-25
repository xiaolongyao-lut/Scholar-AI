# -*- coding: utf-8 -*-
"""Unified batch ingestion service for uploads and source-folder scans."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, cast

from fastapi import UploadFile

try:
    from routers.resources_router._document_extraction import ExtractedDocumentPayload
except ImportError:  # pragma: no cover - package import fallback
    from literature_assistant.core.routers.resources_router._document_extraction import (
        ExtractedDocumentPayload,
    )

try:
    from pdf_backends import PDFParseResult
    from pdf_backends.ocr_ingestion import apply_pdf_ocr_if_needed
except ImportError:  # pragma: no cover - package import fallback
    from literature_assistant.core.pdf_backends import PDFParseResult
    from literature_assistant.core.pdf_backends.ocr_ingestion import apply_pdf_ocr_if_needed

try:
    from services.smart_filter_engine import SmartFilterEngine, SmartFilterReport
except ImportError:  # pragma: no cover - package import fallback
    from literature_assistant.core.services.smart_filter_engine import (
        SmartFilterEngine,
        SmartFilterReport,
    )


logger = logging.getLogger("UnifiedBatchUploadService")


class UploadedSourceFile(Protocol):
    """Protocol for the upload persistence object returned by resources_router."""

    path: Path
    fingerprint: str
    size: int
    created: bool


PersistUploadFn = Callable[[str, str, UploadFile], Any]
DocStore = dict[str, dict[str, Any]]
DocStoreUpdater = Callable[[DocStore], DocStore]
LoadDocStoreFn = Callable[[str], DocStore]
UpdateDocStoreFn = Callable[[str, DocStoreUpdater], DocStore | None]
SaveDocStoreFn = Callable[[str, DocStore], None]
CleanupUploadedSourceFn = Callable[[str, UploadedSourceFile], bool]


class ExtractPayloadFn(Protocol):
    """Callable shape for document extraction with optional project context."""

    def __call__(
        self,
        filename: str,
        source_path: Path,
        *,
        project_id: str | None = None,
    ) -> ExtractedDocumentPayload:
        """Return extracted content and optional structured blocks."""
        ...


TruncateContentFn = Callable[[str], str]
EnsureExtractedTextFn = Callable[[str, str], str]
WriteMaterialFn = Callable[..., dict[str, Any]]
SafeFilenameFn = Callable[[str], str]


@dataclass(frozen=True)
class BatchSource:
    """One persisted source file ready for filtering and extraction.

    Args:
        source_path: Existing local file path.
        display_name: Human-readable material title.
        source_relative_path: Project-relative source reference persisted in
            the doc store.
        source_fingerprint: Stable fingerprint used for deduplication.
        source_size: Source byte size.
        source_mtime: Optional source modification time.
    """

    source_path: Path
    display_name: str
    source_relative_path: str
    source_fingerprint: str
    source_size: int
    source_mtime: float | None = None


@dataclass(frozen=True)
class BatchUploadResult:
    """Batch ingestion result preserving the legacy upload response fields."""

    project_id: str
    total_files: int
    successful_files: int
    duplicate_files: int
    queued_files: int
    failed_files: int
    total_chunks: int
    results: list[dict[str, Any]] = field(default_factory=list)
    skipped_files: int = 0
    filter_report: SmartFilterReport | None = None
    processing_mode: str = "unified_batch"
    accepted_files: int | None = None
    completed_files: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result to the route's JSON response shape."""

        payload: dict[str, Any] = {
            "project_id": self.project_id,
            "total_files": self.total_files,
            "accepted_files": (
                self.accepted_files
                if self.accepted_files is not None
                else self.successful_files + self.queued_files
            ),
            "completed_files": (
                self.completed_files
                if self.completed_files is not None
                else self.successful_files
            ),
            "successful_files": self.successful_files,
            "duplicate_files": self.duplicate_files,
            "queued_files": self.queued_files,
            "failed_files": self.failed_files,
            "total_chunks": self.total_chunks,
            "results": list(self.results),
            "processing_mode": self.processing_mode,
        }
        if self.skipped_files:
            payload["skipped_files"] = self.skipped_files
        if self.filter_report is not None:
            payload["filter"] = self.filter_report.to_dict()
        return payload


class UnifiedBatchUploadService:
    """Shared ingestion path for multi-file uploads and source-folder scans."""

    def __init__(
        self,
        *,
        persist_upload: PersistUploadFn,
        load_doc_store: LoadDocStoreFn,
        extract_payload: ExtractPayloadFn,
        truncate_content: TruncateContentFn,
        ensure_extracted_text: EnsureExtractedTextFn,
        write_material_document_content: WriteMaterialFn,
        safe_upload_filename: SafeFilenameFn,
        update_doc_store: UpdateDocStoreFn | None = None,
        save_doc_store: SaveDocStoreFn | None = None,
        cleanup_uploaded_source: CleanupUploadedSourceFn | None = None,
        filter_engine: SmartFilterEngine | None = None,
    ) -> None:
        """Wire the service to existing router persistence helpers.

        Args:
            persist_upload: Existing streaming upload-to-source-file helper.
            load_doc_store: Existing project doc-store reader.
            update_doc_store: Project-locked document-store mutation helper.
            save_doc_store: Legacy document-store writer. Used only when
                ``update_doc_store`` is omitted and adapted to read-update-save.
            cleanup_uploaded_source: Optional ownership-aware callback that
                removes a newly-created source only when no store row refers to it.
            extract_payload: Existing extraction helper for non-batch fallback.
            truncate_content: Existing content cap helper.
            ensure_extracted_text: Existing extraction failure guard.
            write_material_document_content: Existing doc/chunk persistence
                helper that also writes marker markdown sidecars.
            safe_upload_filename: Existing filename sanitizer.
            filter_engine: Optional injected filter for deterministic tests.
        """

        for name, value in {
            "persist_upload": persist_upload,
            "load_doc_store": load_doc_store,
            "extract_payload": extract_payload,
            "truncate_content": truncate_content,
            "ensure_extracted_text": ensure_extracted_text,
            "write_material_document_content": write_material_document_content,
            "safe_upload_filename": safe_upload_filename,
        }.items():
            if not callable(value):
                raise TypeError(f"{name} must be callable")
        if update_doc_store is not None and not callable(update_doc_store):
            raise TypeError("update_doc_store must be callable when provided")
        if save_doc_store is not None and not callable(save_doc_store):
            raise TypeError("save_doc_store must be callable when provided")
        if cleanup_uploaded_source is not None and not callable(cleanup_uploaded_source):
            raise TypeError("cleanup_uploaded_source must be callable when provided")
        if (update_doc_store is None) == (save_doc_store is None):
            raise ValueError("exactly one of update_doc_store or save_doc_store is required")

        if update_doc_store is None:
            assert save_doc_store is not None

            def _legacy_update_doc_store(
                project_id: str,
                updater: DocStoreUpdater,
            ) -> DocStore:
                doc_store = load_doc_store(project_id)
                updated = updater(doc_store)
                save_doc_store(project_id, updated)
                return updated

            update_doc_store = _legacy_update_doc_store

        self.persist_upload = persist_upload
        self.load_doc_store = load_doc_store
        self.update_doc_store = update_doc_store
        self.cleanup_uploaded_source = cleanup_uploaded_source
        self.extract_payload = extract_payload
        self.truncate_content = truncate_content
        self.ensure_extracted_text = ensure_extracted_text
        self.write_material_document_content = write_material_document_content
        self.safe_upload_filename = safe_upload_filename
        self.filter_engine = filter_engine or SmartFilterEngine()

    async def process_uploads(
        self,
        project_id: str,
        uploads: Sequence[UploadFile],
        *,
        store: Any,
        goal: str | None = None,
        enable_filter: bool = True,
        max_workers: int | None = None,
    ) -> BatchUploadResult:
        """Persist uploaded files, deduplicate, then process accepted sources.

        Args:
            project_id: Existing project id.
            uploads: Non-empty sequence of FastAPI uploads.
            store: Existing writing resource store.
            goal: Optional user goal that enables smart filtering.
            enable_filter: Whether to run the filter when ``goal`` is non-empty.
            max_workers: Optional Marker batch worker count.

        Returns:
            Legacy-compatible batch upload summary.
        """

        normalized_project_id = self._validate_project_id(project_id)
        if isinstance(uploads, (str, bytes)) or not isinstance(uploads, Sequence):
            raise TypeError("uploads must be a sequence of UploadFile")
        if not uploads:
            raise ValueError("uploads must be non-empty")
        if store is None:
            raise ValueError("store must not be None")

        prepared_sources: list[BatchSource] = []
        immediate_results: list[dict[str, Any]] = []
        duplicate_files = 0
        failed_files = 0
        request_fingerprints: set[str] = set()

        for upload in uploads:
            filename = self.safe_upload_filename(getattr(upload, "filename", "") or "unnamed")
            uploaded_source: UploadedSourceFile | None = None
            try:
                uploaded = await self.persist_upload(normalized_project_id, filename, upload)
                uploaded_source = self._coerce_uploaded_source(uploaded)
                source = uploaded_source
                fingerprint = source.fingerprint.strip().lower()
                if fingerprint in request_fingerprints:
                    if self.cleanup_uploaded_source is not None:
                        self.cleanup_uploaded_source(normalized_project_id, source)
                    duplicate_files += 1
                    immediate_results.append(
                        {
                            "title": filename,
                            "chunks": 0,
                            "content_length": 0,
                            "status": "duplicate",
                            "reason": "duplicate_in_batch",
                        }
                    )
                    continue
                duplicate_result = self._deduplicate_uploaded_source(
                    normalized_project_id,
                    filename,
                    source,
                )
                if duplicate_result is not None:
                    if self.cleanup_uploaded_source is not None:
                        self.cleanup_uploaded_source(normalized_project_id, source)
                    duplicate_files += 1
                    immediate_results.append(duplicate_result)
                    continue
                # Only reserve after the authoritative store check succeeds;
                # a failed check must not poison a later same-content retry.
                request_fingerprints.add(fingerprint)
                prepared_sources.append(
                    BatchSource(
                        source_path=source.path,
                        display_name=filename,
                        source_relative_path=source.path.name,
                        source_fingerprint=source.fingerprint,
                        source_size=source.size,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - per-file failure envelope
                if uploaded_source is not None and self.cleanup_uploaded_source is not None:
                    try:
                        self.cleanup_uploaded_source(normalized_project_id, uploaded_source)
                    except Exception as cleanup_exc:  # noqa: BLE001 - preserve original failure
                        logger.warning(
                            "upload_source_cleanup_failed filename=%s err=%s",
                            filename,
                            cleanup_exc,
                        )
                failed_files += 1
                immediate_results.append(
                    {
                        "title": filename,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        processed = await self.process_sources(
            normalized_project_id,
            prepared_sources,
            store=store,
            goal=goal,
            enable_filter=enable_filter,
            max_workers=max_workers,
            total_files=len(uploads),
            initial_results=immediate_results,
            initial_duplicate_files=duplicate_files,
            initial_failed_files=failed_files,
        )
        return processed

    async def process_sources(
        self,
        project_id: str,
        sources: Sequence[BatchSource],
        *,
        store: Any,
        goal: str | None = None,
        enable_filter: bool = True,
        max_workers: int | None = None,
        total_files: int | None = None,
        initial_results: Sequence[Mapping[str, Any]] | None = None,
        initial_duplicate_files: int = 0,
        initial_failed_files: int = 0,
    ) -> BatchUploadResult:
        """Process local sources from upload or folder-scan entry points."""

        normalized_project_id = self._validate_project_id(project_id)
        normalized_sources = self._validate_sources(sources)
        if store is None:
            raise ValueError("store must not be None")
        if initial_duplicate_files < 0 or initial_failed_files < 0:
            raise ValueError("initial counters must be non-negative")

        results = [dict(item) for item in (initial_results or [])]
        filter_report: SmartFilterReport | None = None
        selected_sources = list(normalized_sources)
        filtered_out: list[BatchSource] = []
        goal_text = str(goal or "").strip()

        if enable_filter and goal_text and selected_sources:
            filter_result = await self.filter_engine.filter_paths(
                [source.source_path for source in selected_sources],
                goal_text,
            )
            filter_report = filter_result.report
            selected_path_set = {path.resolve() for path in filter_result.selected_paths}
            filtered_out = [
                source
                for source in selected_sources
                if source.source_path.resolve() not in selected_path_set
            ]
            selected_sources = [
                source
                for source in selected_sources
                if source.source_path.resolve() in selected_path_set
            ]
            decision_by_path = {
                decision.source_path.resolve(): decision
                for decision in filter_result.report.decisions
            }
            for source in filtered_out:
                decision = decision_by_path.get(source.source_path.resolve())
                results.append(
                    {
                        "title": source.display_name,
                        "status": "skipped",
                        "reason": "filtered_out",
                        "filter_stage": decision.stage if decision else "filter",
                        "keyword_score": (
                            round(decision.keyword_score, 4)
                            if decision is not None
                            else None
                        ),
                        "vector_score": (
                            round(decision.vector_score, 4)
                            if decision is not None and decision.vector_score is not None
                            else None
                        ),
                    }
                )

        payloads = await asyncio.to_thread(
            self._extract_sources_sync,
            selected_sources,
            max_workers,
            normalized_project_id,
        )
        successful_files = 0
        failed_files = initial_failed_files
        total_chunks = 0

        for source in selected_sources:
            parsed = payloads.get(source.source_path)
            if isinstance(parsed, Exception):
                failed_files += 1
                results.append(
                    {
                        "title": source.display_name,
                        "status": "error",
                        "error": str(parsed),
                    }
                )
                continue
            if parsed is None:
                failed_files += 1
                results.append(
                    {
                        "title": source.display_name,
                        "status": "error",
                        "error": "extraction result missing",
                    }
                )
                continue
            try:
                result = self._persist_payload(normalized_project_id, source, parsed, store)
            except Exception as exc:  # noqa: BLE001 - preserve per-file batch behavior
                failed_files += 1
                results.append(
                    {
                        "title": source.display_name,
                        "status": "error",
                        "error": str(exc),
                    }
                )
                continue
            total_chunks += int(result.get("chunks") or 0)
            successful_files += 1
            results.append(result)

        return BatchUploadResult(
            project_id=normalized_project_id,
            total_files=int(total_files if total_files is not None else len(normalized_sources)),
            successful_files=successful_files,
            duplicate_files=initial_duplicate_files,
            queued_files=0,
            failed_files=failed_files,
            total_chunks=total_chunks,
            results=results,
            skipped_files=len(filtered_out),
            filter_report=filter_report,
            processing_mode=self._processing_mode(selected_sources),
            accepted_files=successful_files,
            completed_files=successful_files,
        )

    def _persist_payload(
        self,
        project_id: str,
        source: BatchSource,
        payload: ExtractedDocumentPayload,
        store: Any,
    ) -> dict[str, Any]:
        content = self.truncate_content(payload.content)
        extracted = self.ensure_extracted_text(source.display_name, content)
        summary = self._build_summary(source.source_path, source.display_name, extracted)
        material = store.create_material(
            project_id=project_id,
            title=source.display_name,
            title_en=source.display_name,
            summary=summary,
            summary_en="",
            material_type="reference",
        )
        material_id = str(getattr(material, "material_id", "") or "").strip()
        if not material_id:
            raise ValueError("created material did not return a material_id")

        return self.write_material_document_content(
            project_id,
            material_id,
            source.display_name,
            extracted,
            source_relative_path=source.source_relative_path,
            source_fingerprint=source.source_fingerprint,
            source_size=source.source_size,
            source_mtime=source.source_mtime,
            blocks=payload.blocks,
            markdown_full=payload.markdown_full,
            parser_provenance=payload.parser_provenance,
            parser_output_sha256=payload.parser_output_sha256,
            ocr_report=payload.ocr_report,
        )

    def _extract_payload_with_project_context(
        self,
        filename: str,
        source_path: Path,
        project_id: str | None,
    ) -> ExtractedDocumentPayload:
        """Call the extractor with project context when the injected callable supports it."""

        normalized_project_id = str(project_id or "").strip()
        if normalized_project_id:
            try:
                return self.extract_payload(
                    filename,
                    source_path,
                    project_id=normalized_project_id,
                )
            except TypeError as exc:
                if "project_id" not in str(exc):
                    raise
        return self.extract_payload(filename, source_path)

    def _extract_sources_sync(
        self,
        sources: list[BatchSource],
        max_workers: int | None,
        project_id: str | None = None,
    ) -> dict[Path, ExtractedDocumentPayload | Exception]:
        if not sources:
            return {}

        results: dict[Path, ExtractedDocumentPayload | Exception] = {}
        pdf_sources = [source for source in sources if source.source_path.suffix.lower() == ".pdf"]
        pdf_paths = [source.source_path for source in pdf_sources]

        if pdf_sources:
            batch_results = self._try_parse_pdf_batch(pdf_paths, max_workers)
            if batch_results is not None:
                for source, parsed in zip(pdf_sources, batch_results, strict=True):
                    if isinstance(parsed, Exception):
                        results[source.source_path] = parsed
                    else:
                        if isinstance(parsed, PDFParseResult):
                            text, blocks, markdown_full = parsed.legacy_tuple()
                            parser_provenance = parsed.provenance
                        else:
                            text, blocks, markdown_full = parsed
                            parser_provenance = None
                        if blocks is None and str(project_id or "").strip():
                            try:
                                visual_payload = self._extract_payload_with_project_context(
                                    source.display_name,
                                    source.source_path,
                                    project_id,
                                )
                                blocks = visual_payload.blocks
                                markdown_full = markdown_full or visual_payload.markdown_full
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "pdf_visual_batch_supplement_failed file=%s err=%s",
                                    source.display_name,
                                    exc,
                                )
                        payload = ExtractedDocumentPayload(
                            content=text,
                            blocks=blocks,
                            markdown_full=markdown_full,
                            parser_provenance=parser_provenance,
                            parser_output_sha256=(
                                f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
                            ),
                        )
                        results[source.source_path] = cast(
                            ExtractedDocumentPayload,
                            apply_pdf_ocr_if_needed(
                                source.display_name,
                                source.source_path,
                                payload,
                            ),
                        )

        for source in sources:
            if source.source_path in results:
                continue
            try:
                results[source.source_path] = self._extract_payload_with_project_context(
                    source.display_name,
                    source.source_path,
                    project_id,
                )
            except Exception as exc:  # noqa: BLE001
                results[source.source_path] = exc
        return results

    def _try_parse_pdf_batch(
        self,
        pdf_paths: list[Path],
        max_workers: int | None,
    ) -> list[
        PDFParseResult | tuple[str, list[Any] | None, str | None] | Exception
    ] | None:
        if not pdf_paths:
            return []
        try:
            from pdf_backends import get_pdf_backend

            backend = get_pdf_backend()
            parse_batch = getattr(backend, "parse_batch_with_provenance", None)
            if not callable(parse_batch):
                parse_batch = getattr(backend, "parse_batch", None)
            if not callable(parse_batch):
                return None
            workers = self._resolve_marker_workers(max_workers)
            return list(parse_batch(pdf_paths, max_workers=workers))
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf_batch_parse_unavailable count=%d err=%s", len(pdf_paths), exc)
            return None

    def _deduplicate_uploaded_source(
        self,
        project_id: str,
        filename: str,
        uploaded: UploadedSourceFile,
    ) -> dict[str, Any] | None:
        uploaded_path = getattr(uploaded, "path", None)
        source_relative_path = uploaded_path.name if isinstance(uploaded_path, Path) else filename
        doc_store = self.load_doc_store(project_id)
        for existing_mid, existing_doc in doc_store.items():
            if str(existing_doc.get("source_fingerprint") or "") != uploaded.fingerprint:
                continue
            matched_record: dict[str, Any] | None = None

            def _repair_source(current_store: DocStore) -> DocStore:
                nonlocal matched_record
                current = current_store.get(existing_mid)
                if not isinstance(current, dict):
                    return current_store
                if str(current.get("source_fingerprint") or "") != uploaded.fingerprint:
                    return current_store
                if not str(current.get("source_relative_path") or "").strip():
                    current["source_relative_path"] = source_relative_path
                    current["source_size"] = int(current.get("source_size") or uploaded.size)
                    current_store[existing_mid] = current
                matched_record = dict(current)
                return current_store

            self.update_doc_store(project_id, _repair_source)
            if matched_record is None:
                continue
            return {
                "material_id": existing_mid,
                "title": str(matched_record.get("title") or filename),
                "content_length": len(str(matched_record.get("content") or "")),
                "chunks": 0,
                "status": "duplicate",
            }
        return None

    def _build_summary(self, source_path: Path, filename: str, content: str) -> str:
        try:
            metadata = self.filter_engine.extract_metadata(source_path)
            summary = metadata.abstract.strip()
        except Exception:  # noqa: BLE001 - summary fallback must not block ingest
            summary = ""
        if not summary:
            # 使用智能摘要提取（优先 Abstract 章节）
            try:
                from services.abstract_extractor import extract_abstract
                summary = extract_abstract(content, max_length=500).strip()
            except Exception:  # noqa: BLE001
                summary = content[:500].replace("\n", " ").strip()
        if not summary:
            summary = f"从文件 {filename} 导入"
        return summary[:1000]

    @staticmethod
    def _processing_mode(sources: Sequence[BatchSource]) -> str:
        if any(source.source_path.suffix.lower() == ".pdf" for source in sources):
            return "unified_batch_pdf"
        return "unified_batch"

    @staticmethod
    def _resolve_marker_workers(max_workers: int | None) -> int:
        if max_workers is None:
            raw = os.environ.get("MARKER_BATCH_MAX_WORKERS", "2").strip()
            try:
                parsed = int(raw)
            except ValueError:
                return 2
            return max(1, min(parsed, 4))
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            raise TypeError("max_workers must be an integer")
        return max(1, min(max_workers, 4))

    @staticmethod
    def _validate_project_id(project_id: str) -> str:
        if not isinstance(project_id, str):
            raise TypeError("project_id must be a string")
        normalized = project_id.strip()
        if not normalized:
            raise ValueError("project_id must be non-empty")
        return normalized

    @staticmethod
    def _validate_sources(sources: Sequence[BatchSource]) -> list[BatchSource]:
        if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
            raise TypeError("sources must be a sequence of BatchSource")
        normalized = list(sources)
        for source in normalized:
            if not isinstance(source, BatchSource):
                raise TypeError("sources must contain BatchSource values")
            if not source.source_path.is_file():
                raise ValueError(f"source_path is not a file: {source.source_path}")
            if not source.display_name.strip():
                raise ValueError("display_name must be non-empty")
            if not source.source_relative_path.strip():
                raise ValueError("source_relative_path must be non-empty")
            if not re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                source.source_fingerprint.strip().lower(),
            ):
                raise ValueError("source_fingerprint must use sha256:<64 lowercase hex>")
            if source.source_size < 0:
                raise ValueError("source_size must be non-negative")
        return normalized

    @staticmethod
    def _coerce_uploaded_source(uploaded: Any) -> UploadedSourceFile:
        path = getattr(uploaded, "path", None)
        fingerprint = str(getattr(uploaded, "fingerprint", "") or "").strip()
        size = getattr(uploaded, "size", None)
        if not isinstance(path, Path):
            raise TypeError("persist_upload returned an invalid path")
        if not path.is_file():
            raise ValueError(f"persisted upload path is not a file: {path}")
        if not fingerprint:
            raise ValueError("persist_upload returned an empty fingerprint")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("persist_upload returned an invalid size")
        return uploaded
