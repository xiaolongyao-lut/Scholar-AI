# -*- coding: utf-8 -*-
"""Export API Router — TipTap content → formatted DOCX."""

from __future__ import annotations

import tempfile
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

router = APIRouter(prefix="/api/export", tags=["Export"])


def _safe_docx_filename_stem(value: str, fallback: str = "export") -> str:
    """Return a bounded filename stem for generated DOCX downloads.

    Args:
        value: User-facing title text, not a filesystem path.
        fallback: ASCII stem used when the title has no safe characters.

    Returns:
        A Windows-safe filename stem without path separators or control chars.
    """
    normalized = re.sub(r"\s+", " ", str(value or "").strip())
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized).strip(" ._")
    if not safe:
        safe = fallback
    return safe[:96]


def _cleanup_export_tmp_dir(tmp_dir: Path) -> None:
    """Remove a generated DOCX temp directory after the response is sent.

    Args:
        tmp_dir: Directory returned by ``tempfile.mkdtemp(prefix="export_docx_")``.

    Returns:
        None. Paths outside the expected temp root are left untouched.
    """

    if not isinstance(tmp_dir, Path):
        raise TypeError("tmp_dir must be a pathlib.Path")

    resolved = tmp_dir.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if resolved.parent != temp_root or not resolved.name.startswith("export_docx_"):
        return
    if resolved.is_dir():
        shutil.rmtree(resolved)


class ExportDocxRequest(BaseModel):
    html: str = Field(..., min_length=1, max_length=500000)
    json_content: dict | None = Field(None, alias="json")
    title: str = Field("Untitled", max_length=200)
    style_profile: str | None = None


def _html_to_docx(html: str, title: str, output_path: Path, style_profile: str | None = None) -> Path:
    """Convert TipTap HTML to DOCX using existing WordWriter infrastructure."""
    try:
        from docx import Document
        from docx.shared import Pt, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
    except ImportError:
        raise HTTPException(status_code=501, detail="python-docx not installed")

    doc = Document()

    # Page setup — reuse WordWriter conventions
    sec = doc.sections[0]
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)

    # CJK/Latin dual font — reuse WordWriter pattern
    styles = doc.styles
    normal_font = styles["Normal"].font
    normal_font.name = "Times New Roman"
    normal_font.size = Pt(10.5)
    styles["Normal"]._element.rPr.get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")

    # Title
    title_para = doc.add_paragraph(title, style="Title")
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title_para.runs:
        run.font.name = "Times New Roman"
        run._element.rPr.get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")
        run.font.size = Pt(18)

    # Parse HTML into paragraphs using html.parser
    from html.parser import HTMLParser

    class _TipTapParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.paragraphs: list[dict] = []
            self._current: list[dict] = []
            self._in_heading: int | None = None
            self._in_list: bool = False
            self._in_strong: bool = False
            self._in_em: bool = False
            self._in_u: bool = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
            if tag in ("h1", "h2", "h3", "h4"):
                self._in_heading = int(tag[1])
                self._flush()
            elif tag in ("p", "div", "blockquote"):
                self._flush()
            elif tag == "strong" or tag == "b":
                self._in_strong = True
            elif tag == "em" or tag == "i":
                self._in_em = True
            elif tag == "u":
                self._in_u = True
            elif tag == "ul" or tag == "ol":
                self._in_list = True
            elif tag == "li":
                self._flush()

        def handle_endtag(self, tag: str):
            if tag in ("h1", "h2", "h3", "h4"):
                self._in_heading = None
            elif tag in ("p", "div", "blockquote"):
                pass
            elif tag == "strong" or tag == "b":
                self._in_strong = False
            elif tag == "em" or tag == "i":
                self._in_em = False
            elif tag == "u":
                self._in_u = False
            elif tag == "ul" or tag == "ol":
                self._in_list = False

        def handle_data(self, data: str):
            text = data.strip()
            if not text:
                return
            run_info: dict[str, Any] = {"text": text}
            if self._in_strong:
                run_info["bold"] = True
            if self._in_em:
                run_info["italic"] = True
            if self._in_u:
                run_info["underline"] = True
            self._current.append(run_info)

        def _flush(self):
            if self._current:
                self.paragraphs.append({
                    "runs": self._current,
                    "heading": self._in_heading,
                    "list": self._in_list,
                })
                self._current = []

        def close(self):
            self._flush()
            super().close()

    parser = _TipTapParser()
    parser.feed(html)
    parser.close()

    heading_styles = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}
    for para_info in parser.paragraphs:
        heading = para_info["heading"]
        style = heading_styles.get(heading, "Normal") if heading else "Normal"
        p = doc.add_paragraph(style=style)
        if not heading and para_info.get("list"):
            p.style = styles["List Bullet"]
        for run_info in para_info["runs"]:
            run = p.add_run(run_info["text"])
            run.font.name = "Times New Roman"
            run._element.rPr.get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
            if heading:
                run._element.rPr.get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")
            if run_info.get("bold"):
                run.bold = True
            if run_info.get("italic"):
                run.italic = True
            if run_info.get("underline"):
                run.underline = True

    doc.save(str(output_path))
    return output_path


@router.post("/docx")
async def export_docx(req: ExportDocxRequest):
    """Export TipTap content as formatted DOCX."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="export_docx_"))
    filename = f"{_safe_docx_filename_stem(req.title)}_{uuid.uuid4().hex[:8]}.docx"
    output_path = tmp_dir / filename

    try:
        _html_to_docx(req.html, req.title, output_path, req.style_profile)
    except Exception as e:
        _cleanup_export_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(
        path=str(output_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(_cleanup_export_tmp_dir, tmp_dir),
    )
