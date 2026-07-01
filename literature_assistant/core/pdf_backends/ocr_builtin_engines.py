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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import httpx

from .ocr_engine import OcrEngineHealth, OcrReadinessStatus


_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*$")
_DEFAULT_WINDOWS_OCR_TIMEOUT_SECONDS = 90
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
        api_key = self._api_key()
        base_url = self._base_url()
        if api_key and base_url and not self._allow_remote_upload():
            return "remote OCR requires explicit allow_remote_upload=true consent"
        if api_key and base_url:
            try:
                provider = self._provider()
                self._validated_base_url()
                self._endpoint_path()
                self._timeout_seconds()
            except (TypeError, ValueError) as exc:
                return str(exc)
            if provider == "mineru":
                return (
                    "MinerU uses asynchronous document parsing; configure it as "
                    "an OCR credential, but do not select it for page-level OCR."
                )
            return None
        return "remote OCR requires explicit api_key and base_url configuration"

    def readiness_status(self) -> OcrReadinessStatus:
        reason = self.unavailable_reason()
        if reason is None:
            return "ready"
        if "asynchronous document parsing" in reason:
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
        if provider == "mistral":
            payload = self._mistral_request_payload(image_bytes)
            response = self._post_ocr_payload(payload, provider=provider)
        else:
            payload = self._request_payload(image_bytes, language=language_tag)
            response = self._post_ocr_payload(payload, provider=provider)
        return self._extract_response_text(response).strip()

    def _provider(self) -> str:
        raw = str(self.config.get("provider") or "generic").strip().lower()
        if raw in {"", "custom"}:
            return "generic"
        if raw not in _REMOTE_OCR_PROVIDER_DEFAULTS:
            raise ValueError("remote OCR provider must be one of: generic, mistral, mineru")
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
        if timeout < 5:
            raise ValueError("remote OCR timeout_seconds must be at least 5")
        if timeout > 600:
            raise ValueError("remote OCR timeout_seconds must be 600 or fewer")
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
        url = urljoin(self._validated_base_url(), self._endpoint_path().lstrip("/"))
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
