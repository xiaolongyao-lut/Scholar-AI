"""Disabled-by-default experimental MCP tools."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..audit import AuditLog
from ..python_sandbox import PythonSandbox
from ..redaction import SecretRedactor
from ..result import safe_result
from ..workflow_runtime.workspace import ArtifactWorkspace

MAX_OCR_PAGES: int = 10
DEFAULT_OCR_PAGES: int = 3
MAX_TRANSLATION_CONTEXT_CHARS: int = 24_000


class ExperimentalRuntime(Protocol):
    """Runtime tool subset used by experimental wrappers."""

    def list_materials(self, project_id: str) -> dict[str, Any]:
        """List materials for a project."""

    def search_literature(self, project_id: str, query: str, top_k: int = 10) -> dict[str, Any]:
        """Search project literature."""

    def get_material_file_base64(self, material_id: str) -> dict[str, Any]:
        """Read a small material source file through the backend."""

    def list_figure_table_candidates(
        self,
        project_id: str,
        limit: int = 20,
        pixel_only: bool = False,
        render_pdf_fallback: bool = True,
    ) -> dict[str, Any]:
        """List visual figure/table candidates through the backend."""

    def chat_ask(
        self,
        query: str,
        context: list[str] | None = None,
        project_id: str | None = None,
        ai_cost_profile: str = "aggressive",
    ) -> dict[str, Any]:
        """Call backend-managed chat generation."""


class ExperimentalTools:
    """High-risk local tools with a hard explicit-enable boundary."""

    def __init__(
        self,
        repo_root: Path,
        runtime: ExperimentalRuntime,
        audit: AuditLog | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Create experimental tools.

        Args:
            repo_root: Repository root used only for artifact workspace anchoring.
            runtime: HTTP-first runtime tools. Secrets stay behind the backend.
            audit: Optional audit log.
            enabled: Explicit test/runtime override. When None, reads
                ``LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS``.
        """
        if not isinstance(repo_root, Path):
            raise TypeError("repo_root must be a Path")
        self.workspace = ArtifactWorkspace(repo_root=repo_root)
        self.runtime = runtime
        self.audit = audit
        self.enabled = self._env_enabled() if enabled is None else bool(enabled)
        self.python_sandbox = PythonSandbox(python_executable=Path(sys.executable), timeout_sec=5)

    def ocr_material(
        self,
        material_id: str,
        pages: list[int] | None = None,
        ocr_language: str = "eng",
    ) -> dict[str, Any]:
        """Render and OCR a small material through backend-served file bytes."""

        started = time.perf_counter()
        args = {"material_id": material_id, "pages": pages or [], "ocr_language": ocr_language}
        if not self._require_enabled("literature.ocr_material", args, started):
            return self._disabled("literature.ocr_material", args, started)
        try:
            material_id = self._require_non_empty(material_id, "material_id")
            selected_pages = self._normalize_pages(pages)
            language = self._require_non_empty(ocr_language, "ocr_language")
            file_result = self.runtime.get_material_file_base64(material_id)
            if file_result.get("is_error") is True:
                return self._finish("literature.ocr_material", args, file_result, started, "experimental_runtime")
            file_data = file_result.get("data")
            if not isinstance(file_data, dict):
                return self._finish(
                    "literature.ocr_material",
                    args,
                    safe_result(None, error=True, error_code="ocr_invalid_file_payload", message="Backend file payload is invalid."),
                    started,
                    "experimental_runtime",
                )
            payload = self._ocr_file_payload(material_id, file_data, selected_pages, language)
            path = f"experimental/ocr-{self._slug(material_id)}-{int(time.time() * 1000)}.json"
            result = safe_result(self.workspace.write_json(path, self._redacted_json(payload), overwrite=True))
            result["data"]["summary"] = {
                "page_count": len(payload.get("pages", [])),
                "ocr_available": payload.get("ocr_available"),
                "artifact": result["data"]["path"],
            }
            return self._finish("literature.ocr_material", args, result, started, "experimental_artifact_write")
        except Exception as exc:
            return self._finish(
                "literature.ocr_material",
                args,
                safe_result(None, error=True, error_code="ocr_tool_failed", message=str(exc)),
                started,
                "experimental_error",
            )

    def prepare_visual_review(
        self,
        project_id: str,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Prepare a redacted retrieval snapshot for external visual review."""

        started = time.perf_counter()
        args = {"project_id": project_id, "query": query[:200], "top_k": top_k}
        if not self._require_enabled("literature.prepare_visual_review", args, started):
            return self._disabled("literature.prepare_visual_review", args, started)
        try:
            project_id = self._require_non_empty(project_id, "project_id")
            query = self._require_non_empty(query, "query")
            top_k = self._bounded_int(top_k, "top_k", 1, 20)
            search_result = self.runtime.search_literature(project_id, query, top_k=top_k)
            if search_result.get("is_error") is True:
                return self._finish("literature.prepare_visual_review", args, search_result, started, "experimental_runtime")
            candidates_result = self.runtime.list_figure_table_candidates(
                project_id,
                limit=max(top_k, 10),
                pixel_only=False,
                render_pdf_fallback=True,
            )
            payload = {
                "kind": "visual_review_pack",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "query": SecretRedactor.scan(query),
                "search": search_result.get("data"),
                "figure_table_candidates": None if candidates_result.get("is_error") else candidates_result.get("data"),
                "candidate_error": candidates_result.get("error_code") if candidates_result.get("is_error") else None,
            }
            path = f"experimental/visual-review-{self._slug(project_id)}-{int(time.time() * 1000)}.json"
            result = safe_result(self.workspace.write_json(path, self._redacted_json(payload), overwrite=True))
            return self._finish("literature.prepare_visual_review", args, result, started, "experimental_artifact_write")
        except Exception as exc:
            return self._finish(
                "literature.prepare_visual_review",
                args,
                safe_result(None, error=True, error_code="visual_review_failed", message=str(exc)),
                started,
                "experimental_error",
            )

    def translate_pack(
        self,
        project_id: str,
        target_language: str,
        query: str | None = None,
        top_k: int = 8,
        use_model: bool = True,
    ) -> dict[str, Any]:
        """Generate a bounded translation pack through backend-managed chat."""

        started = time.perf_counter()
        args = {
            "project_id": project_id,
            "target_language": target_language,
            "query": query or "",
            "top_k": top_k,
            "use_model": use_model,
        }
        if not self._require_enabled("literature.translate_pack", args, started):
            return self._disabled("literature.translate_pack", args, started)
        try:
            project_id = self._require_non_empty(project_id, "project_id")
            target_language = self._require_non_empty(target_language, "target_language")
            top_k = self._bounded_int(top_k, "top_k", 1, 20)
            source_pack = self._build_translation_source_pack(project_id, query, top_k)
            prompt = self._translation_prompt(target_language, source_pack)
            translated_markdown = self._render_translation_source_markdown(target_language, source_pack)
            model_data: dict[str, Any] | None = None
            if use_model:
                chat_result = self.runtime.chat_ask(
                    query=prompt,
                    context=source_pack["context"],
                    project_id=project_id,
                    ai_cost_profile="aggressive",
                )
                if chat_result.get("is_error") is True:
                    return self._finish("literature.translate_pack", args, chat_result, started, "experimental_runtime")
                model_data = chat_result.get("data") if isinstance(chat_result.get("data"), dict) else None
                answer = model_data.get("answer") if isinstance(model_data, dict) else None
                if isinstance(answer, str) and answer.strip():
                    translated_markdown = answer.strip()
            artifact_payload = {
                "kind": "translation_pack",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "target_language": target_language,
                "query": query or "",
                "use_model": use_model,
                "source_pack": source_pack,
                "model": model_data.get("model") if isinstance(model_data, dict) else None,
                "translation_markdown": translated_markdown,
            }
            base_path = f"experimental/translation-{self._slug(project_id)}-{int(time.time() * 1000)}"
            json_result = self.workspace.write_json(f"{base_path}.json", self._redacted_json(artifact_payload), overwrite=True)
            markdown_result = self.workspace.write_text(
                f"{base_path}.md",
                translated_markdown,
                overwrite=True,
            )
            result = safe_result({"json": json_result, "markdown": markdown_result, "model": artifact_payload["model"]})
            return self._finish("literature.translate_pack", args, result, started, "experimental_artifact_write")
        except Exception as exc:
            return self._finish(
                "literature.translate_pack",
                args,
                safe_result(None, error=True, error_code="translate_pack_failed", message=str(exc)),
                started,
                "experimental_error",
            )

    def export_project_pack(
        self,
        project_id: str,
        include_search_preview: bool = False,
        query: str = "",
    ) -> dict[str, Any]:
        """Write a redacted local project metadata pack artifact."""

        started = time.perf_counter()
        args = {
            "project_id": project_id,
            "include_search_preview": include_search_preview,
            "query": query[:200],
        }
        if not self._require_enabled("literature.export_project_pack", args, started):
            return self._disabled("literature.export_project_pack", args, started)
        project_id = self._require_non_empty(project_id, "project_id")
        materials = self.runtime.list_materials(project_id)
        if materials.get("is_error") is True:
            return self._finish("literature.export_project_pack", args, materials, started, "experimental_runtime")
        payload: dict[str, Any] = {
            "kind": "project_pack",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "materials": materials.get("data"),
        }
        if include_search_preview and query.strip():
            preview = self.runtime.search_literature(project_id, query.strip(), top_k=5).get("data")
            if isinstance(preview, dict) and "query" in preview:
                preview = {**preview, "query": "<redacted-query>"}
            payload["search_preview"] = preview
        path = f"experimental/project-pack-{self._slug(project_id)}-{int(time.time())}.json"
        result = safe_result(self.workspace.write_json(path, self._redacted_json(payload), overwrite=True))
        return self._finish("literature.export_project_pack", args, result, started, "experimental_artifact_write")

    def run_python_sandbox(self, script: dict[str, Any]) -> dict[str, Any]:
        """Run bounded pure-Python code in a short-lived child process."""

        started = time.perf_counter()
        args = {"script_keys": sorted(script.keys()) if isinstance(script, dict) else []}
        if not self._require_enabled("workflow.run_python_sandbox", args, started):
            return self._disabled("workflow.run_python_sandbox", args, started)
        try:
            if not isinstance(script, dict):
                raise ValueError("script must be an object")
            code = script.get("code")
            if not isinstance(code, str):
                raise ValueError("script.code must be a string")
            input_data = script.get("input_data", {})
            if not isinstance(input_data, dict):
                raise ValueError("script.input_data must be an object")
            timeout_raw = script.get("timeout_sec", 5)
            if not isinstance(timeout_raw, int):
                raise ValueError("script.timeout_sec must be an integer")
            sandbox_payload = self.python_sandbox.run(code=code, input_data=input_data, timeout_sec=timeout_raw)
            path = f"experimental/python-sandbox-{int(time.time() * 1000)}.json"
            artifact = self.workspace.write_json(path, self._redacted_json({"kind": "python_sandbox_run", **sandbox_payload}), overwrite=True)
            result = safe_result({"run": sandbox_payload, "artifact": artifact})
            if not sandbox_payload.get("ok"):
                result["is_error"] = True
                result["error_code"] = sandbox_payload.get("error_code") or "python_sandbox_failed"
                result["message"] = sandbox_payload.get("message")
            return self._finish("workflow.run_python_sandbox", args, result, started, "experimental_sandbox")
        except Exception as exc:
            return self._finish(
                "workflow.run_python_sandbox",
                args,
                safe_result(None, error=True, error_code="python_sandbox_failed", message=str(exc)),
                started,
                "experimental_error",
            )

    def _disabled(self, tool_name: str, args: dict[str, Any], started: float) -> dict[str, Any]:
        result = safe_result(
            {"enable_env": "LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1"},
            error=True,
            error_code="experimental_tools_disabled",
            message="Experimental tools are disabled by default.",
        )
        return self._finish(tool_name, args, result, started, "experimental_disabled")

    def _require_enabled(self, tool_name: str, args: dict[str, Any], started: float) -> bool:
        del tool_name, args, started
        return self.enabled

    def _finish(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        started: float,
        reason: str,
    ) -> dict[str, Any]:
        if self.audit is not None:
            self.audit.log(
                tool_name=tool_name,
                args_summary=args,
                touched_paths=[],
                allow_block_reason=reason,
                result_preview=str(result.get("data")),
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=result.get("error_code"),
            )
        return result

    def _redacted_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        loaded = json.loads(SecretRedactor.scan(text))
        if not isinstance(loaded, dict):
            raise ValueError("redacted payload must remain an object")
        return loaded

    def _ocr_file_payload(
        self,
        material_id: str,
        file_data: dict[str, Any],
        selected_pages: list[int],
        ocr_language: str,
    ) -> dict[str, Any]:
        data_b64 = file_data.get("data")
        mime = str(file_data.get("mime") or "")
        filename = str(file_data.get("name") or material_id)
        if not isinstance(data_b64, str) or not data_b64:
            raise ValueError("backend file payload is missing data")
        raw = base64.b64decode(data_b64, validate=True)
        if mime == "application/pdf" or filename.lower().endswith(".pdf"):
            return self._ocr_pdf_bytes(material_id, filename, raw, selected_pages, ocr_language)
        if mime.startswith("text/") or filename.lower().endswith((".txt", ".md")):
            text = raw.decode("utf-8", errors="replace")
            artifact = self.workspace.write_text(
                f"experimental/ocr-{self._slug(material_id)}-source.md",
                text,
                overwrite=True,
            )
            return {
                "kind": "ocr_material",
                "material_id": material_id,
                "filename": filename,
                "mime": mime,
                "ocr_available": False,
                "pages": [{"page": None, "text": SecretRedactor.scan(text), "text_source": "plain_text"}],
                "artifacts": [artifact],
            }
        if mime.startswith("image/") or filename.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")):
            return self._ocr_image_bytes(material_id, filename, raw, ocr_language)
        raise ValueError(f"unsupported OCR material type: {mime or filename}")

    def _ocr_pdf_bytes(
        self,
        material_id: str,
        filename: str,
        raw: bytes,
        selected_pages: list[int],
        ocr_language: str,
    ) -> dict[str, Any]:
        try:
            import pymupdf
        except ImportError as exc:
            raise ValueError("pymupdf is required for PDF OCR preparation") from exc
        try:
            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image

            ocr_available = True
        except ImportError:
            pytesseract = None
            Image = None
            ocr_available = False
        pages: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        with pymupdf.open(stream=raw, filetype="pdf") as doc:
            page_count = len(doc)
            if not selected_pages:
                selected_pages = list(range(1, min(DEFAULT_OCR_PAGES, page_count) + 1))
            for page_number in selected_pages:
                if page_number < 1 or page_number > page_count:
                    raise ValueError(f"page {page_number} is outside document page range 1..{page_count}")
                page = doc[page_number - 1]
                extracted_text = SecretRedactor.scan(page.get_text("text") or "")
                pixmap = page.get_pixmap(dpi=160, alpha=False)
                png_bytes = pixmap.tobytes("png")
                image_artifact = self.workspace.write_bytes(
                    f"experimental/ocr-images/{self._slug(material_id)}-p{page_number}.png",
                    png_bytes,
                    overwrite=True,
                )
                artifacts.append(image_artifact)
                ocr_text = ""
                ocr_error = None
                if ocr_available and pytesseract is not None and Image is not None:
                    try:
                        with Image.open(io.BytesIO(png_bytes)) as image:
                            ocr_text = SecretRedactor.scan(
                                pytesseract.image_to_string(image, lang=ocr_language, timeout=15)
                            )
                    except Exception as exc:  # pragma: no cover - depends on local tesseract binary
                        ocr_error = f"{type(exc).__name__}: {exc}"
                pages.append(
                    {
                        "page": page_number,
                        "image_artifact": image_artifact["path"],
                        "extracted_text": extracted_text,
                        "ocr_text": ocr_text,
                        "ocr_error": SecretRedactor.scan(ocr_error) if ocr_error else None,
                    }
                )
        return {
            "kind": "ocr_material",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "material_id": material_id,
            "filename": filename,
            "mime": "application/pdf",
            "ocr_available": ocr_available,
            "ocr_language": ocr_language,
            "pages": pages,
            "artifacts": artifacts,
        }

    def _ocr_image_bytes(
        self,
        material_id: str,
        filename: str,
        raw: bytes,
        ocr_language: str,
    ) -> dict[str, Any]:
        image_artifact = self.workspace.write_bytes(
            f"experimental/ocr-images/{self._slug(material_id)}-{self._slug(filename)}",
            raw,
            overwrite=True,
        )
        try:
            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image
        except ImportError:
            return {
                "kind": "ocr_material",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "material_id": material_id,
                "filename": filename,
                "ocr_available": False,
                "pages": [{"page": None, "image_artifact": image_artifact["path"], "ocr_text": ""}],
                "artifacts": [image_artifact],
            }
        with Image.open(io.BytesIO(raw)) as image:
            text = SecretRedactor.scan(pytesseract.image_to_string(image, lang=ocr_language, timeout=15))
        return {
            "kind": "ocr_material",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "material_id": material_id,
            "filename": filename,
            "ocr_available": True,
            "ocr_language": ocr_language,
            "pages": [{"page": None, "image_artifact": image_artifact["path"], "ocr_text": text}],
            "artifacts": [image_artifact],
        }

    def _normalize_pages(self, pages: list[int] | None) -> list[int]:
        if pages is None:
            return []
        if not isinstance(pages, list):
            raise ValueError("pages must be a list of 1-based integers")
        normalized: list[int] = []
        for page in pages:
            if not isinstance(page, int):
                raise ValueError("pages must contain integers")
            if page < 1:
                raise ValueError("pages must be 1-based positive integers")
            if page not in normalized:
                normalized.append(page)
        if len(normalized) > MAX_OCR_PAGES:
            raise ValueError(f"at most {MAX_OCR_PAGES} pages may be processed")
        return normalized

    def _build_translation_source_pack(self, project_id: str, query: str | None, top_k: int) -> dict[str, Any]:
        context: list[str] = []
        sources: list[dict[str, Any]] = []
        if query and query.strip():
            search_result = self.runtime.search_literature(project_id, query.strip(), top_k=top_k)
            if search_result.get("is_error") is True:
                raise RuntimeError(search_result.get("message") or search_result.get("error_code") or "search failed")
            data = search_result.get("data")
            results = data.get("results", []) if isinstance(data, dict) else []
            if isinstance(results, list):
                for item in results[:top_k]:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("content") or item.get("text") or item.get("excerpt") or "")
                    title = str(item.get("title") or item.get("material_title") or item.get("material_id") or "source")
                    snippet = f"[{title}]\n{text}".strip()
                    if snippet:
                        context.append(snippet[:3000])
                    sources.append({key: item.get(key) for key in ("material_id", "chunk_id", "title", "score") if key in item})
        else:
            materials = self.runtime.list_materials(project_id)
            if materials.get("is_error") is True:
                raise RuntimeError(materials.get("message") or materials.get("error_code") or "list materials failed")
            data = materials.get("data")
            if isinstance(data, list):
                for item in data[:top_k]:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or item.get("material_id") or "material")
                    summary = str(item.get("summary") or item.get("summary_en") or "")
                    context.append(f"[{title}]\n{summary}".strip()[:3000])
                    sources.append({key: item.get(key) for key in ("material_id", "title", "type") if key in item})
        bounded_context: list[str] = []
        total = 0
        for item in context:
            if total >= MAX_TRANSLATION_CONTEXT_CHARS:
                break
            remaining = MAX_TRANSLATION_CONTEXT_CHARS - total
            clipped = item[:remaining]
            bounded_context.append(clipped)
            total += len(clipped)
        return {
            "project_id": project_id,
            "query": query or "",
            "context": bounded_context,
            "sources": sources,
        }

    def _translation_prompt(self, target_language: str, source_pack: dict[str, Any]) -> str:
        query = source_pack.get("query") or "the selected literature pack"
        return (
            f"Translate the supplied literature evidence into {target_language}. "
            "Keep academic terminology, preserve source markers when possible, "
            "and return concise Markdown only.\n\n"
            f"Task/query: {query}"
        )

    def _render_translation_source_markdown(self, target_language: str, source_pack: dict[str, Any]) -> str:
        lines = [
            f"# Translation Pack ({target_language})",
            "",
            f"Project: {source_pack.get('project_id')}",
            f"Query: {source_pack.get('query') or '(materials summary)'}",
            "",
            "## Source Context",
            "",
        ]
        for index, item in enumerate(source_pack.get("context", []), start=1):
            lines.append(f"### Source {index}")
            lines.append(str(item))
            lines.append("")
        return SecretRedactor.scan("\n".join(lines).strip() + "\n")

    def _require_non_empty(self, value: str, name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} must be non-empty")
        return cleaned

    def _bounded_int(self, value: int, name: str, minimum: int, maximum: int) -> int:
        if not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value

    def _slug(self, value: str) -> str:
        cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip("-")[:80] or "project"

    def _env_enabled(self) -> bool:
        value = os.environ.get("LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS", "")
        return value.strip().lower() in {"1", "true", "yes", "on"}


def create_default_experimental_tools(
    repo_root: Path,
    runtime: ExperimentalRuntime,
    audit_root: Path | None = None,
) -> ExperimentalTools:
    """Create experimental tools with environment-gated execution."""

    audit = AuditLog(audit_root) if audit_root is not None else None
    return ExperimentalTools(repo_root=repo_root, runtime=runtime, audit=audit)
