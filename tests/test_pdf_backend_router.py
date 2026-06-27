# -*- coding: utf-8 -*-
"""Tests for the core PDF backend status endpoint."""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends import (  # noqa: E402
    ENV_VAR,
    OcrEngineHealth,
    clear_ocr_engines_for_tests,
    get_pdf_backend,
    register_ocr_engine,
)
from pdf_backends import ocr_builtin_engines  # noqa: E402
from python_adapter_server import app, get_local_api_capability_token  # noqa: E402
from routers.pdf_backend_router import (  # noqa: E402
    OcrEngineSelectionRequest,
    OcrExecutionProbeRequest,
    OcrHealthRequest,
    _resolve_active_backend,
    get_pdf_backend_status,
    get_ocr_status,
    list_ocr_engines,
    run_ocr_execution_probe,
    select_ocr_engine_endpoint,
    check_ocr_engine_health,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.delenv("LITASSIST_OCR_POLICY", raising=False)
    monkeypatch.delenv("LITASSIST_OCR_ENGINE", raising=False)
    monkeypatch.delenv("LITASSIST_OCR_LANG", raising=False)
    monkeypatch.delenv("LITASSIST_OCR_CONFIG_PATH", raising=False)
    monkeypatch.delenv("LITASSIST_PADDLEOCR_PYTHON", raising=False)
    monkeypatch.delenv("LITASSIST_RAPIDOCR_PYTHON", raising=False)
    clear_ocr_engines_for_tests()
    yield
    clear_ocr_engines_for_tests()


class _MockLocalOcrEngine:
    """Small local OCR engine used to prove execution without optional deps."""

    name = "mock_local"
    display_name = "Mock Local OCR"
    engine_type = "local"
    requires_network = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def is_available(self) -> bool:
        return self.config.get("available", True) is True

    def unavailable_reason(self) -> str | None:
        return None if self.is_available() else "mock local OCR disabled"

    def readiness_status(self) -> str:
        return "ready" if self.is_available() else "unavailable"

    def readiness_blockers(self) -> tuple[str, ...]:
        reason = self.unavailable_reason()
        return () if reason is None else (reason,)

    def health_check(self) -> OcrEngineHealth:
        return OcrEngineHealth(
            ok=self.is_available(),
            detail="available" if self.is_available() else "mock local OCR disabled",
            engine=self.name,
            readiness_status="ready" if self.is_available() else "unavailable",
            readiness_blockers=self.readiness_blockers(),
        )

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        image_bytes = image.read_bytes() if isinstance(image, Path) else image
        suffix = str(self.config.get("suffix") or "").strip()
        return f"mock text {language} bytes={len(image_bytes)} {suffix}".strip()


def _register_mock_local_ocr() -> None:
    register_ocr_engine("mock_local", lambda config: _MockLocalOcrEngine(dict(config)))


def test_default_backend_is_pymupdf() -> None:
    backend, source = _resolve_active_backend()
    assert backend == "pymupdf"
    assert source == "default"
    assert get_pdf_backend().name == "pymupdf"


@pytest.mark.parametrize("raw_value", ["marker", "pymupdf", "auto", "unknown"])
def test_env_var_no_longer_selects_external_backend(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv(ENV_VAR, raw_value)
    backend, source = _resolve_active_backend()
    assert backend == "pymupdf"
    assert source == "env"
    assert get_pdf_backend().name == "pymupdf"


def test_status_payload_shape() -> None:
    payload = get_pdf_backend_status()
    assert payload.active_backend == "pymupdf"
    assert payload.active_source == "default"
    assert payload.env_var_name == ENV_VAR
    assert payload.env_var_value is None
    assert payload.external_backends_supported is True
    assert "optional local providers" in payload.install_hint
    assert payload.ocr_policy == "auto"
    assert payload.ocr_language == "en"


def test_status_reports_env_var_value_without_changing_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "marker")
    payload = get_pdf_backend_status()
    assert payload.env_var_value == "marker"
    assert payload.active_backend == "pymupdf"
    assert payload.active_source == "env"


def test_ocr_status_defaults_to_auto_without_requiring_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITASSIST_OCR_CONFIG_PATH", str(tmp_path / "ocr_config.json"))

    payload = get_ocr_status()

    assert payload.policy == "auto"
    assert payload.configured_engine is None
    assert payload.language == "en"
    assert isinstance(payload.available_engines, list)
    assert payload.next_safe_local_actions


def test_ocr_engines_endpoint_lists_builtin_engines() -> None:
    engines = list_ocr_engines()
    names = {engine.name for engine in engines}
    remote = next(engine for engine in engines if engine.name == "remote_api")

    assert {"paddleocr_gpu", "rapidocr", "windows", "remote_api"}.issubset(names)
    assert all(engine.engine_type in {"local", "remote"} for engine in engines)
    assert remote.readiness_status == "configuration_required"
    assert remote.readiness_blockers == [
        "remote OCR requires explicit api_key and base_url configuration"
    ]
    assert any("api_key" in action for action in remote.next_safe_local_actions)


def test_ocr_engine_selection_writes_local_runtime_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "ocr_config.json"
    monkeypatch.setenv("LITASSIST_OCR_CONFIG_PATH", str(config_path))

    response = select_ocr_engine_endpoint(
        OcrEngineSelectionRequest(
            policy="engine",
            engine="remote_api",
            language="en",
            engine_config={
                "api_key": "secret-value",
                "base_url": "https://ocr.example.test",
            },
        )
    )

    assert response.saved is True
    assert Path(response.config_path) == config_path
    assert response.status.policy == "engine"
    assert response.status.configured_engine == "remote_api"
    assert response.status.selected_engine is None
    assert response.status.warning == "remote OCR requires explicit allow_remote_upload=true consent"
    assert response.status.engine_config["api_key"] == "***"
    remote = next(
        engine for engine in response.status.available_engines if engine.name == "remote_api"
    )
    assert remote.readiness_status == "configuration_required"
    assert remote.readiness_blockers == [
        "remote OCR requires explicit allow_remote_upload=true consent"
    ]
    assert any("allow_remote_upload" in action for action in remote.next_safe_local_actions)
    assert config_path.exists()


def test_ocr_engine_selection_can_enable_remote_api_with_explicit_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "ocr_config.json"
    monkeypatch.setenv("LITASSIST_OCR_CONFIG_PATH", str(config_path))

    response = select_ocr_engine_endpoint(
        OcrEngineSelectionRequest(
            policy="engine",
            engine="remote_api",
            language="en",
            engine_config={
                "api_key": "secret-value",
                "base_url": "https://ocr.example.test",
                "allow_remote_upload": True,
            },
        )
    )

    assert response.saved is True
    assert response.status.policy == "engine"
    assert response.status.configured_engine == "remote_api"
    assert response.status.selected_engine == "remote_api"
    assert response.status.warning is None
    assert response.status.engine_config["api_key"] == "***"
    assert response.status.engine_config["allow_remote_upload"] is True
    remote = next(
        engine for engine in response.status.available_engines if engine.name == "remote_api"
    )
    assert remote.available is True
    assert remote.readiness_status == "ready"
    assert remote.readiness_blockers == []


def test_ocr_health_returns_unavailable_without_uploading_content() -> None:
    payload = check_ocr_engine_health(OcrHealthRequest(engine="remote_api"))

    assert payload.engine == "remote_api"
    assert payload.ok is False
    assert "requires explicit" in payload.detail
    assert payload.readiness_status == "configuration_required"
    assert payload.readiness_blockers == [
        "remote OCR requires explicit api_key and base_url configuration"
    ]
    assert any("api_key" in action for action in payload.next_safe_local_actions)


def test_ocr_execution_probe_requires_explicit_confirm() -> None:
    _register_mock_local_ocr()

    with pytest.raises(HTTPException) as exc_info:
        run_ocr_execution_probe(
            OcrExecutionProbeRequest(
                engine="mock_local",
                image_base64=base64.b64encode(b"fake-image").decode("ascii"),
            )
        )

    assert exc_info.value.status_code == 400
    assert "confirm_execution=true" in str(exc_info.value.detail)


def test_ocr_execution_probe_returns_bounded_execution_proof() -> None:
    _register_mock_local_ocr()
    image_bytes = b"fake-png-bytes"

    payload = run_ocr_execution_probe(
        OcrExecutionProbeRequest(
            confirm_execution=True,
            engine="mock_local",
            engine_config={"suffix": "ok"},
            image_base64=base64.b64encode(image_bytes).decode("ascii"),
            language="en",
            preview_chars=9,
        )
    )

    assert payload.schema_version == "scholar-ai-ocr-execution-probe/v1"
    assert payload.confirmed is True
    assert payload.engine == "mock_local"
    assert payload.engine_type == "local"
    assert payload.requires_network is False
    assert payload.input_kind == "image_base64"
    assert payload.input_bytes == len(image_bytes)
    assert payload.input_sha256 == hashlib.sha256(image_bytes).hexdigest()
    assert payload.text_length == len("mock text en bytes=14 ok")
    assert payload.text_sha256 == hashlib.sha256(b"mock text en bytes=14 ok").hexdigest()
    assert payload.text_preview == "mock text"


def test_ocr_execution_probe_accepts_bounded_temp_image_path(tmp_path: Path) -> None:
    _register_mock_local_ocr()
    image_path = tmp_path / "probe.png"
    image_path.write_bytes(b"temp-image")

    payload = run_ocr_execution_probe(
        OcrExecutionProbeRequest(
            confirm_execution=True,
            engine="mock_local",
            image_path=str(image_path),
        )
    )

    assert payload.input_kind == "image_path"
    assert payload.input_bytes == len(b"temp-image")
    assert payload.text_preview.startswith("mock text en bytes=10")


def test_ocr_execution_probe_blocks_remote_without_upload_consent() -> None:
    image_bytes = b"remote-image"

    with pytest.raises(HTTPException) as exc_info:
        run_ocr_execution_probe(
            OcrExecutionProbeRequest(
                confirm_execution=True,
                engine="remote_api",
                engine_config={
                    "api_key": "secret-value",
                    "base_url": "https://ocr.example.test",
                },
                image_base64=base64.b64encode(image_bytes).decode("ascii"),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "remote OCR requires explicit allow_remote_upload=true consent"


def test_ocr_execution_probe_runs_configured_external_paddleocr_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_executable = tmp_path / "python.exe"
    python_executable.write_bytes(b"stub")
    image_bytes = b"paddle-image"

    def _fake_external_python_json(
        executable: Path,
        script: str,
        *,
        timeout_seconds: int,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert executable == python_executable.resolve()
        assert timeout_seconds == 11
        if payload is None:
            assert "find_spec" in script
            return {"paddleocr_present": True, "paddle_present": True}
        assert payload["constructor_kwargs"] == {"device": "gpu:0"}
        assert payload["runtime_method"] == "predict"
        assert "PaddleOCR" in script
        return {"text": "router external paddle text"}

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

    payload = run_ocr_execution_probe(
        OcrExecutionProbeRequest(
            confirm_execution=True,
            engine="paddleocr_gpu",
            engine_config={
                "python_executable": str(python_executable),
                "constructor_kwargs": {"device": "gpu:0"},
                "runtime_method": "predict",
                "timeout_seconds": 11,
            },
            image_base64=base64.b64encode(image_bytes).decode("ascii"),
            preview_chars=80,
        )
    )

    assert payload.engine == "paddleocr_gpu"
    assert payload.requires_network is False
    assert payload.input_sha256 == hashlib.sha256(image_bytes).hexdigest()
    assert payload.text_preview == "router external paddle text"
    assert payload.text_sha256 == hashlib.sha256(b"router external paddle text").hexdigest()


def test_ocr_execution_probe_runs_configured_external_rapidocr_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_executable = tmp_path / "python.exe"
    python_executable.write_bytes(b"stub")
    image_bytes = b"rapid-image"

    def _fake_external_python_json(
        executable: Path,
        script: str,
        *,
        timeout_seconds: int,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert executable == python_executable.resolve()
        assert timeout_seconds == 12
        if payload is None:
            assert "rapidocr_onnxruntime" in script
            return {"rapidocr_present": True, "rapidocr_onnxruntime_present": False}
        assert payload["constructor_kwargs"] == {"det_model_path": "local-det.onnx"}
        assert "RapidOCR" in script
        return {"text": "router external rapid text"}

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

    payload = run_ocr_execution_probe(
        OcrExecutionProbeRequest(
            confirm_execution=True,
            engine="rapidocr",
            engine_config={
                "python_executable": str(python_executable),
                "constructor_kwargs": {"det_model_path": "local-det.onnx"},
                "timeout_seconds": 12,
            },
            image_base64=base64.b64encode(image_bytes).decode("ascii"),
            preview_chars=80,
        )
    )

    assert payload.engine == "rapidocr"
    assert payload.requires_network is False
    assert payload.input_sha256 == hashlib.sha256(image_bytes).hexdigest()
    assert payload.text_preview == "router external rapid text"
    assert payload.text_sha256 == hashlib.sha256(b"router external rapid text").hexdigest()


def test_pdf_backend_ocr_routes_resolve_on_full_app_with_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_mock_local_ocr()
    monkeypatch.setenv("LITASSIST_OCR_CONFIG_PATH", str(tmp_path / "ocr_config.json"))
    client = TestClient(app)
    headers = {"X-LitAssist-Capability": get_local_api_capability_token()}

    status = client.get("/api/pdf-backend/ocr-status", headers=headers)
    engines = client.get("/api/pdf-backend/ocr-engines", headers=headers)
    health = client.post(
        "/api/pdf-backend/ocr-health",
        json={"engine": "remote_api"},
        headers=headers,
    )
    execution = client.post(
        "/api/pdf-backend/ocr-execution-probe",
        json={
            "confirm_execution": True,
            "engine": "mock_local",
            "image_base64": base64.b64encode(b"route-image").decode("ascii"),
            "preview_chars": 20,
        },
        headers=headers,
    )

    assert status.status_code == 200
    status_payload = status.json()
    status_engines = {item["name"]: item for item in status_payload["available_engines"]}
    assert status_payload["policy"] == "auto"
    assert "next_safe_local_actions" in status_payload
    assert status_engines["mock_local"]["readiness_status"] == "ready"
    assert status_engines["remote_api"]["readiness_status"] == "configuration_required"
    assert "next_safe_local_actions" in status_engines["remote_api"]
    assert engines.status_code == 200
    assert {item["name"] for item in engines.json()} >= {
        "paddleocr_gpu",
        "rapidocr",
        "windows",
        "remote_api",
    }
    assert all("readiness_blockers" in item for item in engines.json())
    assert health.status_code == 200
    assert health.json()["engine"] == "remote_api"
    assert health.json()["readiness_status"] == "configuration_required"
    assert "next_safe_local_actions" in health.json()
    assert execution.status_code == 200
    assert execution.json()["schema_version"] == "scholar-ai-ocr-execution-probe/v1"
    assert execution.json()["engine"] == "mock_local"
    assert execution.json()["input_sha256"] == hashlib.sha256(b"route-image").hexdigest()
