# -*- coding: utf-8 -*-
"""Built-in optional OCR engine adapters.

These adapters are intentionally lightweight. They probe optional runtimes and
expose stable engine metadata without importing heavy dependencies at module
import time.
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import httpx

from .ocr_engine import OcrEngineHealth, OcrImageRegion, OcrImageResult, OcrReadinessStatus


_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*$")
_DEFAULT_WINDOWS_OCR_TIMEOUT_SECONDS = 90
_PADDLE_JOBS_API_PATH = "/api/v2/ocr/jobs"
_PADDLE_JOBS_INITIAL_POLL_SECONDS = 3.0
_PADDLE_JOBS_MAX_POLL_SECONDS = 15.0
_PADDLE_JOBS_POLL_MULTIPLIER = 1.5
_PADDLE_JOBS_DEFAULT_POLL_TIMEOUT_SECONDS = 600.0
_PADDLE_JOBS_STATES = {"pending", "running", "done", "failed"}
_PADDLE_JOBS_QUOTA_CODES = frozenset({12001})
_PADDLE_ERROR_DETAIL_MAX_CHARS = 300
_PADDLE_AUTHORIZATION_DETAIL_RE = re.compile(
    r"(?i)(\bauthorization\b\s*(?:[:=]\s*|\s+))(?:bearer\s+)?[^\s,;]+"
)
_PADDLE_SECRET_DETAIL_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|api[_-]?key|authorization|bearer)\b"
    r"\s*(?:[:=]\s*|\s+))[^\s,;]+"
)
_PADDLE_OCR_RESULT_MODELS = frozenset({"PP-OCRv5"})
_PADDLE_DOCUMENT_RESULT_MODELS = frozenset(
    {"PP-StructureV3", "PaddleOCR-VL", "PaddleOCR-VL-1.5", "PaddleOCR-VL-1.6"}
)
_PADDLE_IMAGE_TYPES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
    (b"BM", ".bmp", "image/bmp"),
    (b"II*\x00", ".tiff", "image/tiff"),
    (b"MM\x00*", ".tiff", "image/tiff"),
)
_PADDLE_SUFFIX_MIME_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}
_PADDLE_BLOCK_TYPES = {
    "doc_title": "Heading",
    "figure": "Image",
    "figure_caption": "FigureCaption",
    "figure_title": "FigureCaption",
    "formula": "Equation",
    "image": "Image",
    "image_caption": "FigureCaption",
    "list": "ListItem",
    "paragraph": "Paragraph",
    "table": "Table",
    "table_caption": "TableCaption",
    "table_title": "TableCaption",
    "text": "Text",
    "title": "Heading",
}
_REMOTE_OCR_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "generic": {
        "base_url": "",
        "endpoint_path": "/ocr",
        "model": "",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "endpoint_path": "/ocr",
        "model": "mistral-ocr-latest",
    },
    "mineru": {
        "base_url": "https://mineru.net/api",
        "endpoint_path": "/v4/file-urls/batch",
        "model": "pipeline",
    },
    "paddle_jobs": {
        "base_url": "",
        "endpoint_path": "",
        "model": "",
    },
}
_EXTERNAL_OCR_JSON_PREFIX = "__LITASSIST_OCR_JSON__"
_PADDLEOCR_PYTHON_ENV_VAR = "LITASSIST_PADDLEOCR_PYTHON"
_RAPIDOCR_PYTHON_ENV_VAR = "LITASSIST_RAPIDOCR_PYTHON"
_EXTERNAL_PADDLEOCR_PROBE_SCRIPT = f"""
import importlib.util
import json

payload = {{
    "paddleocr_present": importlib.util.find_spec("paddleocr") is not None,
    "paddle_present": importlib.util.find_spec("paddle") is not None,
}}
print({_EXTERNAL_OCR_JSON_PREFIX!r} + json.dumps(payload, ensure_ascii=False))
""".strip()
_EXTERNAL_PADDLEOCR_EXECUTION_SCRIPT = f"""
import importlib
import json
import sys

PREFIX = {_EXTERNAL_OCR_JSON_PREFIX!r}


def collect_text(value, fragments):
    json_attr = getattr(value, "json", None)
    if isinstance(json_attr, dict):
        collect_text(json_attr, fragments)
        return
    if callable(json_attr):
        try:
            parsed = json_attr()
        except TypeError:
            parsed = None
        if parsed is not None:
            collect_text(parsed, fragments)
            return
    if isinstance(value, dict):
        for key in ("rec_texts", "texts", "text", "markdown", "content"):
            if key in value:
                collect_text(value[key], fragments)
        for key in ("res", "result", "data", "page", "pages"):
            if key in value:
                collect_text(value[key], fragments)
        return
    if isinstance(value, str):
        if value.strip():
            fragments.append(value)
        return
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1]:
            text = value[1][0]
            if isinstance(text, str) and text.strip():
                fragments.append(text)
                return
        if len(value) >= 3 and isinstance(value[1], str):
            fragments.append(value[1])
            return
        for item in value:
            collect_text(item, fragments)


def main():
    request = json.loads(sys.stdin.read())
    module = importlib.import_module("paddleocr")
    runtime_cls = getattr(module, "PaddleOCR", None)
    if runtime_cls is None or not callable(runtime_cls):
        raise RuntimeError("paddleocr runtime does not expose callable PaddleOCR")
    runtime = runtime_cls(**dict(request.get("constructor_kwargs") or {{}}))
    method_kwargs = dict(request.get("method_kwargs") or {{}})
    requested = request.get("runtime_method")
    method_names = [requested] if requested else ["predict", "ocr", "__call__"]
    result = None
    for method_name in method_names:
        method = runtime if method_name == "__call__" else getattr(runtime, method_name, None)
        if callable(method):
            result = method(request["image_path"], **method_kwargs)
            break
    if result is None:
        raise RuntimeError("PaddleOCR runtime does not expose predict, ocr, or __call__")
    fragments = []
    collect_text(result, fragments)
    normalized = []
    for fragment in fragments:
        cleaned = str(fragment).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    print(PREFIX + json.dumps({{"text": "\\n".join(normalized)}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
""".strip()
_EXTERNAL_RAPIDOCR_PROBE_SCRIPT = f"""
import importlib.util
import json

payload = {{
    "rapidocr_present": importlib.util.find_spec("rapidocr") is not None,
    "rapidocr_onnxruntime_present": importlib.util.find_spec("rapidocr_onnxruntime") is not None,
}}
print({_EXTERNAL_OCR_JSON_PREFIX!r} + json.dumps(payload, ensure_ascii=False))
""".strip()
_EXTERNAL_RAPIDOCR_EXECUTION_SCRIPT = f"""
import importlib
import json
import sys

PREFIX = {_EXTERNAL_OCR_JSON_PREFIX!r}


def collect_text(value, fragments):
    txts = getattr(value, "txts", None)
    if isinstance(txts, (list, tuple)):
        for item in txts:
            collect_text(item, fragments)
        return
    if isinstance(value, dict):
        for key in ("text", "rec_text", "content", "markdown"):
            if key in value:
                collect_text(value[key], fragments)
        for key in ("result", "res", "data", "pages"):
            if key in value:
                collect_text(value[key], fragments)
        return
    if isinstance(value, str):
        if value.strip():
            fragments.append(value)
        return
    if isinstance(value, (list, tuple)):
        if len(value) >= 3 and isinstance(value[1], str):
            fragments.append(value[1])
            return
        for item in value:
            collect_text(item, fragments)


def main():
    request = json.loads(sys.stdin.read())
    try:
        module = importlib.import_module("rapidocr")
    except ImportError:
        module = importlib.import_module("rapidocr_onnxruntime")
    runtime_cls = getattr(module, "RapidOCR", None)
    if runtime_cls is None or not callable(runtime_cls):
        raise RuntimeError("RapidOCR runtime does not expose callable RapidOCR")
    result = runtime_cls(**dict(request.get("constructor_kwargs") or {{}}))(request["image_path"])
    fragments = []
    collect_text(result, fragments)
    normalized = []
    for fragment in fragments:
        cleaned = str(fragment).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    print(PREFIX + json.dumps({{"text": "\\n".join(normalized)}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
""".strip()


class _BaseOptionalOcrEngine:
    """Shared guards for optional OCR engines."""

    name = "unknown"
    display_name = "Unknown OCR"
    engine_type = "local"
    requires_network = False

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def _health_from_availability(self) -> OcrEngineHealth:
        started = time.perf_counter()
        ok = self.is_available()
        elapsed = (time.perf_counter() - started) * 1000.0
        detail = "available" if ok else (self.unavailable_reason() or "unavailable")
        readiness_status = "ready" if ok else self.readiness_status()
        return OcrEngineHealth(
            ok=ok,
            detail=detail,
            engine=self.name,
            latency_ms=round(elapsed, 3),
            readiness_status=readiness_status,
            readiness_blockers=() if ok else self.readiness_blockers(),
        )

    def unavailable_reason(self) -> str | None:
        return None if self.is_available() else "engine is not available"

    def readiness_status(self) -> OcrReadinessStatus:
        """Return a stable reason class for local readiness gates."""

        return "ready" if self.is_available() else "unavailable"

    def readiness_blockers(self) -> tuple[str, ...]:
        """Return bounded blockers without probing page content."""

        reason = self.unavailable_reason()
        return () if reason is None else (reason,)

    def health_check(self) -> OcrEngineHealth:
        return self._health_from_availability()


def _powershell_string_literal(value: str) -> str:
    """Return a single-quoted PowerShell literal for local file/config values."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return "'" + value.replace("'", "''") + "'"


def _validate_language_tag(language: str) -> str:
    text = str(language or "en").strip()
    if not text:
        raise ValueError("OCR language must be non-empty")
    if not _LANGUAGE_TAG_RE.match(text):
        raise ValueError(f"invalid OCR language tag: {text!r}")
    return text


def _optional_module_present(module_name: str) -> bool:
    """Return dependency presence without importing optional OCR runtimes."""

    if not isinstance(module_name, str) or not module_name.strip():
        raise ValueError("module_name must be a non-empty string")
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _extract_rapidocr_text(raw_result: Any) -> str:
    """Normalize common RapidOCR result shapes into newline-delimited text."""

    if raw_result is None:
        return ""
    if isinstance(raw_result, str):
        return raw_result

    txts = getattr(raw_result, "txts", None)
    if isinstance(txts, (list, tuple)):
        return "\n".join(str(item).strip() for item in txts if str(item).strip())

    result_payload = raw_result
    if isinstance(raw_result, tuple) and raw_result:
        result_payload = raw_result[0]

    if isinstance(result_payload, Mapping):
        text = result_payload.get("text") or result_payload.get("txt")
        return "" if text is None else str(text).strip()

    if not isinstance(result_payload, list):
        return str(result_payload).strip()

    lines: list[str] = []
    for item in result_payload:
        if isinstance(item, str):
            text = item
        elif isinstance(item, Mapping):
            text = str(item.get("text") or item.get("txt") or "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            text = str(item[1])
        else:
            text = ""
        cleaned = text.strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _extract_paddleocr_text(raw_result: Any) -> str:
    """Normalize common PaddleOCR result shapes into newline-delimited text."""

    fragments: list[str] = []
    _collect_paddleocr_text(raw_result, fragments)
    normalized: list[str] = []
    for fragment in fragments:
        cleaned = fragment.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return "\n".join(normalized)


def _collect_paddleocr_text(value: Any, fragments: list[str]) -> None:
    """Collect likely OCR text leaves from PaddleOCR v2/v3 result objects."""

    if value is None:
        return

    json_attr = getattr(value, "json", None)
    if isinstance(json_attr, Mapping):
        _collect_paddleocr_text(json_attr, fragments)
        return
    if callable(json_attr):
        try:
            parsed = json_attr()
        except TypeError:
            parsed = None
        if parsed is not None:
            _collect_paddleocr_text(parsed, fragments)
            return

    if isinstance(value, Mapping):
        for key in ("rec_texts", "texts", "text", "markdown", "content"):
            if key in value:
                _collect_paddleocr_text(value[key], fragments)
        for key in ("res", "result", "data", "page", "pages"):
            if key in value:
                _collect_paddleocr_text(value[key], fragments)
        return

    if isinstance(value, str):
        if value.strip():
            fragments.append(value)
        return

    if isinstance(value, (list, tuple)):
        if _looks_like_paddleocr_v2_line(value):
            text = value[1][0]
            if isinstance(text, str) and text.strip():
                fragments.append(text)
            return
        if len(value) >= 3 and isinstance(value[1], str):
            fragments.append(value[1])
            return
        for item in value:
            _collect_paddleocr_text(item, fragments)


def _looks_like_paddleocr_v2_line(value: list[Any] | tuple[Any, ...]) -> bool:
    """Return whether a list resembles ``[box, (text, score)]``."""

    if len(value) < 2 or not isinstance(value[1], (list, tuple)):
        return False
    if not value[1]:
        return False
    return isinstance(value[1][0], str)


def _run_powershell_script(
    script: str,
    *,
    timeout_seconds: int,
    executable: str,
) -> str:
    """Run a local encoded PowerShell WinRT script and return stdout text."""

    if not isinstance(script, str) or not script.strip():
        raise ValueError("script must be a non-empty string")
    if isinstance(timeout_seconds, bool) or timeout_seconds < 5:
        raise ValueError("timeout_seconds must be at least 5")
    if not isinstance(executable, str) or not executable.strip():
        raise ValueError("executable must be a non-empty string")

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        completed = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-OutputFormat",
                "Text",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Windows OCR timed out") from exc

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"PowerShell exited with {completed.returncode}"
        raise RuntimeError(detail[:500])
    return stdout


def _parse_external_ocr_json(stdout: str) -> Mapping[str, Any]:
    """Parse the last bounded JSON receipt emitted by an external OCR process."""

    if not isinstance(stdout, str):
        raise TypeError("stdout must be a string")
    for line in reversed(stdout.splitlines()):
        if line.startswith(_EXTERNAL_OCR_JSON_PREFIX):
            payload = json.loads(line[len(_EXTERNAL_OCR_JSON_PREFIX) :])
            if not isinstance(payload, Mapping):
                raise RuntimeError("external OCR receipt must be a JSON object")
            return payload
    raise RuntimeError("external OCR process did not emit a receipt")


def _run_external_python_json(
    executable: Path,
    script: str,
    *,
    timeout_seconds: int,
    payload: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Run a bounded Python OCR helper and return its JSON receipt."""

    if not isinstance(executable, Path):
        raise TypeError("executable must be a pathlib.Path")
    if not executable.is_file():
        raise FileNotFoundError(f"Python executable not found: {executable}")
    if not isinstance(script, str) or not script.strip():
        raise ValueError("script must be a non-empty string")
    if isinstance(timeout_seconds, bool) or timeout_seconds < 5:
        raise ValueError("timeout_seconds must be at least 5")

    request_text = "" if payload is None else json.dumps(dict(payload), ensure_ascii=False)
    try:
        completed = subprocess.run(
            [str(executable), "-c", script],
            input=request_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("external OCR process timed out") from exc

    stdout = str(completed.stdout or "")
    stderr = str(completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr or stdout.strip() or f"external Python exited with {completed.returncode}"
        raise RuntimeError(detail[:500])
    return _parse_external_ocr_json(stdout)


def _windows_ocr_script(image_path: Path, *, language_tag: str) -> str:
    """Render the PowerShell script used to call Windows.Media.Ocr."""

    if not isinstance(image_path, Path):
        raise TypeError("image_path must be a pathlib.Path")
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"OCR image not found: {image_path}")
    language = _validate_language_tag(language_tag)
    return f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$Path = {_powershell_string_literal(str(image_path))}
$LanguageTag = {_powershell_string_literal(language)}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$AsTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
}} | Select-Object -First 1)
if ($null -eq $AsTask) {{ throw 'WinRT AsTask bridge is unavailable.' }}
function Await-WinRt($Operation, [Type]$ResultType) {{
  $Task = $AsTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
  $Task.Wait()
  if ($Task.IsFaulted) {{ throw $Task.Exception }}
  return $Task.Result
}}
$Stream = $null
try {{
  $File = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
  $Stream = Await-WinRt ($File.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $Decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($Stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $Bitmap = Await-WinRt ($Decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $Language = [Windows.Globalization.Language]::new($LanguageTag)
  $Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($Language)
  if ($null -eq $Engine) {{ throw "Windows OCR engine is unavailable for language '$LanguageTag'." }}
  if ($Bitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $Bitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {{
    throw "Rendered image exceeds Windows OCR maximum dimension."
  }}
  $Result = Await-WinRt ($Engine.RecognizeAsync($Bitmap)) ([Windows.Media.Ocr.OcrResult])
  $Result.Text
}} finally {{
  if ($null -ne $Stream) {{ $Stream.Dispose() }}
}}
""".strip()


def _windows_ocr_probe_script(*, language_tag: str) -> str:
    """Render a no-content WinRT availability probe for Windows OCR."""

    language = _validate_language_tag(language_tag)
    return f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$LanguageTag = {_powershell_string_literal(language)}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$Language = [Windows.Globalization.Language]::new($LanguageTag)
$Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($Language)
if ($null -eq $Engine) {{ throw "Windows OCR engine is unavailable for language '$LanguageTag'." }}
'available'
""".strip()


class PaddleOcrGpuEngine(_BaseOptionalOcrEngine):
    """PaddleOCR adapter with lazy optional-runtime execution."""

    name = "paddleocr_gpu"
    display_name = "PaddleOCR GPU"
    engine_type = "local"
    requires_network = False

    def _external_python_executable(self) -> Path | None:
        raw = str(
            self.config.get("python_executable")
            or os.environ.get(_PADDLEOCR_PYTHON_ENV_VAR)
            or ""
        ).strip()
        if not raw:
            return None
        return Path(raw).expanduser().resolve()

    def _external_timeout_seconds(self) -> int:
        raw = self.config.get("timeout_seconds", 300)
        if isinstance(raw, bool):
            raise ValueError("PaddleOCR timeout_seconds must be an integer")
        timeout = int(raw)
        if timeout < 5:
            raise ValueError("PaddleOCR timeout_seconds must be at least 5")
        if timeout > 1800:
            raise ValueError("PaddleOCR timeout_seconds must be 1800 or fewer")
        return timeout

    def _external_probe(self) -> Mapping[str, Any]:
        executable = self._external_python_executable()
        if executable is None:
            return {}
        return _run_external_python_json(
            executable,
            _EXTERNAL_PADDLEOCR_PROBE_SCRIPT,
            timeout_seconds=min(self._external_timeout_seconds(), 30),
        )

    def _dependency_present(self) -> bool:
        if self._external_python_executable() is not None:
            try:
                probe = self._external_probe()
            except Exception:
                return False
            return probe.get("paddleocr_present") is True and probe.get("paddle_present") is True
        return _optional_module_present("paddleocr") and _optional_module_present("paddle")

    def _missing_dependency_reason(
        self,
        *,
        paddleocr_present: bool,
        paddle_present: bool,
        runtime_label: str,
    ) -> str:
        """Return a bounded dependency blocker for one PaddleOCR Python runtime.

        Args:
            paddleocr_present: Whether ``importlib`` can locate ``paddleocr``.
            paddle_present: Whether ``importlib`` can locate PaddlePaddle's
                runtime module ``paddle``.
            runtime_label: Non-empty label for the probed Python runtime.

        Returns:
            Human-readable blocker without local secrets.
        """

        if not isinstance(paddleocr_present, bool) or not isinstance(paddle_present, bool):
            raise TypeError("dependency presence flags must be booleans")
        label = str(runtime_label or "").strip()
        if not label:
            raise ValueError("runtime_label must be non-empty")

        missing: list[str] = []
        if not paddleocr_present:
            missing.append("paddleocr")
        if not paddle_present:
            missing.append("paddlepaddle runtime module 'paddle'")
        if not missing:
            return ""
        verb = "is" if len(missing) == 1 else "are"
        return f"{' and '.join(missing)} {verb} not installed in the {label}"

    def is_available(self) -> bool:
        return self._dependency_present()

    def unavailable_reason(self) -> str | None:
        external_python = self._external_python_executable()
        if external_python is not None:
            try:
                probe = self._external_probe()
            except Exception as exc:  # noqa: BLE001 - bounded local readiness diagnostic
                return f"external PaddleOCR Python is unavailable: {str(exc)[:300]}"
            reason = self._missing_dependency_reason(
                paddleocr_present=probe.get("paddleocr_present") is True,
                paddle_present=probe.get("paddle_present") is True,
                runtime_label="configured external Python runtime",
            )
            if reason:
                return reason
            return None
        reason = self._missing_dependency_reason(
            paddleocr_present=_optional_module_present("paddleocr"),
            paddle_present=_optional_module_present("paddle"),
            runtime_label="active Python runtime",
        )
        if not reason:
            return None
        return reason

    def readiness_status(self) -> OcrReadinessStatus:
        if not self._dependency_present():
            return "dependency_missing"
        return "ready"

    def health_check(self) -> OcrEngineHealth:
        started = time.perf_counter()
        external_python = self._external_python_executable()
        if external_python is None:
            return self._health_from_availability()
        try:
            probe = self._external_probe()
        except Exception as exc:  # noqa: BLE001 - bounded local readiness diagnostic
            elapsed = (time.perf_counter() - started) * 1000.0
            detail = f"external PaddleOCR Python is unavailable: {str(exc)[:300]}"
            return OcrEngineHealth(
                ok=False,
                detail=detail,
                engine=self.name,
                latency_ms=round(elapsed, 3),
                readiness_status="dependency_missing",
                readiness_blockers=(detail,),
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        ok = probe.get("paddleocr_present") is True and probe.get("paddle_present") is True
        missing_reason = self._missing_dependency_reason(
            paddleocr_present=probe.get("paddleocr_present") is True,
            paddle_present=probe.get("paddle_present") is True,
            runtime_label="configured external Python runtime",
        )
        detail = "available via external Python runtime" if ok else missing_reason
        return OcrEngineHealth(
            ok=ok,
            detail=detail,
            engine=self.name,
            latency_ms=round(elapsed, 3),
            readiness_status="ready" if ok else "dependency_missing",
            readiness_blockers=() if ok else (detail,),
        )

    def _build_runtime(self) -> Any:
        """Create the optional PaddleOCR runtime only when OCR is requested."""

        if not self._dependency_present():
            raise RuntimeError(self.unavailable_reason() or "PaddleOCR is unavailable")

        constructor_kwargs = self._constructor_kwargs()
        module = importlib.import_module("paddleocr")
        runtime_cls = getattr(module, "PaddleOCR", None)
        if runtime_cls is None or not callable(runtime_cls):
            raise RuntimeError("paddleocr runtime does not expose callable PaddleOCR")
        return runtime_cls(**constructor_kwargs)

    def _method_kwargs(self) -> dict[str, Any]:
        raw = self.config.get("method_kwargs", {})
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError("PaddleOCR method_kwargs must be a JSON object")
        return dict(raw)

    def _runtime_method_name(self) -> str | None:
        raw = self.config.get("runtime_method")
        if raw is None:
            return None
        text = str(raw).strip()
        if text not in {"predict", "ocr", "__call__"}:
            raise ValueError("PaddleOCR runtime_method must be one of: predict, ocr, __call__")
        return text

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        _validate_language_tag(language)

        cleanup_path: Path | None = None
        if isinstance(image, Path):
            image_input: str = str(image)
            if not image.is_file():
                raise FileNotFoundError(f"OCR image not found: {image}")
            if image.stat().st_size <= 0:
                raise ValueError("PaddleOCR image file must be non-empty")
        else:
            if not image:
                raise ValueError("PaddleOCR image bytes must be non-empty")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as handle:
                handle.write(image)
                cleanup_path = Path(handle.name)
            image_input = str(cleanup_path)

        try:
            method_kwargs = self._method_kwargs()
            requested_method = self._runtime_method_name()
            external_python = self._external_python_executable()
            if external_python is not None:
                payload = {
                    "image_path": image_input,
                    "constructor_kwargs": self._constructor_kwargs(),
                    "method_kwargs": method_kwargs,
                    "runtime_method": requested_method,
                }
                result = _run_external_python_json(
                    external_python,
                    _EXTERNAL_PADDLEOCR_EXECUTION_SCRIPT,
                    timeout_seconds=self._external_timeout_seconds(),
                    payload=payload,
                )
                return str(result.get("text") or "").strip()
            runtime = self._build_runtime()
            result = self._run_runtime(runtime, image_input, requested_method, method_kwargs)
            return _extract_paddleocr_text(result).strip()
        finally:
            if cleanup_path is not None:
                try:
                    cleanup_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _constructor_kwargs(self) -> dict[str, Any]:
        raw = self.config.get("constructor_kwargs", {})
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError("PaddleOCR constructor_kwargs must be a JSON object")
        return dict(raw)

    def _run_runtime(
        self,
        runtime: Any,
        image_input: str,
        requested_method: str | None,
        method_kwargs: Mapping[str, Any],
    ) -> Any:
        method_names = [requested_method] if requested_method else ["predict", "ocr", "__call__"]
        for method_name in method_names:
            if method_name is None:
                continue
            method = runtime if method_name == "__call__" else getattr(runtime, method_name, None)
            if callable(method):
                return method(image_input, **dict(method_kwargs))
        raise RuntimeError("PaddleOCR runtime does not expose predict, ocr, or __call__")


class RapidOcrEngine(_BaseOptionalOcrEngine):
    """RapidOCR adapter with lazy optional-runtime execution."""

    name = "rapidocr"
    display_name = "RapidOCR"
    engine_type = "local"
    requires_network = False

    def _external_python_executable(self) -> Path | None:
        raw = str(
            self.config.get("python_executable")
            or os.environ.get(_RAPIDOCR_PYTHON_ENV_VAR)
            or ""
        ).strip()
        if not raw:
            return None
        return Path(raw).expanduser().resolve()

    def _timeout_seconds(self) -> int:
        raw = self.config.get("timeout_seconds", 300)
        if isinstance(raw, bool):
            raise ValueError("RapidOCR timeout_seconds must be an integer")
        timeout = int(raw)
        if timeout < 5:
            raise ValueError("RapidOCR timeout_seconds must be at least 5")
        if timeout > 1800:
            raise ValueError("RapidOCR timeout_seconds must be 1800 or fewer")
        return timeout

    def _constructor_kwargs(self) -> dict[str, Any]:
        raw = self.config.get("constructor_kwargs", {})
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError("RapidOCR constructor_kwargs must be a JSON object")
        return dict(raw)

    def _external_probe(self) -> Mapping[str, Any]:
        executable = self._external_python_executable()
        if executable is None:
            return {}
        return _run_external_python_json(
            executable,
            _EXTERNAL_RAPIDOCR_PROBE_SCRIPT,
            timeout_seconds=min(self._timeout_seconds(), 30),
        )

    def _dependency_present(self) -> bool:
        if self._external_python_executable() is not None:
            try:
                probe = self._external_probe()
            except Exception:
                return False
            return probe.get("rapidocr_present") is True or (
                probe.get("rapidocr_onnxruntime_present") is True
            )
        return _optional_module_present("rapidocr") or _optional_module_present(
            "rapidocr_onnxruntime"
        )

    def is_available(self) -> bool:
        return self._dependency_present()

    def unavailable_reason(self) -> str | None:
        external_python = self._external_python_executable()
        if external_python is not None:
            try:
                probe = self._external_probe()
            except Exception as exc:  # noqa: BLE001 - bounded local readiness diagnostic
                return f"external RapidOCR Python is unavailable: {str(exc)[:300]}"
            if not (
                probe.get("rapidocr_present") is True
                or probe.get("rapidocr_onnxruntime_present") is True
            ):
                return "rapidocr or rapidocr_onnxruntime is not installed in the configured external Python runtime"
            return None
        if not self._dependency_present():
            return "rapidocr or rapidocr_onnxruntime is not installed"
        return None

    def readiness_status(self) -> OcrReadinessStatus:
        if not self._dependency_present():
            return "dependency_missing"
        return "ready"

    def health_check(self) -> OcrEngineHealth:
        started = time.perf_counter()
        external_python = self._external_python_executable()
        if external_python is None:
            return self._health_from_availability()
        try:
            probe = self._external_probe()
        except Exception as exc:  # noqa: BLE001 - bounded local readiness diagnostic
            elapsed = (time.perf_counter() - started) * 1000.0
            detail = f"external RapidOCR Python is unavailable: {str(exc)[:300]}"
            return OcrEngineHealth(
                ok=False,
                detail=detail,
                engine=self.name,
                latency_ms=round(elapsed, 3),
                readiness_status="dependency_missing",
                readiness_blockers=(detail,),
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        ok = probe.get("rapidocr_present") is True or (
            probe.get("rapidocr_onnxruntime_present") is True
        )
        detail = (
            "available via external Python runtime"
            if ok
            else "rapidocr or rapidocr_onnxruntime is not installed in the configured external Python runtime"
        )
        return OcrEngineHealth(
            ok=ok,
            detail=detail,
            engine=self.name,
            latency_ms=round(elapsed, 3),
            readiness_status="ready" if ok else "dependency_missing",
            readiness_blockers=() if ok else (detail,),
        )

    def _build_runtime(self) -> Any:
        """Create the optional RapidOCR runtime only when page OCR is requested."""

        constructor_kwargs = self._constructor_kwargs()
        if not self._dependency_present():
            raise RuntimeError(self.unavailable_reason() or "RapidOCR is unavailable")

        try:
            module = importlib.import_module("rapidocr")
        except ImportError:
            module = importlib.import_module("rapidocr_onnxruntime")

        runtime_cls = getattr(module, "RapidOCR", None)
        if runtime_cls is None or not callable(runtime_cls):
            raise RuntimeError("RapidOCR runtime does not expose callable RapidOCR")

        return runtime_cls(**constructor_kwargs)

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        _validate_language_tag(language)

        cleanup_path: Path | None = None
        if isinstance(image, Path):
            image_input: str = str(image)
            if not image.is_file():
                raise FileNotFoundError(f"OCR image not found: {image}")
            if image.stat().st_size <= 0:
                raise ValueError("RapidOCR image file must be non-empty")
        else:
            if not image:
                raise ValueError("RapidOCR image bytes must be non-empty")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as handle:
                handle.write(image)
                cleanup_path = Path(handle.name)
            image_input = str(cleanup_path)

        try:
            external_python = self._external_python_executable()
            if external_python is not None:
                result = _run_external_python_json(
                    external_python,
                    _EXTERNAL_RAPIDOCR_EXECUTION_SCRIPT,
                    timeout_seconds=self._timeout_seconds(),
                    payload={
                        "image_path": image_input,
                        "constructor_kwargs": self._constructor_kwargs(),
                    },
                )
                return str(result.get("text") or "").strip()
            runtime = self._build_runtime()
            return _extract_rapidocr_text(runtime(image_input)).strip()
        finally:
            if cleanup_path is not None:
                try:
                    cleanup_path.unlink(missing_ok=True)
                except OSError:
                    pass


class WindowsOcrEngine(_BaseOptionalOcrEngine):
    """Windows local OCR adapter using Windows.Media.Ocr through PowerShell."""

    name = "windows"
    display_name = "Windows OCR"
    engine_type = "local"
    requires_network = False

    def _powershell_executable(self) -> str | None:
        configured = str(self.config.get("powershell_executable") or "").strip()
        if configured:
            return configured
        return shutil.which("powershell.exe") or shutil.which("powershell")

    def _timeout_seconds(self) -> int:
        raw = self.config.get("timeout_seconds", _DEFAULT_WINDOWS_OCR_TIMEOUT_SECONDS)
        if isinstance(raw, bool):
            raise ValueError("timeout_seconds must be an integer")
        timeout = int(raw)
        if timeout < 5:
            raise ValueError("timeout_seconds must be at least 5")
        if timeout > 600:
            raise ValueError("timeout_seconds must be 600 or fewer")
        return timeout

    def is_available(self) -> bool:
        return sys.platform == "win32" and self._powershell_executable() is not None

    def unavailable_reason(self) -> str | None:
        if sys.platform != "win32":
            return "Windows OCR is available only on Windows"
        if self._powershell_executable() is None:
            return "powershell.exe is required for Windows OCR"
        return None

    def readiness_status(self) -> OcrReadinessStatus:
        if sys.platform != "win32":
            return "platform_unsupported"
        if self._powershell_executable() is None:
            return "dependency_missing"
        return "ready"

    def health_check(self) -> OcrEngineHealth:
        started = time.perf_counter()
        if not self.is_available():
            return self._health_from_availability()
        language = _validate_language_tag(str(self.config.get("language") or "en"))
        executable = self._powershell_executable()
        if executable is None:
            return self._health_from_availability()
        try:
            _run_powershell_script(
                _windows_ocr_probe_script(language_tag=language),
                timeout_seconds=min(self._timeout_seconds(), 30),
                executable=executable,
            )
        except Exception as exc:  # noqa: BLE001 - bounded readiness diagnostic
            elapsed = (time.perf_counter() - started) * 1000.0
            return OcrEngineHealth(
                ok=False,
                detail=str(exc)[:500],
                engine=self.name,
                latency_ms=round(elapsed, 3),
                readiness_status="unavailable",
                readiness_blockers=(str(exc)[:500],),
            )
        elapsed = (time.perf_counter() - started) * 1000.0
        return OcrEngineHealth(
            ok=True,
            detail="available",
            engine=self.name,
            latency_ms=round(elapsed, 3),
            readiness_status="ready",
        )

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        if not self.is_available():
            raise RuntimeError(self.unavailable_reason() or "Windows OCR is unavailable")

        language_tag = _validate_language_tag(language or str(self.config.get("language") or "en"))
        executable = self._powershell_executable()
        if executable is None:
            raise RuntimeError("powershell.exe is required for Windows OCR")

        cleanup_path: Path | None = None
        if isinstance(image, Path):
            image_path = image
            if not image_path.is_file():
                raise FileNotFoundError(f"OCR image not found: {image_path}")
            if image_path.stat().st_size <= 0:
                raise ValueError("Windows OCR image file must be non-empty")
        else:
            if not image:
                raise ValueError("Windows OCR image bytes must be non-empty")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as handle:
                handle.write(image)
                cleanup_path = Path(handle.name)
            image_path = cleanup_path

        try:
            script = _windows_ocr_script(image_path, language_tag=language_tag)
            return _run_powershell_script(
                script,
                timeout_seconds=self._timeout_seconds(),
                executable=executable,
            ).strip()
        finally:
            if cleanup_path is not None:
                try:
                    cleanup_path.unlink(missing_ok=True)
                except OSError:
                    pass


class RemoteApiOcrEngine(_BaseOptionalOcrEngine):
    """Remote OCR adapter requiring credentials and explicit upload consent."""

    name = "remote_api"
    display_name = "Remote API OCR"
    engine_type = "remote"
    requires_network = True

    def is_available(self) -> bool:
        return self.unavailable_reason() is None

    def unavailable_reason(self) -> str | None:
        credential_error = str(self.config.get("_credential_error") or "").strip()
        if credential_error:
            return credential_error
        api_key = self._api_key()
        base_url = self._base_url()
        if api_key and base_url and not self._allow_remote_upload():
            return "remote OCR requires explicit allow_remote_upload=true consent"
        if api_key and base_url:
            try:
                provider = self._provider()
                self._validated_base_url()
                self._timeout_seconds()
            except (TypeError, ValueError) as exc:
                return str(exc)
            if provider == "mineru":
                return (
                    "MinerU uses asynchronous document parsing; configure it as "
                    "an OCR credential, but do not select it for page-level OCR."
                )
            if provider == "paddle_jobs":
                if not self._model():
                    return "PaddleOCR AIStudio jobs require a model name"
                try:
                    self._poll_timeout_seconds()
                except (TypeError, ValueError) as exc:
                    return str(exc)
                return None
            try:
                self._endpoint_path()
            except (TypeError, ValueError) as exc:
                return str(exc)
            return None
        return "remote OCR requires explicit api_key and base_url configuration"

    def readiness_status(self) -> OcrReadinessStatus:
        reason = self.unavailable_reason()
        if reason is None:
            return "ready"
        if "asynchronous document parsing" in reason or "not wired" in reason:
            return "adapter_not_wired"
        if "allow_remote_upload" in reason or "configuration" in reason:
            return "configuration_required"
        return "configuration_required"

    def health_check(self) -> OcrEngineHealth:
        started = time.perf_counter()
        ok = self.is_available()
        elapsed = (time.perf_counter() - started) * 1000.0
        detail = (
            "configured; page images upload only when OCR execution is requested"
            if ok
            else (self.unavailable_reason() or "unavailable")
        )
        return OcrEngineHealth(
            ok=ok,
            detail=detail,
            engine=self.name,
            latency_ms=round(elapsed, 3),
            readiness_status=self.readiness_status(),
            readiness_blockers=() if ok else self.readiness_blockers(),
        )

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        language_tag = _validate_language_tag(language)
        unavailable = self.unavailable_reason()
        if unavailable is not None:
            raise RuntimeError(unavailable)

        provider = self._provider()
        if provider == "mineru":
            raise RuntimeError(
                "MinerU uses an asynchronous document-parse workflow; use the "
                "remote document parser for whole-PDF parsing instead of page-level OCR."
            )

        image_bytes = self._read_image_bytes(image)
        if provider == "paddle_jobs":
            upload_filename, upload_mime_type = self._paddle_upload_metadata(
                image,
                image_bytes,
            )
            return self._run_paddle_jobs(
                image_bytes,
                upload_filename=upload_filename,
                upload_mime_type=upload_mime_type,
                image_size=self._paddle_image_size(image_bytes),
            ).text.strip()
        if provider == "mistral":
            payload = self._mistral_request_payload(image_bytes)
            response = self._post_ocr_payload(payload, provider=provider)
        else:
            payload = self._request_payload(image_bytes, language=language_tag)
            response = self._post_ocr_payload(payload, provider=provider)
        return self._extract_response_text(response).strip()

    def ocr_image_result(
        self,
        image: bytes | Path,
        *,
        language: str = "en",
    ) -> OcrImageResult:
        """Return a layout-aware OCR result without changing ``ocr_image``.

        Args:
            image: Non-empty encoded image bytes or an existing image path.
            language: Valid BCP-47-like language tag retained for adapter
                compatibility. Paddle jobs currently derives behavior from its
                configured model and optional payload.

        Returns:
            Searchable text plus normalized page regions when the provider
            returns coordinates that still refer to the uploaded image.

        Raises:
            TypeError: If the image or language shape is invalid.
            RuntimeError: If the engine is unavailable or the remote job fails.
        """

        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        _validate_language_tag(language)
        unavailable = self.unavailable_reason()
        if unavailable is not None:
            raise RuntimeError(unavailable)
        if self._provider() != "paddle_jobs":
            return OcrImageResult(text=self.ocr_image(image, language=language))

        image_bytes = self._read_image_bytes(image)
        upload_filename, upload_mime_type = self._paddle_upload_metadata(
            image,
            image_bytes,
        )
        result = self._run_paddle_jobs(
            image_bytes,
            upload_filename=upload_filename,
            upload_mime_type=upload_mime_type,
            image_size=self._paddle_image_size(image_bytes),
        )
        if not isinstance(result, OcrImageResult):
            raise RuntimeError("PaddleOCR jobs adapter returned an invalid OCR result")
        return result

    def _provider(self) -> str:
        raw = str(self.config.get("provider") or "generic").strip().lower()
        if raw in {"", "custom"}:
            return "generic"
        if raw not in _REMOTE_OCR_PROVIDER_DEFAULTS:
            raise ValueError(
                "remote OCR provider must be one of: generic, mistral, mineru, paddle_jobs"
            )
        return raw

    def _api_key(self) -> str:
        return str(
            self.config.get("api_key") or os.environ.get("LITASSIST_OCR_API_KEY") or ""
        ).strip()

    def _base_url(self) -> str:
        provider = self._provider()
        default = _REMOTE_OCR_PROVIDER_DEFAULTS[provider]["base_url"]
        return str(
            self.config.get("base_url")
            or os.environ.get("LITASSIST_OCR_BASE_URL")
            or default
        ).strip()

    def _model(self) -> str:
        provider = self._provider()
        default = _REMOTE_OCR_PROVIDER_DEFAULTS[provider]["model"]
        return str(self.config.get("model") or default).strip()

    def _allow_remote_upload(self) -> bool:
        value = self.config.get("allow_remote_upload", False)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _validated_base_url(self) -> str:
        base_url = self._base_url()
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("remote OCR requires valid http(s) base_url configuration")
        if parsed.scheme == "http" and not self._allow_insecure_http(parsed.hostname or ""):
            raise ValueError("remote OCR base_url must use https unless local insecure HTTP is allowed")
        return base_url.rstrip("/") + "/"

    def _allow_insecure_http(self, hostname: str) -> bool:
        explicit = self.config.get("allow_insecure_http", False)
        if isinstance(explicit, bool) and explicit:
            return True
        normalized = hostname.lower()
        return normalized in {"localhost", "127.0.0.1", "::1"}

    def _endpoint_path(self) -> str:
        provider = self._provider()
        default = _REMOTE_OCR_PROVIDER_DEFAULTS[provider]["endpoint_path"]
        raw = str(self.config.get("endpoint_path") or default).strip()
        if not raw:
            raise ValueError("remote OCR endpoint_path must be non-empty")
        if not raw.startswith("/"):
            raw = "/" + raw
        return raw

    def _timeout_seconds(self) -> float:
        raw = self.config.get("timeout_seconds", 60)
        if isinstance(raw, bool):
            raise ValueError("remote OCR timeout_seconds must be numeric")
        timeout = float(raw)
        if not math.isfinite(timeout):
            raise ValueError("remote OCR timeout_seconds must be finite")
        if timeout < 5:
            raise ValueError("remote OCR timeout_seconds must be at least 5")
        if timeout > 600:
            raise ValueError("remote OCR timeout_seconds must be 600 or fewer")
        return timeout

    def _poll_timeout_seconds(self) -> float:
        raw = self.config.get(
            "poll_timeout_seconds",
            _PADDLE_JOBS_DEFAULT_POLL_TIMEOUT_SECONDS,
        )
        if isinstance(raw, bool):
            raise ValueError("remote OCR poll_timeout_seconds must be numeric")
        timeout = float(raw)
        if not math.isfinite(timeout):
            raise ValueError("remote OCR poll_timeout_seconds must be finite")
        if timeout < 5:
            raise ValueError("remote OCR poll_timeout_seconds must be at least 5")
        if timeout > 600:
            raise ValueError("remote OCR poll_timeout_seconds must be 600 or fewer")
        return timeout

    def _read_image_bytes(self, image: bytes | Path) -> bytes:
        if isinstance(image, bytes):
            if not image:
                raise ValueError("remote OCR image bytes must be non-empty")
            return image
        if not image.is_file():
            raise FileNotFoundError(f"OCR image not found: {image}")
        data = image.read_bytes()
        if not data:
            raise ValueError("remote OCR image file must be non-empty")
        return data

    def _paddle_upload_metadata(
        self,
        image: bytes | Path,
        image_bytes: bytes,
    ) -> tuple[str, str]:
        """Preserve a path name and derive a truthful multipart image type."""

        detected_suffix = ""
        detected_mime = ""
        if image_bytes.startswith(b"RIFF") and len(image_bytes) >= 12:
            if image_bytes[8:12] == b"WEBP":
                detected_suffix, detected_mime = ".webp", "image/webp"
        if not detected_mime:
            for magic, suffix, mime_type in _PADDLE_IMAGE_TYPES:
                if image_bytes.startswith(magic):
                    detected_suffix, detected_mime = suffix, mime_type
                    break

        if isinstance(image, Path):
            raw_filename = image.name or f"page{detected_suffix or '.png'}"
            filename = (
                raw_filename.replace("\r", "_")
                .replace("\n", "_")
                .replace('"', "_")[:180]
            )
            suffix_mime = _PADDLE_SUFFIX_MIME_TYPES.get(image.suffix.lower(), "")
            return filename, detected_mime or suffix_mime or "image/png"

        return f"page{detected_suffix or '.png'}", detected_mime or "image/png"

    def _paddle_image_size(self, image_bytes: bytes) -> tuple[int, int] | None:
        """Read original upload dimensions without making OCR depend on decoding."""

        try:
            from PIL import Image
        except ImportError:
            return None

        try:
            with Image.open(BytesIO(image_bytes)) as decoded:
                width, height = decoded.size
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
            return None
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            return None
        return width, height

    def _request_payload(self, image_bytes: bytes, *, language: str) -> dict[str, Any]:
        extra_payload = self.config.get("extra_payload", {})
        if extra_payload is None:
            extra_payload = {}
        if not isinstance(extra_payload, Mapping):
            raise ValueError("remote OCR extra_payload must be a JSON object")
        payload = dict(extra_payload)
        image_field = str(self.config.get("image_field") or "image_base64").strip()
        language_field = str(self.config.get("language_field") or "language").strip()
        if not image_field or not language_field:
            raise ValueError("remote OCR image_field and language_field must be non-empty")
        payload[image_field] = base64.b64encode(image_bytes).decode("ascii")
        payload[language_field] = language
        return payload

    def _mistral_request_payload(self, image_bytes: bytes) -> dict[str, Any]:
        model = self._model()
        if not model:
            raise ValueError("Mistral OCR requires a model name")
        return {
            "model": model,
            "document": {
                "type": "image_url",
                "image_url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}",
            },
        }

    def _post_ocr_payload(self, payload: Mapping[str, Any], *, provider: str) -> Any:
        url = self._joined_endpoint_url(self._endpoint_path())
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept": "application/json",
        }
        if provider == "mistral":
            headers["Content-Type"] = "application/json"
        with httpx.Client(timeout=self._timeout_seconds(), follow_redirects=False) as client:
            response = client.post(url, json=dict(payload), headers=headers)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("remote OCR response must be JSON") from exc

    def _joined_endpoint_url(self, endpoint_path: str) -> str:
        """Join an endpoint while preserving an already-complete base URL."""

        base_url = self._validated_base_url().rstrip("/")
        normalized_endpoint = "/" + endpoint_path.strip().strip("/")
        base_path = urlparse(base_url).path.rstrip("/")
        if base_path.endswith(normalized_endpoint):
            return base_url
        return urljoin(base_url + "/", normalized_endpoint.lstrip("/"))

    def _run_paddle_jobs(
        self,
        image_bytes: bytes,
        *,
        upload_filename: str,
        upload_mime_type: str,
        image_size: tuple[int, int] | None,
    ) -> OcrImageResult:
        """Run the official PaddleOCR submit-poll-result job protocol."""

        model = self._model()
        if not model:
            raise RuntimeError("PaddleOCR AIStudio jobs require a model name")
        optional_payload = self.config.get("extra_payload", {})
        if optional_payload is None:
            optional_payload = {}
        if not isinstance(optional_payload, Mapping):
            raise ValueError("remote OCR extra_payload must be a JSON object")

        jobs_url = self._joined_endpoint_url(_PADDLE_JOBS_API_PATH)
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept": "application/json",
        }
        form_data = {
            "model": model,
            "optionalPayload": json.dumps(dict(optional_payload), ensure_ascii=False),
        }
        files = {"file": (upload_filename, image_bytes, upload_mime_type)}

        with httpx.Client(
            timeout=self._timeout_seconds(),
            follow_redirects=False,
        ) as client:
            submit_response = self._paddle_request(
                lambda: client.post(
                    jobs_url,
                    data=form_data,
                    files=files,
                    headers=headers,
                ),
                operation="job submission",
            )
            submit_data = self._paddle_response_data(
                submit_response,
                operation="job submission",
            )
            job_id = submit_data.get("jobId")
            if not isinstance(job_id, str) or not job_id.strip():
                raise RuntimeError(
                    "PaddleOCR job submission response is missing data.jobId"
                )
            result_url = self._poll_paddle_job(
                client,
                jobs_url=jobs_url,
                job_id=job_id.strip(),
                headers=headers,
            )
            result_response = self._paddle_request(
                lambda: client.get(result_url, follow_redirects=True),
                operation="result download",
            )
            if not 200 <= result_response.status_code < 300:
                detail = self._safe_paddle_detail(result_response.text)
                raise RuntimeError(
                    "PaddleOCR result download failed "
                    f"(HTTP {result_response.status_code}): {detail}"
                )
            return self._paddle_jsonl_result(
                result_response.text,
                image_size=image_size,
            )

    def _poll_paddle_job(
        self,
        client: httpx.Client,
        *,
        jobs_url: str,
        job_id: str,
        headers: Mapping[str, str],
    ) -> str:
        """Poll one PaddleOCR job until a validated result URL is available."""

        deadline = time.monotonic() + self._poll_timeout_seconds()
        request_timeout = self._timeout_seconds()
        interval = _PADDLE_JOBS_INITIAL_POLL_SECONDS
        status_url = f"{jobs_url.rstrip('/')}/{job_id}"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"PaddleOCR job {job_id} polling timed out")
            status_response = self._paddle_request(
                lambda: client.get(
                    status_url,
                    headers=dict(headers),
                    timeout=min(request_timeout, remaining),
                ),
                operation="job status",
            )
            status_data = self._paddle_response_data(
                status_response,
                operation="job status",
            )
            state = status_data.get("state")
            if not isinstance(state, str):
                raise RuntimeError("PaddleOCR job status state must be a string")
            if state not in _PADDLE_JOBS_STATES:
                raise RuntimeError(
                    f"PaddleOCR job status has unknown or missing state: {state!r}"
                )
            if state == "failed":
                detail = self._safe_paddle_detail(
                    status_data.get("errorMsg"),
                    fallback="unknown provider error",
                )
                raise RuntimeError(f"PaddleOCR job {job_id} failed: {detail}")
            if state == "done":
                result_urls = status_data.get("resultUrl")
                if not isinstance(result_urls, Mapping):
                    raise RuntimeError(
                        "PaddleOCR completed job response is missing data.resultUrl"
                    )
                json_url = result_urls.get("jsonUrl")
                if not isinstance(json_url, str) or not json_url.strip():
                    raise RuntimeError(
                        "PaddleOCR completed job response is missing resultUrl.jsonUrl"
                    )
                return self._validated_paddle_result_url(json_url.strip())

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"PaddleOCR job {job_id} polling timed out")
            time.sleep(min(interval, remaining))
            interval = min(
                interval * _PADDLE_JOBS_POLL_MULTIPLIER,
                _PADDLE_JOBS_MAX_POLL_SECONDS,
            )

    def _validated_paddle_result_url(self, result_url: str) -> str:
        parsed = urlparse(result_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("PaddleOCR result URL must be a valid http(s) URL")
        if parsed.scheme == "http" and not self._allow_insecure_http(parsed.hostname or ""):
            raise RuntimeError("PaddleOCR result URL must use https")
        return result_url

    def _paddle_request(
        self,
        request: Any,
        *,
        operation: str,
    ) -> httpx.Response:
        try:
            response = request()
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"PaddleOCR {operation} timed out") from exc
        except httpx.RequestError as exc:
            detail = self._safe_paddle_detail(str(exc), fallback="request failed")
            raise RuntimeError(
                f"PaddleOCR {operation} network error: {detail}"
            ) from exc
        if not isinstance(response, httpx.Response):
            raise RuntimeError(f"PaddleOCR {operation} returned an invalid HTTP response")
        return response

    def _paddle_response_data(
        self,
        response: httpx.Response,
        *,
        operation: str,
    ) -> Mapping[str, Any]:
        message = ""
        try:
            payload = response.json()
        except ValueError as exc:
            if 200 <= response.status_code < 300:
                raise RuntimeError(
                    f"PaddleOCR {operation} response must be JSON"
                ) from exc
            payload = {}
            message = response.text.strip()
        if isinstance(payload, Mapping):
            payload_data = payload.get("data")
            nested_error = (
                payload_data.get("errorMsg")
                if isinstance(payload_data, Mapping)
                else None
            )
            message = str(
                payload.get("msg")
                or payload.get("errorMsg")
                or payload.get("message")
                or nested_error
                or message
            ).strip()
        safe_message = self._safe_paddle_detail(message)
        normalized_message = message.casefold()
        is_quota_error = any(
            marker in normalized_message
            for marker in ("quota", "rate limit", "too many requests")
        )
        is_auth_error = any(
            marker in normalized_message
            for marker in (
                "access token",
                "authentication",
                "credential",
                "invalid token",
                "unauthorized",
            )
        )
        is_invalid_request_error = any(
            marker in normalized_message
            for marker in ("invalid request", "invalid parameter", "bad request")
        )
        is_service_unavailable_error = any(
            marker in normalized_message
            for marker in (
                "service unavailable",
                "temporarily unavailable",
                "gateway timeout",
            )
        )
        if isinstance(payload, Mapping):
            code = payload.get("code", 0)
            if isinstance(code, bool) or (
                code is not None and not isinstance(code, int)
            ):
                raise RuntimeError(
                    f"PaddleOCR {operation} response code must be an integer or null"
                )
        else:
            code = 0
        is_business_error = (
            200 <= response.status_code < 300 and code not in {0, None}
        )
        if code in _PADDLE_JOBS_QUOTA_CODES or response.status_code == 429 or (
            (response.status_code in {401, 403} or is_business_error)
            and is_quota_error
        ):
            raise RuntimeError(
                f"PaddleOCR quota or rate limit exceeded: {safe_message}"
            )
        if (
            response.status_code in {401, 403} or is_business_error
        ) and is_auth_error:
            raise RuntimeError(
                "PaddleOCR authentication failed: "
                f"{self._safe_paddle_detail(message, fallback='access token rejected')}"
            )
        if response.status_code == 400 or (
            is_business_error and is_invalid_request_error
        ):
            raise RuntimeError(f"PaddleOCR invalid request: {safe_message}")
        if response.status_code in {503, 504} or (
            is_business_error and is_service_unavailable_error
        ):
            raise RuntimeError(f"PaddleOCR service unavailable: {safe_message}")
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"PaddleOCR {operation} failed (HTTP {response.status_code}): "
                f"{safe_message}"
            )
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"PaddleOCR {operation} response must be a JSON object")
        if code not in {0, None}:
            raise RuntimeError(
                f"PaddleOCR {operation} failed (code {code}): "
                f"{safe_message}"
            )
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise RuntimeError(
                f"PaddleOCR {operation} response is missing object field data"
            )
        return data

    def _safe_paddle_detail(
        self,
        value: Any,
        *,
        fallback: str = "provider error",
    ) -> str:
        """Return a bounded provider detail with credential-shaped values removed."""

        detail = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        api_key = self._api_key()
        if api_key:
            detail = detail.replace(api_key, "[REDACTED]")
        detail = _PADDLE_AUTHORIZATION_DETAIL_RE.sub(
            lambda match: f"{match.group(1)}[REDACTED]",
            detail,
        )
        detail = _PADDLE_SECRET_DETAIL_RE.sub(
            lambda match: f"{match.group(1)}[REDACTED]",
            detail,
        )
        normalized = detail or fallback
        return normalized[:_PADDLE_ERROR_DETAIL_MAX_CHARS]

    def _paddle_jsonl_result(
        self,
        payload: str,
        *,
        image_size: tuple[int, int] | None,
    ) -> OcrImageResult:
        """Parse PaddleOCR JSONL while retaining trustworthy original-image regions."""

        fragments: list[str] = []
        regions: list[OcrImageRegion] = []
        allow_regions = self._paddle_regions_are_trustworthy(image_size)
        for line_number, raw_line in enumerate(payload.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"PaddleOCR result JSONL line {line_number} is invalid"
                ) from exc
            if not isinstance(item, Mapping):
                raise RuntimeError(
                    f"PaddleOCR result JSONL line {line_number} must be an object"
                )
            result = item.get("result")
            if not isinstance(result, Mapping):
                raise RuntimeError(
                    f"PaddleOCR result JSONL line {line_number} is missing result"
                )
            layout_results = result.get("layoutParsingResults")
            ocr_results = result.get("ocrResults")
            model = self._model()
            if model in _PADDLE_DOCUMENT_RESULT_MODELS and not isinstance(
                layout_results, list
            ):
                raise RuntimeError(
                    "PaddleOCR result JSONL line "
                    f"{line_number} is missing list field layoutParsingResults"
                )
            if model in _PADDLE_OCR_RESULT_MODELS and not isinstance(
                ocr_results, list
            ):
                raise RuntimeError(
                    "PaddleOCR result JSONL line "
                    f"{line_number} is missing list field ocrResults"
                )
            if (
                model not in _PADDLE_DOCUMENT_RESULT_MODELS
                and model not in _PADDLE_OCR_RESULT_MODELS
                and not isinstance(layout_results, list)
                and not isinstance(ocr_results, list)
            ):
                raise RuntimeError(
                    "PaddleOCR result JSONL line "
                    f"{line_number} has no supported result list"
                )
            layout_fragments, layout_regions = self._paddle_layout_content(
                layout_results,
                image_size=image_size if allow_regions else None,
            )
            if layout_fragments:
                fragments.extend(layout_fragments)
                regions.extend(layout_regions)
                continue
            ocr_fragments, ocr_regions = self._paddle_ocr_content(
                ocr_results,
                image_size=image_size if allow_regions else None,
            )
            fragments.extend(ocr_fragments)
            regions.extend(ocr_regions)
        return OcrImageResult(text="\n".join(fragments), regions=tuple(regions))

    def _paddle_jsonl_text(self, payload: str) -> str:
        """Retain the pre-structured internal parser contract for callers in flight."""

        return self._paddle_jsonl_result(payload, image_size=None).text

    def _paddle_layout_content(
        self,
        raw_layout_results: Any,
        *,
        image_size: tuple[int, int] | None,
    ) -> tuple[list[str], list[OcrImageRegion]]:
        """Prefer located document blocks, falling back to page Markdown."""

        if not isinstance(raw_layout_results, list):
            return [], []
        block_fragments: list[str] = []
        block_regions: list[OcrImageRegion] = []
        markdown_fragments: list[str] = []
        for layout in raw_layout_results:
            if not isinstance(layout, Mapping):
                continue
            markdown = layout.get("markdown")
            if isinstance(markdown, Mapping):
                markdown_text = markdown.get("text")
                if isinstance(markdown_text, str) and markdown_text.strip():
                    markdown_fragments.append(markdown_text.strip())
            pruned_result = layout.get("prunedResult")
            if not isinstance(pruned_result, Mapping):
                continue
            raw_blocks = pruned_result.get("parsing_res_list")
            if not isinstance(raw_blocks, list):
                continue
            for raw_block in raw_blocks:
                if not isinstance(raw_block, Mapping):
                    continue
                content = raw_block.get("block_content")
                if not isinstance(content, str) or not content.strip():
                    continue
                text = content.strip()
                block_fragments.append(text)
                raw_label = raw_block.get("block_label")
                label = raw_label.strip().casefold() if isinstance(raw_label, str) else ""
                block_type = _PADDLE_BLOCK_TYPES.get(label, "Text")
                region = self._paddle_region(
                    text,
                    raw_block.get("block_bbox"),
                    block_type=block_type,
                    image_size=image_size,
                )
                if region is not None:
                    block_regions.append(region)
        if block_fragments:
            return block_fragments, block_regions
        return markdown_fragments, []

    def _paddle_ocr_content(
        self,
        raw_ocr_results: Any,
        *,
        image_size: tuple[int, int] | None,
    ) -> tuple[list[str], list[OcrImageRegion]]:
        """Read OCR lines and retain only boxes valid for the uploaded image."""

        if not isinstance(raw_ocr_results, list):
            return [], []
        fragments: list[str] = []
        regions: list[OcrImageRegion] = []
        for raw_ocr_result in raw_ocr_results:
            if not isinstance(raw_ocr_result, Mapping):
                continue
            pruned_result = raw_ocr_result.get("prunedResult")
            if not isinstance(pruned_result, Mapping):
                continue
            raw_texts = pruned_result.get("rec_texts")
            raw_boxes = pruned_result.get("rec_boxes")
            if not isinstance(raw_texts, list):
                fallback_text = _extract_paddleocr_text(pruned_result).strip()
                if fallback_text:
                    fragments.append(fallback_text)
                continue
            boxes = raw_boxes if isinstance(raw_boxes, list) else []
            for index, raw_text in enumerate(raw_texts):
                if not isinstance(raw_text, str) or not raw_text.strip():
                    continue
                text = raw_text.strip()
                fragments.append(text)
                raw_bbox = boxes[index] if index < len(boxes) else None
                region = self._paddle_region(
                    text,
                    raw_bbox,
                    block_type="Text",
                    image_size=image_size,
                )
                if region is not None:
                    regions.append(region)
        return fragments, regions

    def _paddle_regions_are_trustworthy(
        self,
        image_size: tuple[int, int] | None,
    ) -> bool:
        """Reject exact locators when Paddle may transform the source geometry."""

        if image_size is None:
            return False
        extra_payload = self.config.get("extra_payload")
        if not isinstance(extra_payload, Mapping):
            return True
        for flag_name in ("useDocOrientationClassify", "useDocUnwarping"):
            value = extra_payload.get(flag_name)
            if value is True or (
                isinstance(value, str)
                and value.strip().casefold() in {"1", "true", "yes", "on"}
            ):
                return False
        return True

    def _paddle_region(
        self,
        text: str,
        raw_bbox: Any,
        *,
        block_type: str,
        image_size: tuple[int, int] | None,
    ) -> OcrImageRegion | None:
        """Convert one original-image ``xyxy`` box to normalized ``xywh``."""

        if image_size is None or not isinstance(raw_bbox, (list, tuple)):
            return None
        if len(raw_bbox) != 4:
            return None
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in raw_bbox
        ):
            return None
        x0, y0, x1, y1 = (float(value) for value in raw_bbox)
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            return None
        width, height = image_size
        if (
            x0 < 0.0
            or y0 < 0.0
            or x1 <= x0
            or y1 <= y0
            or x1 > float(width)
            or y1 > float(height)
        ):
            return None
        return OcrImageRegion(
            markdown=text,
            bbox=(
                x0 / width,
                y0 / height,
                (x1 - x0) / width,
                (y1 - y0) / height,
            ),
            block_type=block_type,
        )

    def _extract_response_text(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if not isinstance(payload, Mapping):
            raise RuntimeError("remote OCR response must contain a JSON object")

        configured_path = str(self.config.get("response_text_path") or "").strip()
        if configured_path:
            found = self._value_at_path(payload, configured_path)
            if found is not None:
                return self._coerce_text(found)

        for path in (
            "text",
            "content",
            "markdown",
            "data.text",
            "data.content",
            "data.markdown",
            "result.text",
            "result.content",
            "result.markdown",
            "pages.markdown",
            "pages.text",
            "pages.0.text",
            "pages.0.markdown",
        ):
            found = self._value_at_path(payload, path)
            if found is not None:
                text = self._coerce_text(found).strip()
                if text:
                    return text
        raise RuntimeError("remote OCR response did not include text")

    def _value_at_path(self, payload: Mapping[str, Any], path: str) -> Any:
        current: Any = payload
        for segment in path.split("."):
            if isinstance(current, Mapping):
                current = current.get(segment)
            elif isinstance(current, list):
                if segment in {"text", "markdown", "content"}:
                    collected = []
                    for item in current:
                        if isinstance(item, Mapping) and item.get(segment) is not None:
                            collected.append(item[segment])
                    return collected if collected else None
                try:
                    index = int(segment)
                except ValueError:
                    return None
                if index < 0 or index >= len(current):
                    return None
                current = current[index]
            else:
                return None
            if current is None:
                return None
        return current

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(self._coerce_text(item).strip() for item in value).strip()
        return str(value)
