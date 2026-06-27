# -*- coding: utf-8 -*-
"""Unified batch ingestion service for uploads and source-folder scans."""

from __future__ import annotations

import asyncio
import logging
import os
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
    from pdf_backends.ocr_ingestion import apply_pdf_ocr_if_needed
except ImportError:  # pragma: no cover - package import fallback
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


PersistUploadFn = Callable[[str, str, UploadFile], Any]
LoadDocStoreFn = Callable[[str], dict[str, dict[str, Any]]]
SaveDocStoreFn = Callable[[str, dict[str, dict[str, Any]]], None]
ExtractPayloadFn = Callable[[str, Path], ExtractedDocumentPayload]
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

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result to the route's JSON response shape."""

        payload: dict[str, Any] = {
            "project_id": self.project_id,
            "total_files": self.total_files,
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
        save_doc_store: SaveDocStoreFn,
        extract_payload: ExtractPayloadFn,
        truncate_content: TruncateContentFn,
        ensure_extracted_text: EnsureExtractedTextFn,
        write_material_document_content: WriteMaterialFn,
        safe_upload_filename: SafeFilenameFn,
        filter_engine: SmartFilterEngine | None = None,
    ) -> None:
        """Wire the service to existing router persistence helpers.

        Args:
            persist_upload: Existing streaming upload-to-source-file helper.
            load_doc_store: Existing project doc-store reader.
            save_doc_store: Existing project doc-store writer.
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
            "save_doc_store": save_doc_store,
            "extract_payload": extract_payload,
            "truncate_content": truncate_content,
            "ensure_extracted_text": ensure_extracted_text,
            "write_material_document_content": write_material_document_content,
            "safe_upload_filename": safe_upload_filename,
        }.items():
            if not callable(value):
                raise TypeError(f"{name} must be callable")

        self.persist_upload = persist_upload
        self.load_doc_store = load_doc_store
        self.save_doc_store = save_doc_store
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

        for upload in uploads:
            filename = self.safe_upload_filename(getattr(upload, "filename", "") or "unnamed")
            try:
                uploaded = await self.persist_upload(normalized_project_id, filename, upload)
                source = self._coerce_uploaded_source(uploaded)
                duplicate_result = self._deduplicate_uploaded_source(
                    normalized_project_id,
                    filename,
                    source,
                )
                if duplicate_result is not None:
                    duplicate_files += 1
                    immediate_results.append(duplicate_result)
                    continue
                prepared_sources.append(
                    BatchSource(
                        source_path=source.path,
                        display_name=filename,
                        source_relative_path=filename,
                        source_fingerprint=source.fingerprint,
                        source_size=source.size,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - per-file failure envelope
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
        )

    def _extract_sources_sync(
        self,
        sources: list[BatchSource],
        max_workers: int | None,
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
                        text, blocks, markdown_full = parsed
                        payload = ExtractedDocumentPayload(
                            content=text,
                            blocks=blocks,
                            markdown_full=markdown_full,
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
                results[source.source_path] = self.extract_payload(
                    source.display_name,
                    source.source_path,
                )
            except Exception as exc:  # noqa: BLE001
                results[source.source_path] = exc
        return results

    def _try_parse_pdf_batch(
        self,
        pdf_paths: list[Path],
        max_workers: int | None,
    ) -> list[tuple[str, list[Any] | None, str | None] | Exception] | None:
        if not pdf_paths:
            return []
        try:
            from pdf_backends import get_pdf_backend

            backend = get_pdf_backend()
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
        doc_store = self.load_doc_store(project_id)
        for existing_mid, existing_doc in doc_store.items():
            if str(existing_doc.get("source_fingerprint") or "") != uploaded.fingerprint:
                continue
            if not str(existing_doc.get("source_relative_path") or "").strip():
                existing_doc["source_relative_path"] = filename
                existing_doc["source_size"] = int(existing_doc.get("source_size") or uploaded.size)
                doc_store[existing_mid] = existing_doc
                self.save_doc_store(project_id, doc_store)
            return {
                "material_id": existing_mid,
                "title": str(existing_doc.get("title") or filename),
                "content_length": len(str(existing_doc.get("content") or "")),
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
            if not source.source_fingerprint.strip():
                raise ValueError("source_fingerprint must be non-empty")
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
