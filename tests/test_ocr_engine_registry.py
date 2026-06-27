# -*- coding: utf-8 -*-
"""Tests for OCR engine registry and auto policy contracts."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Mapping

import httpx
import pytest

_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends import (  # noqa: E402
    OcrEngine,
    OcrEngineHealth,
    OcrRuntimeConfig,
    clear_ocr_engines_for_tests,
    list_ocr_engine_names,
    public_ocr_status,
    register_ocr_engine,
    resolve_ocr_runtime_config,
    select_ocr_engine,
    write_ocr_runtime_config,
)
from pdf_backends import ocr_builtin_engines  # noqa: E402
from pdf_backends.ocr_builtin_engines import (  # noqa: E402
    PaddleOcrGpuEngine,
    RapidOcrEngine,
    RemoteApiOcrEngine,
    WindowsOcrEngine,
)


class _MockOcrEngine:
    name = "mock"
    display_name = "Mock OCR"
    engine_type = "local"
    requires_network = False

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def is_available(self) -> bool:
        return bool(self.config.get("available", True))

    def unavailable_reason(self) -> str | None:
        return None if self.is_available() else "mock unavailable"

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        return f"mock text {language}"

    def health_check(self) -> OcrEngineHealth:
        return OcrEngineHealth(ok=self.is_available(), detail="mock", engine=self.name)


class _LegacyOcrEngine:
    """Engine shape that predates readiness methods."""

    name = "legacy"
    display_name = "Legacy OCR"
    engine_type = "local"
    requires_network = False

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str | None:
        return None

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        return "legacy text"

    def health_check(self) -> OcrEngineHealth:
        return OcrEngineHealth(ok=True, detail="legacy", engine=self.name)


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_ocr_engines_for_tests()
    monkeypatch.delenv("LITASSIST_OCR_POLICY", raising=False)
    monkeypatch.delenv("LITASSIST_OCR_ENGINE", raising=False)
    monkeypatch.delenv("LITASSIST_OCR_LANG", raising=False)
    monkeypatch.delenv("LITASSIST_PADDLEOCR_PYTHON", raising=False)
    monkeypatch.delenv("LITASSIST_RAPIDOCR_PYTHON", raising=False)
    yield
    clear_ocr_engines_for_tests()


def test_default_ocr_policy_is_auto_and_does_not_require_configured_engine(
    tmp_path: Path,
) -> None:
    config = resolve_ocr_runtime_config(config_path=tmp_path / "missing.json")

    assert config.policy == "auto"
    assert config.engine is None
    assert config.language == "en"
    engine, warning = select_ocr_engine(config)
    if engine is None:
        assert warning == "OCR policy is auto but no available OCR engine was found"
    else:
        assert warning is None
        assert engine.name in {"paddleocr_gpu", "rapidocr", "windows", "remote_api"}


def test_builtin_heavy_and_remote_engines_report_readiness_without_secret_leakage() -> None:
    status = public_ocr_status(OcrRuntimeConfig(policy="auto"))
    unavailable_by_name = {
        item["name"]: item["unavailable_reason"] for item in status["available_engines"]
    }
    readiness_by_name = {
        item["name"]: item["readiness_status"] for item in status["available_engines"]
    }
    blockers_by_name = {
        item["name"]: item["readiness_blockers"] for item in status["available_engines"]
    }
    actions_by_name = {
        item["name"]: item["next_safe_local_actions"] for item in status["available_engines"]
    }

    if status["selected_engine"] is None:
        assert status["warning"] == "OCR policy is auto but no available OCR engine was found"
        assert status["next_safe_local_actions"]
    else:
        assert status["selected_engine"] == "windows"
        assert status["warning"] is None
        assert any("ocr_health" in action for action in status["next_safe_local_actions"])
    assert unavailable_by_name["remote_api"] == (
        "remote OCR requires explicit api_key and base_url configuration"
    )
    assert readiness_by_name["remote_api"] == "configuration_required"
    assert blockers_by_name["remote_api"] == [
        "remote OCR requires explicit api_key and base_url configuration"
    ]
    assert any("api_key" in action for action in actions_by_name["remote_api"])
    assert readiness_by_name["paddleocr_gpu"] in {"dependency_missing", "adapter_not_wired"}
    assert readiness_by_name["rapidocr"] in {"dependency_missing", "adapter_not_wired"}
    assert readiness_by_name["windows"] in {
        "ready",
        "dependency_missing",
        "platform_unsupported",
    }


def test_ocr_engine_protocol_requires_readiness_contract() -> None:
    engine = _LegacyOcrEngine()

    assert not isinstance(engine, OcrEngine)


def test_unavailable_configured_engine_returns_warning() -> None:
    engine, warning = select_ocr_engine(
        OcrRuntimeConfig(policy="engine", engine="remote_api", engine_config={})
    )

    assert engine is None
    assert warning == "remote OCR requires explicit api_key and base_url configuration"


def test_configured_remote_api_credentials_still_require_upload_consent() -> None:
    engine, warning = select_ocr_engine(
        OcrRuntimeConfig(
            policy="engine",
            engine="remote_api",
            engine_config={
                "api_key": "secret-value",
                "base_url": "https://ocr.example.test",
            },
        )
    )

    assert engine is None
    assert warning == "remote OCR requires explicit allow_remote_upload=true consent"

    status = public_ocr_status(
        OcrRuntimeConfig(
            policy="engine",
            engine="remote_api",
            engine_config={
                "api_key": "secret-value",
                "base_url": "https://ocr.example.test",
            },
        )
    )
    remote = next(item for item in status["available_engines"] if item["name"] == "remote_api")
    assert remote["available"] is False
    assert remote["readiness_status"] == "configuration_required"
    assert remote["readiness_blockers"] == [
        "remote OCR requires explicit allow_remote_upload=true consent"
    ]


def test_remote_api_adapter_runs_only_with_explicit_upload_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> httpx.Response:
            requests.append(
                {
                    "url": url,
                    "json": dict(json),
                    "headers": dict(headers),
                    "timeout": self.timeout,
                    "follow_redirects": self.follow_redirects,
                }
            )
            return httpx.Response(
                200,
                json={"data": {"text": "recognized remote text"}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "api_key": "secret-value",
            "base_url": "https://ocr.example.test/api",
            "endpoint_path": "/v1/ocr",
            "allow_remote_upload": True,
            "timeout_seconds": 12,
        }
    )

    health = engine.health_check()
    text = engine.ocr_image(b"image-bytes", language="en")

    assert engine.is_available() is True
    assert engine.readiness_status() == "ready"
    assert health.ok is True
    assert health.readiness_status == "ready"
    assert text == "recognized remote text"
    assert requests == [
        {
            "url": "https://ocr.example.test/api/v1/ocr",
            "json": {"image_base64": "aW1hZ2UtYnl0ZXM=", "language": "en"},
            "headers": {
                "Authorization": "Bearer secret-value",
                "Accept": "application/json",
            },
            "timeout": 12.0,
            "follow_redirects": False,
        }
    ]


def test_remote_api_health_check_does_not_create_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines.httpx,
        "Client",
        lambda *_args, **_kwargs: pytest.fail("health check must not upload or probe content"),
    )
    engine = RemoteApiOcrEngine(
        {
            "api_key": "secret-value",
            "base_url": "https://ocr.example.test",
            "allow_remote_upload": True,
        }
    )

    health = engine.health_check()

    assert health.ok is True
    assert "upload only when OCR execution is requested" in health.detail


def test_paddleocr_status_and_health_do_not_import_heavy_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "paddleocr" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"status/health must not import {name}"),
    )

    status = public_ocr_status(OcrRuntimeConfig(policy="engine", engine="paddleocr_gpu"))
    engine = PaddleOcrGpuEngine()
    health = engine.health_check()

    paddle = next(item for item in status["available_engines"] if item["name"] == "paddleocr_gpu")
    assert status["selected_engine"] == "paddleocr_gpu"
    assert paddle["available"] is True
    assert paddle["readiness_status"] == "ready"
    assert paddle["readiness_blockers"] == []
    assert health.ok is True
    assert health.readiness_status == "ready"


def test_paddleocr_status_can_use_configured_external_python_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_executable = tmp_path / "python.exe"
    python_executable.write_bytes(b"stub")
    calls: list[dict[str, Any]] = []

    def _fake_external_python_json(
        executable: Path,
        script: str,
        *,
        timeout_seconds: int,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        calls.append(
            {
                "executable": executable,
                "timeout_seconds": timeout_seconds,
                "payload": dict(payload or {}),
                "is_probe": "find_spec" in script,
            }
        )
        return {"paddleocr_present": True, "paddle_present": True}

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_run_external_python_json",
        _fake_external_python_json,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"external status must not import {name} in active runtime"),
    )

    status = public_ocr_status(
        OcrRuntimeConfig(
            policy="engine",
            engine="paddleocr_gpu",
            engine_config={"python_executable": str(python_executable)},
        )
    )
    engine = PaddleOcrGpuEngine({"python_executable": str(python_executable)})
    health = engine.health_check()

    paddle = next(item for item in status["available_engines"] if item["name"] == "paddleocr_gpu")
    assert status["selected_engine"] == "paddleocr_gpu"
    assert paddle["available"] is True
    assert paddle["readiness_status"] == "ready"
    assert health.ok is True
    assert health.detail == "available via external Python runtime"
    assert calls
    assert all(call["executable"] == python_executable.resolve() for call in calls)
    assert all(call["payload"] == {} for call in calls)


def test_paddleocr_external_python_execution_uses_subprocess_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_executable = tmp_path / "python.exe"
    image_path = tmp_path / "page.png"
    python_executable.write_bytes(b"stub")
    image_path.write_bytes(b"png")
    calls: list[dict[str, Any]] = []

    def _fake_external_python_json(
        executable: Path,
        script: str,
        *,
        timeout_seconds: int,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        payload_dict = dict(payload or {})
        calls.append(
            {
                "executable": executable,
                "timeout_seconds": timeout_seconds,
                "payload": payload_dict,
                "is_execution": "PaddleOCR" in script,
            }
        )
        return {"text": "external paddle text"}

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_run_external_python_json",
        _fake_external_python_json,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"external execution must not import {name} in active runtime"),
    )

    engine = PaddleOcrGpuEngine(
        {
            "python_executable": str(python_executable),
            "constructor_kwargs": {"device": "gpu:0"},
            "method_kwargs": {"use_doc_orientation_classify": False},
            "runtime_method": "predict",
            "timeout_seconds": 42,
        }
    )

    text = engine.ocr_image(image_path, language="en")

    assert text == "external paddle text"
    assert calls == [
        {
            "executable": python_executable.resolve(),
            "timeout_seconds": 42,
            "payload": {
                "image_path": str(image_path),
                "constructor_kwargs": {"device": "gpu:0"},
                "method_kwargs": {"use_doc_orientation_classify": False},
                "runtime_method": "predict",
            },
            "is_execution": True,
        }
    ]


def test_paddleocr_external_python_missing_exposes_readiness_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_python = tmp_path / "missing-python.exe"
    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: None,
    )

    engine = PaddleOcrGpuEngine({"python_executable": str(missing_python)})
    health = engine.health_check()

    assert engine.is_available() is False
    assert engine.readiness_status() == "dependency_missing"
    assert health.ok is False
    assert health.readiness_status == "dependency_missing"
    assert "external PaddleOCR Python is unavailable" in health.detail
    assert str(missing_python.resolve()) in health.detail


def test_rapidocr_status_can_use_configured_external_python_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_executable = tmp_path / "python.exe"
    python_executable.write_bytes(b"stub")
    calls: list[dict[str, Any]] = []

    def _fake_external_python_json(
        executable: Path,
        script: str,
        *,
        timeout_seconds: int,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        calls.append(
            {
                "executable": executable,
                "timeout_seconds": timeout_seconds,
                "payload": dict(payload or {}),
                "is_rapidocr": "rapidocr_onnxruntime" in script,
            }
        )
        return {"rapidocr_present": True, "rapidocr_onnxruntime_present": False}

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_run_external_python_json",
        _fake_external_python_json,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"external status must not import {name} in active runtime"),
    )

    status = public_ocr_status(
        OcrRuntimeConfig(
            policy="engine",
            engine="rapidocr",
            engine_config={"python_executable": str(python_executable)},
        )
    )
    engine = RapidOcrEngine({"python_executable": str(python_executable)})
    health = engine.health_check()

    rapid = next(item for item in status["available_engines"] if item["name"] == "rapidocr")
    assert status["selected_engine"] == "rapidocr"
    assert rapid["available"] is True
    assert rapid["readiness_status"] == "ready"
    assert health.ok is True
    assert health.detail == "available via external Python runtime"
    assert calls
    assert all(call["executable"] == python_executable.resolve() for call in calls)
    assert all(call["payload"] == {} for call in calls)
    assert any(call["is_rapidocr"] is True for call in calls)


def test_rapidocr_external_python_execution_uses_subprocess_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_executable = tmp_path / "python.exe"
    image_path = tmp_path / "page.png"
    python_executable.write_bytes(b"stub")
    image_path.write_bytes(b"png")
    calls: list[dict[str, Any]] = []

    def _fake_external_python_json(
        executable: Path,
        script: str,
        *,
        timeout_seconds: int,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        payload_dict = dict(payload or {})
        calls.append(
            {
                "executable": executable,
                "timeout_seconds": timeout_seconds,
                "payload": payload_dict,
                "is_execution": "RapidOCR" in script,
            }
        )
        return {"text": "external rapid text"}

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_run_external_python_json",
        _fake_external_python_json,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"external execution must not import {name} in active runtime"),
    )

    engine = RapidOcrEngine(
        {
            "python_executable": str(python_executable),
            "constructor_kwargs": {"det_model_path": "local-det.onnx"},
            "timeout_seconds": 41,
        }
    )

    text = engine.ocr_image(image_path, language="en")

    assert text == "external rapid text"
    assert calls == [
        {
            "executable": python_executable.resolve(),
            "timeout_seconds": 41,
            "payload": {
                "image_path": str(image_path),
                "constructor_kwargs": {"det_model_path": "local-det.onnx"},
            },
            "is_execution": True,
        }
    ]


def test_rapidocr_external_python_missing_exposes_readiness_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_python = tmp_path / "missing-python.exe"
    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: None,
    )

    engine = RapidOcrEngine({"python_executable": str(missing_python)})
    health = engine.health_check()

    assert engine.is_available() is False
    assert engine.readiness_status() == "dependency_missing"
    assert health.ok is False
    assert health.readiness_status == "dependency_missing"
    assert "external RapidOCR Python is unavailable" in health.detail
    assert str(missing_python.resolve()) in health.detail


def test_paddleocr_engine_runs_lazy_optional_adapter_with_v3_result_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor_calls: list[dict[str, Any]] = []
    predict_calls: list[dict[str, Any]] = []

    class _FakePaddleOCR:
        def __init__(self, **kwargs: Any) -> None:
            constructor_calls.append(dict(kwargs))

        def predict(self, image_path: str, **kwargs: Any) -> dict[str, list[str]]:
            predict_calls.append({"image_path": image_path, "kwargs": dict(kwargs)})
            return {"rec_texts": ["alpha text", "beta text"]}

    fake_module = types.SimpleNamespace(PaddleOCR=_FakePaddleOCR)
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"png")

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "paddleocr" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: fake_module if name == "paddleocr" else pytest.fail(name),
    )

    engine = PaddleOcrGpuEngine(
        {
            "constructor_kwargs": {"device": "gpu:0"},
            "method_kwargs": {"use_doc_orientation_classify": False},
        }
    )
    health = engine.health_check()
    text = engine.ocr_image(image_path, language="en")

    assert engine.is_available() is True
    assert engine.readiness_status() == "ready"
    assert health.ok is True
    assert health.readiness_status == "ready"
    assert constructor_calls == [{"device": "gpu:0"}]
    assert predict_calls == [
        {
            "image_path": str(image_path),
            "kwargs": {"use_doc_orientation_classify": False},
        }
    ]
    assert text == "alpha text\nbeta text"


def test_paddleocr_engine_reads_v2_line_shape_from_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_calls: list[str] = []

    class _FakePaddleOCR:
        def ocr(self, image_path: str) -> list[list[Any]]:
            runtime_calls.append(image_path)
            assert Path(image_path).is_file()
            return [
                [[[0, 0], [10, 0], [10, 10], [0, 10]], ("gamma text", 0.99)],
                [[[0, 12], [10, 12], [10, 20], [0, 20]], ("delta text", 0.98)],
            ]

    fake_module = types.SimpleNamespace(PaddleOCR=lambda **_kwargs: _FakePaddleOCR())

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "paddleocr" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: fake_module if name == "paddleocr" else pytest.fail(name),
    )

    engine = PaddleOcrGpuEngine({"runtime_method": "ocr"})
    text = engine.ocr_image(b"png", language="en")

    assert len(runtime_calls) == 1
    assert not Path(runtime_calls[0]).exists()
    assert text == "gamma text\ndelta text"


def test_paddleocr_engine_rejects_invalid_config_without_model_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "paddleocr" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"invalid config must fail before importing {name}"),
    )

    bad_constructor = PaddleOcrGpuEngine({"constructor_kwargs": ["bad"]})
    bad_method = PaddleOcrGpuEngine({"method_kwargs": ["bad"]})
    bad_runtime_method = PaddleOcrGpuEngine({"runtime_method": "bad"})

    with pytest.raises(ValueError, match="constructor_kwargs"):
        bad_constructor.ocr_image(b"png", language="en")
    with pytest.raises(ValueError, match="method_kwargs"):
        bad_method.ocr_image(b"png", language="en")
    with pytest.raises(ValueError, match="runtime_method"):
        bad_runtime_method.ocr_image(b"png", language="en")


def test_rapidocr_engine_runs_lazy_optional_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor_calls: list[dict[str, Any]] = []
    runtime_calls: list[str] = []

    class _FakeRapidOCR:
        def __init__(self, **kwargs: Any) -> None:
            constructor_calls.append(dict(kwargs))

        def __call__(self, image_path: str) -> tuple[list[list[Any]], float]:
            runtime_calls.append(image_path)
            return (
                [
                    [[[0, 0], [10, 0], [10, 10], [0, 10]], "alpha text", 0.99],
                    [[[0, 12], [10, 12], [10, 20], [0, 20]], "beta text", 0.98],
                ],
                1.25,
            )

    fake_module = types.SimpleNamespace(RapidOCR=_FakeRapidOCR)
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"png")

    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "rapidocr" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: fake_module if name == "rapidocr" else pytest.fail(name),
    )

    engine = RapidOcrEngine({"constructor_kwargs": {"det_model_path": "local-det.onnx"}})
    health = engine.health_check()
    text = engine.ocr_image(image_path, language="en")

    assert engine.is_available() is True
    assert engine.readiness_status() == "ready"
    assert health.ok is True
    assert health.readiness_status == "ready"
    assert constructor_calls == [{"det_model_path": "local-det.onnx"}]
    assert runtime_calls == [str(image_path)]
    assert text == "alpha text\nbeta text"


def test_rapidocr_engine_rejects_invalid_constructor_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "rapidocr" else None,
    )

    engine = RapidOcrEngine({"constructor_kwargs": ["bad"]})

    with pytest.raises(ValueError, match="constructor_kwargs"):
        engine.ocr_image(b"png", language="en")


def test_rapidocr_engine_rejects_empty_image_before_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines.importlib.util,
        "find_spec",
        lambda name: object() if name == "rapidocr" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.importlib,
        "import_module",
        lambda name: pytest.fail(f"empty image must fail before importing {name}"),
    )
    empty_path = tmp_path / "empty.png"
    empty_path.write_bytes(b"")

    engine = RapidOcrEngine()

    with pytest.raises(ValueError, match="RapidOCR image bytes must be non-empty"):
        engine.ocr_image(b"", language="en")
    with pytest.raises(ValueError, match="RapidOCR image file must be non-empty"):
        engine.ocr_image(empty_path, language="en")


def test_env_policy_overrides_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = write_ocr_runtime_config(
        OcrRuntimeConfig(policy="none", language="zh"),
        config_path=tmp_path / "ocr_config.json",
    )
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "auto")
    monkeypatch.setenv("LITASSIST_OCR_LANG", "en")

    config = resolve_ocr_runtime_config(config_path=config_path)

    assert config.policy == "auto"
    assert config.language == "en"
    assert config.source == "env"


def test_auto_policy_selects_registered_available_engine() -> None:
    register_ocr_engine("mock", lambda config: _MockOcrEngine(config))

    names = list_ocr_engine_names(include_builtins=False)
    engine, warning = select_ocr_engine(
        OcrRuntimeConfig(policy="auto", engine="mock", engine_config={"available": True})
    )

    assert names == ["mock"]
    assert warning is None
    assert engine is not None
    assert engine.ocr_image(b"image", language="en") == "mock text en"


def test_public_status_redacts_engine_config_secrets() -> None:
    register_ocr_engine("mock", lambda config: _MockOcrEngine(config))

    status = public_ocr_status(
        OcrRuntimeConfig(
            policy="engine",
            engine="mock",
            engine_config={"api_key": "secret-value", "base_url": "https://example.test"},
        )
    )

    assert status["policy"] == "engine"
    assert status["selected_engine"] == "mock"
    assert status["engine_config"]["api_key"] == "***"
    assert status["engine_config"]["base_url"] == "https://example.test"


def test_windows_ocr_engine_runs_local_powershell_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, str]] = []
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"png")

    monkeypatch.setattr(ocr_builtin_engines.sys, "platform", "win32")
    monkeypatch.setattr(
        ocr_builtin_engines.shutil,
        "which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )

    def _fake_run(script: str, *, timeout_seconds: int, executable: str) -> str:
        calls.append((script, timeout_seconds, executable))
        return "recognized text" if "RecognizeAsync" in script else "available"

    monkeypatch.setattr(ocr_builtin_engines, "_run_powershell_script", _fake_run)

    engine = WindowsOcrEngine({"timeout_seconds": 12, "language": "en-US"})
    health = engine.health_check()
    text = engine.ocr_image(image_path, language="en-US")

    assert engine.is_available() is True
    assert engine.readiness_status() == "ready"
    assert health.ok is True
    assert health.readiness_status == "ready"
    assert text == "recognized text"
    assert len(calls) == 2
    assert calls[0][1] == 12
    assert calls[0][2] == "powershell.exe"
    assert "Windows.Media.Ocr.OcrEngine" in calls[0][0]
    assert "TryCreateFromLanguage" in calls[0][0]
    assert str(image_path) in calls[1][0]
    assert "RecognizeAsync" in calls[1][0]


def test_windows_ocr_engine_rejects_invalid_language_without_running_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocr_builtin_engines.sys, "platform", "win32")
    monkeypatch.setattr(
        ocr_builtin_engines.shutil,
        "which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_run_powershell_script",
        lambda *_args, **_kwargs: pytest.fail("invalid language must fail before PowerShell"),
    )

    engine = WindowsOcrEngine()

    with pytest.raises(ValueError, match="invalid OCR language tag"):
        engine.ocr_image(b"image", language="../bad")


def test_windows_ocr_engine_rejects_empty_image_without_running_powershell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocr_builtin_engines.sys, "platform", "win32")
    monkeypatch.setattr(
        ocr_builtin_engines.shutil,
        "which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_run_powershell_script",
        lambda *_args, **_kwargs: pytest.fail("empty image must fail before PowerShell"),
    )
    empty_path = tmp_path / "empty.png"
    empty_path.write_bytes(b"")

    engine = WindowsOcrEngine()

    with pytest.raises(ValueError, match="Windows OCR image bytes must be non-empty"):
        engine.ocr_image(b"", language="en")
    with pytest.raises(ValueError, match="Windows OCR image file must be non-empty"):
        engine.ocr_image(empty_path, language="en")
