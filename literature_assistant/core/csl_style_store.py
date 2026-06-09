"""CSL citation-style registry.

Owns the citation styles available to the manuscript citation system:

- Builtin styles bundled as read-only ``.csl`` assets. GB/T 7714-2015 numeric is
  the default baseline; the author-date variant is also bundled.
- User-uploaded ``.csl`` styles, persisted as raw XML.
- The currently active style id.

Persistence is a single JSON document under ``runtime_state/`` written
atomically (tempfile + ``os.replace``) and guarded by a process lock, matching
the other runtime stores. Builtin style XML is never copied into the store; it
is read from the bundled assets on demand so a bundled-file upgrade takes effect
without a data migration.

Input boundary: uploaded ``.csl`` content is untrusted. It is size-capped and
parsed with the stdlib XML parser; only well-formed CSL 1.0 ``<style>``
documents with a non-empty title are accepted.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from _atomic_io import CrossProcessFileLock
from project_paths import runtime_state_path

CSL_NAMESPACE = "http://purl.org/net/xbiblio/csl"
_STYLE_TAG = f"{{{CSL_NAMESPACE}}}style"
_INFO_TAG = f"{{{CSL_NAMESPACE}}}info"
_TITLE_TAG = f"{{{CSL_NAMESPACE}}}title"

# Cap untrusted upload size. The user uploads their own style on a local
# single-user app, so this is primarily a guard against accidental huge files.
_MAX_CSL_BYTES = 5 * 1024 * 1024

_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "csl"


@dataclass(frozen=True)
class BuiltinStyle:
    id: str
    title: str
    filename: str


_BUILTIN_STYLES: tuple[BuiltinStyle, ...] = (
    BuiltinStyle(
        id="gb-t-7714-2015-numeric",
        title="GB/T 7714—2015（顺序编码制）",
        filename="china-national-standard-gb-t-7714-2015-numeric.csl",
    ),
)

DEFAULT_STYLE_ID = "gb-t-7714-2015-numeric"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class CslValidationError(ValueError):
    """Raised when an uploaded ``.csl`` payload is not a valid CSL 1.0 style."""


def validate_csl(csl_xml: str) -> str:
    """Validate untrusted CSL XML and return its declared title.

    Boundary check for uploaded content: enforces a size cap, well-formedness, a
    CSL ``<style>`` root, and a non-empty ``info/title``. Raises
    ``CslValidationError`` (a ``ValueError``) on any failure.
    """
    if not isinstance(csl_xml, str) or not csl_xml.strip():
        raise CslValidationError("CSL 内容为空")
    if len(csl_xml.encode("utf-8")) > _MAX_CSL_BYTES:
        raise CslValidationError("CSL 文件过大（超过 5MB）")
    try:
        root = ET.fromstring(csl_xml)
    except ET.ParseError as exc:
        raise CslValidationError(f"CSL XML 解析失败：{exc}") from exc
    if root.tag != _STYLE_TAG:
        raise CslValidationError("根元素不是 CSL <style>（命名空间需为 CSL 1.0）")
    info = root.find(_INFO_TAG)
    title_el = info.find(_TITLE_TAG) if info is not None else None
    title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
    if not title:
        raise CslValidationError("CSL 缺少 <info><title>")
    return title


class CslStyleStore:
    """Registry of builtin + user-uploaded CSL styles with an active selection."""

    __slots__ = ("_path", "_lock", "_builtin_cache")

    def __init__(self) -> None:
        self._path: Path = runtime_state_path("csl_styles.json")
        self._lock = threading.Lock()
        self._builtin_cache: dict[str, str] = {}

    @property
    def _file_lock_path(self) -> Path:
        return self._path.with_suffix(f"{self._path.suffix}.lock")

    # --- builtin assets -------------------------------------------------
    def _builtin_xml(self, style: BuiltinStyle) -> str:
        cached = self._builtin_cache.get(style.id)
        if cached is not None:
            return cached
        text = (_ASSETS_DIR / style.filename).read_text(encoding="utf-8")
        self._builtin_cache[style.id] = text
        return text

    @staticmethod
    def _builtin_by_id(style_id: str) -> BuiltinStyle | None:
        for style in _BUILTIN_STYLES:
            if style.id == style_id:
                return style
        return None

    # --- persistence ----------------------------------------------------
    def _read_raw(self) -> dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_raw(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix="csl_styles_", suffix=".json.tmp", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _uploaded(raw: dict[str, Any]) -> list[dict[str, Any]]:
        items = raw.get("uploaded")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict) and str(item.get("id") or "").strip()]

    def _resolve_active_id(self, raw: dict[str, Any], uploaded: list[dict[str, Any]]) -> str:
        active = str(raw.get("active_style_id") or "").strip()
        valid = {style.id for style in _BUILTIN_STYLES} | {str(item["id"]) for item in uploaded}
        return active if active in valid else DEFAULT_STYLE_ID

    # --- public API -----------------------------------------------------
    def list_styles(self) -> list[dict[str, Any]]:
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            uploaded = self._uploaded(raw)
            active_id = self._resolve_active_id(raw, uploaded)
        styles: list[dict[str, Any]] = [
            {
                "id": style.id,
                "title": style.title,
                "source": "builtin",
                "active": style.id == active_id,
                "can_delete": False,
                "created_at": None,
            }
            for style in _BUILTIN_STYLES
        ]
        for item in uploaded:
            item_id = str(item["id"])
            styles.append(
                {
                    "id": item_id,
                    "title": str(item.get("title") or item_id),
                    "source": "uploaded",
                    "active": item_id == active_id,
                    "can_delete": True,
                    "created_at": item.get("created_at"),
                }
            )
        return styles

    def get_style_xml(self, style_id: str) -> str | None:
        sid = str(style_id or "").strip()
        builtin = self._builtin_by_id(sid)
        if builtin is not None:
            return self._builtin_xml(builtin)
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            for item in self._uploaded(self._read_raw()):
                if str(item["id"]) == sid:
                    return str(item.get("csl_xml") or "")
        return None

    def get_active(self) -> dict[str, Any]:
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            uploaded = self._uploaded(raw)
            active_id = self._resolve_active_id(raw, uploaded)
            builtin = self._builtin_by_id(active_id)
            if builtin is not None:
                xml = self._builtin_xml(builtin)
            else:
                xml = next(
                    (
                        str(item.get("csl_xml") or "")
                        for item in uploaded
                        if str(item["id"]) == active_id
                    ),
                    "",
                )
            styles_meta = [
                {"id": style.id, "title": style.title}
                for style in _BUILTIN_STYLES
            ] + [
                {"id": str(item["id"]), "title": str(item.get("title") or item["id"])}
                for item in uploaded
            ]
        if not xml:
            # Fall back to the default builtin if the active style vanished.
            active_id = DEFAULT_STYLE_ID
            xml = self._builtin_xml(_BUILTIN_STYLES[0])
        title = next((meta["title"] for meta in styles_meta if meta["id"] == active_id), active_id)
        return {"id": active_id, "title": title, "csl_xml": xml}

    def import_style(self, csl_xml: str, *, title_override: str | None = None) -> dict[str, Any]:
        """Validate and store an uploaded CSL style; it becomes the active style.

        Re-uploading a style whose title matches an existing uploaded style
        updates that record in place instead of creating a duplicate.
        """
        parsed_title = validate_csl(csl_xml)
        final_title = (str(title_override or "").strip()) or parsed_title
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            uploaded = self._uploaded(raw)
            normalized = final_title.casefold()
            for item in uploaded:
                if str(item.get("title") or "").strip().casefold() == normalized:
                    item["csl_xml"] = csl_xml
                    item["title"] = final_title
                    item["updated_at"] = _now_iso()
                    raw["uploaded"] = uploaded
                    raw["active_style_id"] = str(item["id"])
                    self._write_raw(raw)
                    return {
                        "id": str(item["id"]),
                        "title": final_title,
                        "source": "uploaded",
                        "active": True,
                        "can_delete": True,
                        "created_at": item.get("created_at"),
                    }
            new_id = f"user-{uuid4().hex[:12]}"
            created = _now_iso()
            uploaded.append(
                {"id": new_id, "title": final_title, "csl_xml": csl_xml, "created_at": created}
            )
            raw["uploaded"] = uploaded
            raw["active_style_id"] = new_id
            self._write_raw(raw)
            return {
                "id": new_id,
                "title": final_title,
                "source": "uploaded",
                "active": True,
                "can_delete": True,
                "created_at": created,
            }

    def set_active(self, style_id: str) -> dict[str, Any]:
        sid = str(style_id or "").strip()
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            uploaded = self._uploaded(raw)
            valid = {style.id for style in _BUILTIN_STYLES} | {str(item["id"]) for item in uploaded}
            if sid not in valid:
                raise KeyError(sid)
            raw["active_style_id"] = sid
            raw["uploaded"] = uploaded
            self._write_raw(raw)
        return self.get_active()

    def delete_style(self, style_id: str) -> None:
        sid = str(style_id or "").strip()
        if self._builtin_by_id(sid) is not None:
            raise PermissionError("内置样式不可删除")
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            uploaded = self._uploaded(raw)
            remaining = [item for item in uploaded if str(item["id"]) != sid]
            if len(remaining) == len(uploaded):
                raise KeyError(sid)
            raw["uploaded"] = remaining
            if str(raw.get("active_style_id") or "") == sid:
                raw["active_style_id"] = DEFAULT_STYLE_ID
            self._write_raw(raw)


csl_style_store = CslStyleStore()

__all__ = [
    "CSL_NAMESPACE",
    "DEFAULT_STYLE_ID",
    "CslStyleStore",
    "CslValidationError",
    "csl_style_store",
    "validate_csl",
]
