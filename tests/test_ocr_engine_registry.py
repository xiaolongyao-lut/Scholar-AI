# -*- coding: utf-8 -*-
"""Tests for OCR engine registry and auto policy contracts."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import time
import types
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

import httpcore
import httpx
import pytest
from PIL import Image

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
from pdf_backends.ocr_engine_registry import (  # noqa: E402
    _AUTO_PRIORITY,
    build_ocr_engine,
    load_builtin_ocr_engines,
)


class _MockResponseContext:
    """Context manager matching the response returned by `httpx.Client.stream`."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(self, *_args: object) -> None:
        return None


class _MockStreamingClient:
    """Let existing HTTP client doubles participate in streaming downloads."""

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        raise NotImplementedError

    def stream(self, method: str, url: str, **kwargs: Any) -> _MockResponseContext:
        assert method == "GET"
        response = self.get(url, **kwargs)
        if response.is_stream_consumed:
            response = httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=httpx.ByteStream(response.content),
                request=response.request,
                extensions=response.extensions,
            )
        return _MockResponseContext(response)


class _RecordingNetworkStream(httpcore.NetworkStream):
    """Minimal HTTP/1.1 stream that records TLS identity and request bytes."""

    def __init__(self) -> None:
        self._response = bytearray(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
        )
        self.writes: list[bytes] = []
        self.tls_hostnames: list[str | None] = []

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        del timeout
        if not self._response:
            return b""
        chunk = bytes(self._response[:max_bytes])
        del self._response[:max_bytes]
        return chunk

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        del timeout
        self.writes.append(buffer)

    def close(self) -> None:
        return None

    def start_tls(
        self,
        ssl_context: object,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> "_RecordingNetworkStream":
        del ssl_context, timeout
        self.tls_hostnames.append(server_hostname)
        return self


class _RecordingNetworkBackend(httpcore.NetworkBackend):
    """Record the concrete TCP address selected by the pinned transport."""

    def __init__(self) -> None:
        self.connect_calls: list[tuple[str, int]] = []
        self.stream = _RecordingNetworkStream()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.NetworkStream:
        del timeout, local_address, socket_options
        self.connect_calls.append((host, port))
        return self.stream

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: object = None,
    ) -> httpcore.NetworkStream:
        del path, timeout, socket_options
        raise AssertionError("Paddle result transport must not use Unix sockets")


def _encoded_test_image(*, width: int, height: int) -> bytes:
    """Return deterministic PNG bytes with known source dimensions."""

    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


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

    def readiness_status(self) -> str:
        # Mock must satisfy the current OcrEngine readiness contract so the
        # registered stand-in stays structurally valid; "ready" when available.
        return "ready" if self.is_available() else "unavailable"

    def readiness_blockers(self) -> tuple[str, ...]:
        return () if self.is_available() else ("mock unavailable",)

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
        assert status["selected_engine"] in {"paddleocr_gpu", "rapidocr", "windows"}
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
    assert readiness_by_name["rapidocr"] in {"ready", "dependency_missing", "adapter_not_wired"}
    assert readiness_by_name["windows"] in {
        "ready",
        "dependency_missing",
        "platform_unsupported",
    }


def test_ocr_engine_protocol_requires_readiness_contract() -> None:
    engine = _LegacyOcrEngine()

    assert not isinstance(engine, OcrEngine)


def test_ocr_engine_protocol_accepts_conforming_engines() -> None:
    """Real built-in engines and the test mock must satisfy the OcrEngine Protocol.

    The negative legacy check alone cannot catch a regression where a *real*
    engine drops a required Protocol method (for example readiness_status), because
    runtime_checkable isinstance only inspects method presence. Without a positive
    conformance assertion over the registered built-in engines, such a break would
    pass CI while silently degrading the OcrEngine contract that ingestion, health,
    and status surfaces depend on. The mock is included so the registered stand-in
    used elsewhere in this suite stays a structurally valid engine.
    """

    conforming_engines = [
        _MockOcrEngine(),
        WindowsOcrEngine({}),
        RapidOcrEngine({}),
        RemoteApiOcrEngine({}),
        PaddleOcrGpuEngine({}),
    ]
    for engine in conforming_engines:
        assert isinstance(engine, OcrEngine), type(engine).__name__

    # Every required Protocol member must be present on each conforming engine so a
    # dropped method is caught by name, not only by the structural isinstance check.
    required_members = (
        "name",
        "display_name",
        "engine_type",
        "requires_network",
        "is_available",
        "unavailable_reason",
        "readiness_status",
        "readiness_blockers",
        "ocr_image",
        "health_check",
    )
    for engine in conforming_engines:
        missing = [member for member in required_members if not hasattr(engine, member)]
        assert not missing, (type(engine).__name__, missing)

    # Self-check: the Protocol must still reject a shape missing readiness methods,
    # so this positive guard cannot pass against a degraded contract.
    assert not isinstance(_LegacyOcrEngine(), OcrEngine)


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


def test_remote_api_mistral_provider_uses_official_ocr_payload(
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
            requests.append({"url": url, "json": dict(json), "headers": dict(headers)})
            return httpx.Response(
                200,
                json={"pages": [{"markdown": "page one"}, {"markdown": "page two"}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "mistral",
            "api_key": "secret-value",
            "base_url": "https://api.mistral.ai/v1",
            "model": "mistral-ocr-latest",
            "allow_remote_upload": True,
        }
    )

    assert engine.ocr_image(b"image-bytes", language="en") == "page one\npage two"
    assert requests[0]["url"] == "https://api.mistral.ai/v1/ocr"
    assert requests[0]["json"]["model"] == "mistral-ocr-latest"
    assert requests[0]["json"]["document"]["type"] == "image_url"
    assert requests[0]["json"]["document"]["image_url"].startswith("data:image/png;base64,")
    assert requests[0]["headers"]["Authorization"] == "Bearer secret-value"


def test_remote_api_mistral_full_ocr_url_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

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
            del json, headers
            urls.append(url)
            return httpx.Response(
                200,
                json={"pages": [{"markdown": "recognized"}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "mistral",
            "api_key": "secret-value",
            "base_url": "https://api.mistral.ai/v1/ocr",
            "model": "mistral-ocr-latest",
            "allow_remote_upload": True,
        }
    )

    assert engine.ocr_image(b"image-bytes", language="en") == "recognized"
    assert urls == ["https://api.mistral.ai/v1/ocr"]


def test_remote_api_mineru_provider_is_not_page_level_ocr() -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "mineru",
            "api_key": "secret-value",
            "base_url": "https://mineru.net/api",
            "model": "pipeline",
            "allow_remote_upload": True,
        }
    )

    health = engine.health_check()

    assert engine.is_available() is False
    assert engine.readiness_status() == "adapter_not_wired"
    assert health.ok is False
    assert "asynchronous document parsing" in health.detail


def test_remote_api_paddle_jobs_submits_polls_and_extracts_document_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    client_options: list[dict[str, Any]] = []
    status_count = 0

    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **kwargs: Any,
        ) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects
            client_options.append(dict(kwargs))

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            data: dict[str, str],
            files: dict[str, tuple[str, bytes, str]],
            headers: dict[str, str],
        ) -> httpx.Response:
            calls.append(
                {
                    "method": "POST",
                    "url": url,
                    "data": dict(data),
                    "files": dict(files),
                    "headers": dict(headers),
                }
            )
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "job-123"}},
                request=httpx.Request("POST", url),
            )

        def get(
            self,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            follow_redirects: bool = False,
            timeout: float | None = None,
            **_kwargs: Any,
        ) -> httpx.Response:
            nonlocal status_count
            calls.append(
                {
                    "method": "GET",
                    "url": url,
                    "headers": dict(headers or {}),
                    "follow_redirects": follow_redirects,
                }
            )
            if url.endswith("/job-123"):
                status_count += 1
                data: dict[str, Any]
                if status_count == 1:
                    data = {"state": "running"}
                else:
                    data = {
                        "state": "done",
                        "resultUrl": {"jsonUrl": "https://results.example.test/job-123.jsonl"},
                    }
                return httpx.Response(
                    200,
                    json={"code": 0, "data": data},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                text=(
                    '{"result":{"layoutParsingResults":[{"markdown":{"text":"page one"}}]}}\n'
                    '{"result":{"layoutParsingResults":[{"markdown":{"text":"page two"}}]}}\n'
                ),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    monkeypatch.setattr(ocr_builtin_engines.time, "sleep", lambda _seconds: None)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
            "timeout_seconds": 12,
        }
    )
    image_path = tmp_path / "scan-page.webp"
    image_bytes = b"RIFF\x0c\x00\x00\x00WEBPVP8 "
    image_path.write_bytes(image_bytes)

    health = engine.health_check()
    text = engine.ocr_image(image_path, language="zh")

    assert engine.is_available() is True
    assert engine.readiness_status() == "ready"
    assert health.ok is True
    assert text == "page one\npage two"
    assert calls[0] == {
        "method": "POST",
        "url": "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        "data": {"model": "PaddleOCR-VL-1.6", "optionalPayload": "{}"},
        "files": {"file": ("scan-page.webp", image_bytes, "image/webp")},
        "headers": {
            "Authorization": "Bearer secret-value",
            "Accept": "application/json",
        },
    }
    assert calls[1]["url"].endswith("/api/v2/ocr/jobs/job-123")
    assert calls[1]["headers"]["Authorization"] == "Bearer secret-value"
    assert calls[-1] == {
        "method": "GET",
        "url": "https://results.example.test/job-123.jsonl",
        "headers": {"Accept-Encoding": "identity"},
        "follow_redirects": False,
    }
    assert client_options[0] == {}
    assert client_options[1]["trust_env"] is False
    assert isinstance(
        client_options[1]["transport"],
        ocr_builtin_engines._PinnedPublicHTTPTransport,
    )


@pytest.mark.parametrize(
    "result_url",
    (
        "https://127.0.0.1:8000/health",
        "https://10.0.0.5/result.jsonl",
        "https://169.254.169.254/latest/meta-data/",
    ),
)
def test_remote_api_paddle_jobs_rejects_unsafe_result_ip_literals(
    result_url: str,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="unsafe network target"):
        engine._validated_paddle_result_url(result_url)


def test_remote_api_paddle_jobs_rejects_result_host_resolving_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["127.0.0.1"],
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="unsafe network target"):
        engine._validated_paddle_result_url("https://results.example.test/job.jsonl")


def test_paddle_result_transport_pins_tcp_address_and_preserves_tls_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = iter(
        (
            ["93.184.216.34"],
            ["8.8.8.8"],
        )
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: next(resolutions),
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    result_url = "https://results.example.test/job.jsonl"
    assert engine._validated_paddle_result_url(result_url) == result_url

    transport_type = getattr(
        ocr_builtin_engines,
        "_PinnedPublicHTTPTransport",
        None,
    )
    assert transport_type is not None
    backend = _RecordingNetworkBackend()
    transport = transport_type(network_backend=backend)
    with httpx.Client(transport=transport, trust_env=False) as client:
        response = client.get(result_url)

    assert response.status_code == 200
    assert backend.connect_calls == [("8.8.8.8", 443)]
    assert backend.stream.tls_hostnames == ["results.example.test"]
    request_bytes = b"".join(backend.stream.writes).lower()
    assert b"host: results.example.test\r\n" in request_bytes


def test_paddle_result_transport_rejects_private_connect_time_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = iter(
        (
            ["93.184.216.34"],
            ["127.0.0.1"],
        )
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: next(resolutions),
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    result_url = "https://results.example.test/job.jsonl"
    assert engine._validated_paddle_result_url(result_url) == result_url

    transport_type = getattr(
        ocr_builtin_engines,
        "_PinnedPublicHTTPTransport",
        None,
    )
    assert transport_type is not None
    backend = _RecordingNetworkBackend()
    transport = transport_type(network_backend=backend)
    with httpx.Client(transport=transport, trust_env=False) as client:
        with pytest.raises(httpx.ConnectError, match="unsafe network target"):
            client.get(result_url)

    assert backend.connect_calls == []


def test_ocr_builtin_engines_supports_isolated_canonical_import(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    site_packages = Path(httpx.__file__).resolve().parents[1]
    script = r"""
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
site_packages = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(site_packages))
sys.path.insert(0, str(repo_root))
import literature_assistant.core.pdf_backends.ocr_builtin_engines  # noqa: F401
"""
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-c",
            script,
            str(repo_root),
            str(site_packages),
        ),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_remote_api_paddle_jobs_rejects_compressed_result_before_decoding() -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    response = httpx.Response(
        200,
        headers={"Content-Encoding": "gzip"},
        stream=httpx.ByteStream(gzip.compress(b'{"result": {}}\n')),
        request=httpx.Request("GET", "https://results.example.test/result.jsonl"),
    )
    try:
        with pytest.raises(RuntimeError, match="identity content encoding"):
            engine._bounded_paddle_result_text(response)
    finally:
        response.close()


def test_remote_api_paddle_jobs_rejects_oversized_result_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_builtin_engines,
        "_PADDLE_RESULT_MAX_BYTES",
        256,
        raising=False,
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )

    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "oversized-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/oversized-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/oversized.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            oversized_jsonl = json.dumps(
                {
                    "result": {
                        "layoutParsingResults": [
                            {"markdown": {"text": "x" * 512}}
                        ]
                    }
                }
            )
            return httpx.Response(
                200,
                stream=httpx.ByteStream(oversized_jsonl.encode("utf-8")),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="exceeds the 256-byte limit"):
        engine.ocr_image(b"image-bytes", language="en")


def test_remote_api_paddle_jobs_times_out_slow_result_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values = iter((0.0, 0.0, 0.0, 6.0))
    monkeypatch.setattr(
        ocr_builtin_engines.time,
        "monotonic",
        lambda: next(monotonic_values, 6.0),
    )
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )

    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "slow-result-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/slow-result-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/slow.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                stream=httpx.ByteStream(
                    b'{"result":{"layoutParsingResults":[]}}\n'
                ),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
            "timeout_seconds": 5,
            "poll_timeout_seconds": 10,
        }
    )

    with pytest.raises(RuntimeError, match="result download timed out"):
        engine.ocr_image(b"image-bytes", language="en")


def test_remote_api_paddle_jobs_enforces_wall_clock_result_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BlockingStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            time.sleep(0.25)
            yield b'{"result":{"layoutParsingResults":[]}}\n'

    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                stream=_BlockingStream(),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    monkeypatch.setattr(engine, "_timeout_seconds", lambda: 0.05)

    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="result download timed out"):
        engine._download_paddle_result(
            "https://results.example.test/wall-clock.jsonl"
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.15


def test_remote_api_paddle_jobs_counts_done_url_dns_in_result_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_started_at: list[float] = []

    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "blocking-dns-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/blocking-dns-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/blocking.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                stream=httpx.ByteStream(
                    b'{"result":{"layoutParsingResults":[]}}\n'
                ),
                request=httpx.Request("GET", url),
            )

    def _blocking_resolver(_host: str, _port: int) -> list[str]:
        if not resolver_started_at:
            resolver_started_at.append(time.perf_counter())
        time.sleep(0.25)
        return ["93.184.216.34"]

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        _blocking_resolver,
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    monkeypatch.setattr(engine, "_timeout_seconds", lambda: 0.05)

    with pytest.raises(RuntimeError, match="result download timed out"):
        engine.ocr_image(b"image-bytes", language="en")
    returned_at = time.perf_counter()

    assert resolver_started_at
    assert returned_at - resolver_started_at[0] < 0.20


def test_remote_api_paddle_jobs_rejects_http_result_before_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_resolver(_host: str, _port: int) -> list[str]:
        pytest.fail("plain HTTP result URLs must be rejected before DNS")

    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        _unexpected_resolver,
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="result URL must use https"):
        engine._download_paddle_result(
            "http://results.example.test/insecure.jsonl"
        )


def test_remote_api_paddle_jobs_prefers_located_layout_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    payload = (
        '{"result":{"layoutParsingResults":[{"markdown":{"text":"whole page markdown"},'
        '"prunedResult":{"width":1000,"height":2000,"parsing_res_list":['
        '{"block_content":"located sentence","block_label":"text",'
        '"block_bbox":[10,20,90,40]},'
        '{"block_content":"Figure 2 caption","block_label":"figure_title",'
        '"block_bbox":[15,90,75,160]}]}}],'
        '"ocrResults":[{"prunedResult":{"width":1000,"height":2000,'
        '"rec_texts":["duplicate OCR fallback"],'
        '"rec_boxes":[[0,0,1000,2000]]}}]}}\n'
    )
    monkeypatch.setattr(
        engine,
        "_run_paddle_jobs",
        lambda _image_bytes, **kwargs: engine._paddle_jsonl_result(
            payload,
            image_size=kwargs["image_size"],
        ),
    )

    result = engine.ocr_image_result(
        _encoded_test_image(width=100, height=200),
        language="zh",
    )

    assert result.text == "located sentence\nFigure 2 caption"
    assert [(region.markdown, region.block_type) for region in result.regions] == [
        ("located sentence", "Text"),
        ("Figure 2 caption", "FigureCaption"),
    ]
    assert result.regions[0].bbox == pytest.approx((0.1, 0.1, 0.8, 0.1))
    assert result.regions[1].bbox == pytest.approx((0.15, 0.45, 0.6, 0.35))
    assert "duplicate OCR fallback" not in result.text


def test_remote_api_paddle_jsonl_falls_back_to_located_ocr_lines() -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PP-OCRv5",
            "allow_remote_upload": True,
        }
    )
    payload = (
        '{"result":{"layoutParsingResults":[],"ocrResults":[{"prunedResult":'
        '{"width":800,"height":400,'
        '"rec_texts":["first line","","second line","outside line"],'
        '"rec_boxes":[[40,20,240,60],[0,0,0,0],[20,100,380,190],'
        '[0,0,500,20]]}}]}}\n'
    )

    result = engine._paddle_jsonl_result(payload, image_size=(400, 200))

    assert result.text == "first line\nsecond line\noutside line"
    assert [region.markdown for region in result.regions] == ["first line", "second line"]
    assert all(region.block_type == "Text" for region in result.regions)
    assert result.regions[0].bbox == pytest.approx((0.1, 0.1, 0.5, 0.2))
    assert result.regions[1].bbox == pytest.approx((0.05, 0.5, 0.9, 0.45))


@pytest.mark.parametrize(
    "extra_payload",
    [
        {"useDocOrientationClassify": True},
        {"useDocUnwarping": True},
    ],
)
def test_remote_api_paddle_jsonl_drops_exact_regions_after_page_transform(
    extra_payload: dict[str, bool],
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
            "extra_payload": extra_payload,
        }
    )
    payload = (
        '{"result":{"layoutParsingResults":[{"prunedResult":'
        '{"width":100,"height":100,"parsing_res_list":['
        '{"block_content":"transformed sentence","block_label":"text",'
        '"block_bbox":[10,10,90,30]}]}}],"ocrResults":[]}}\n'
    )

    result = engine._paddle_jsonl_result(payload, image_size=(100, 100))

    assert result.text == "transformed sentence"
    assert result.regions == ()


def test_remote_api_paddle_jobs_reports_authentication_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded_files: list[dict[str, tuple[str, bytes, str]]] = []

    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **kwargs: Any) -> httpx.Response:
            uploaded_files.append(dict(kwargs["files"]))
            return httpx.Response(
                401,
                json={"code": 401, "msg": "invalid access token"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="authentication failed"):
        engine.ocr_image(b"\xff\xd8\xff\xe0jpeg-bytes", language="en")

    assert uploaded_files == [
        {"file": ("page.jpg", b"\xff\xd8\xff\xe0jpeg-bytes", "image/jpeg")}
    ]


def test_remote_api_paddle_jobs_full_jobs_url_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            urls.append(url)
            return httpx.Response(
                401,
                json={"code": 401, "msg": "invalid access token"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    jobs_url = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": jobs_url,
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="authentication failed"):
        engine.ocr_image(b"image-bytes", language="en")

    assert urls == [jobs_url]


def test_remote_api_paddle_jobs_reports_quota_from_403_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                403,
                json={"code": 403, "msg": "Daily quota exceeded"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="quota or rate limit exceeded") as exc_info:
        engine.ocr_image(b"image-bytes", language="en")

    assert "authentication" not in str(exc_info.value).lower()


def test_remote_api_paddle_jobs_reads_nested_error_message_for_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                403,
                json={"code": 403, "data": {"errorMsg": "Daily quota exceeded"}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(
        RuntimeError,
        match="quota or rate limit exceeded: Daily quota exceeded",
    ):
        engine.ocr_image(b"image-bytes", language="en")


def test_remote_api_paddle_jobs_classifies_provider_code_12001_as_quota() -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    response = httpx.Response(
        200,
        json={"code": 12001, "msg": "Daily service quota exhausted", "data": {}},
        request=httpx.Request("POST", "https://provider.example.test/jobs"),
    )

    with pytest.raises(RuntimeError, match="quota or rate limit exceeded"):
        engine._paddle_response_data(response, operation="job submission")


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_detail"),
    [
        (400, {"code": 400, "msg": "Invalid request parameters"}, "invalid request"),
        (429, {"code": 429, "msg": "Daily quota exceeded"}, "quota or rate limit exceeded"),
        (503, {"code": 503, "msg": "Service temporarily unavailable"}, "service unavailable"),
        (504, {"code": 504, "msg": "Gateway timeout"}, "service unavailable"),
        (401, {"code": 401, "msg": "Daily quota exceeded"}, "quota or rate limit exceeded"),
        (401, {"code": 401, "msg": "Invalid access token"}, "authentication failed"),
        (401, {"code": 401, "msg": "Request blocked by policy"}, "failed (http 401)"),
        (403, {"code": 403, "msg": "Daily quota exceeded"}, "quota or rate limit exceeded"),
        (403, {"code": 403, "msg": "Invalid access token"}, "authentication failed"),
        (403, {"code": 403, "msg": "Request blocked by policy"}, "failed (http 403)"),
    ],
)
def test_remote_api_paddle_jobs_classifies_http_errors_by_status_and_body(
    status_code: int,
    payload: dict[str, Any],
    expected_detail: str,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "test-token",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    response = httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://provider.example.test/jobs"),
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine._paddle_response_data(response, operation="job submission")

    assert expected_detail in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"code": 91001, "msg": "Daily quota exceeded"}, "quota or rate limit exceeded"),
        ({"code": 91002, "errorMsg": "Invalid access token"}, "authentication failed"),
        (
            {"code": 91003, "data": {"errorMsg": "Invalid request parameters"}},
            "invalid request",
        ),
        (
            {"code": 91004, "data": {"errorMsg": "Service temporarily unavailable"}},
            "service unavailable",
        ),
        ({"code": 91005, "msg": "Unclassified provider failure"}, "failed (code 91005)"),
    ],
)
def test_remote_api_paddle_jobs_classifies_nonzero_business_code_from_error_message(
    payload: dict[str, Any],
    expected_detail: str,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "test-token",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://provider.example.test/jobs"),
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine._paddle_response_data(response, operation="job submission")

    assert expected_detail in str(exc_info.value).lower()


def test_remote_api_paddle_jobs_redacts_and_bounds_provider_error_detail() -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    response = httpx.Response(
        400,
        text=(
            "access_token=secret-value Bearer upstream-secret "
            + "provider-detail-" * 80
        ),
        request=httpx.Request("POST", "https://provider.example.test/jobs"),
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine._paddle_response_data(response, operation="job submission")

    detail = str(exc_info.value)
    assert "secret-value" not in detail
    assert "upstream-secret" not in detail
    assert "[REDACTED]" in detail
    assert len(detail) <= 380


def test_remote_api_paddle_jobs_redacts_complete_authorization_header() -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "configured-secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    detail = engine._safe_paddle_detail(
        "Authorization: Bearer synthetic-upstream-value"
    )

    assert detail == "Authorization: [REDACTED]"
    assert "synthetic-upstream-value" not in detail


@pytest.mark.parametrize("invalid_code", [[12001], {"code": 12001}])
def test_remote_api_paddle_jobs_rejects_non_scalar_code_stably(
    invalid_code: object,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )
    response = httpx.Response(
        200,
        json={"code": invalid_code, "data": {}},
        request=httpx.Request("POST", "https://provider.example.test/jobs"),
    )

    with pytest.raises(RuntimeError, match="code must be an integer or null"):
        engine._paddle_response_data(response, operation="job submission")


def test_remote_api_paddle_jobs_does_not_assume_unknown_403_is_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                403,
                json={"code": 403, "msg": "Request forbidden by service policy"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match=r"job submission failed \(HTTP 403\)") as exc_info:
        engine.ocr_image(b"image-bytes", language="en")

    assert "authentication" not in str(exc_info.value).lower()


def test_remote_api_paddle_jobs_preserves_plain_text_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                403,
                text="Request forbidden by upstream policy",
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(
        RuntimeError,
        match=r"job submission failed \(HTTP 403\): Request forbidden",
    ) as exc_info:
        engine.ocr_image(b"image-bytes", language="en")

    assert "authentication" not in str(exc_info.value).lower()


def test_remote_api_paddle_jobs_allows_blank_jsonl_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "blank-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/blank-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/blank.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                text='{"result":{"layoutParsingResults":[],"ocrResults":[]}}\n',
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    assert engine.ocr_image(b"blank-image", language="en") == ""


@pytest.mark.parametrize(
    ("model", "payload", "missing_field"),
    [
        (
            "PaddleOCR-VL-1.6",
            '{"result":{"unexpected":[]}}\n',
            "layoutParsingResults",
        ),
        (
            "PaddleOCR-VL-1.6",
            '{"result":{"layoutParsingResults":{}}}\n',
            "layoutParsingResults",
        ),
        (
            "PP-OCRv5",
            '{"result":{"layoutParsingResults":[]}}\n',
            "ocrResults",
        ),
    ],
)
def test_remote_api_paddle_jobs_rejects_malformed_model_result_shape(
    model: str,
    payload: str,
    missing_field: str,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "configured-secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": model,
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match=missing_field):
        engine._paddle_jsonl_result(payload, image_size=None)


@pytest.mark.parametrize(
    ("field_name", "accessor_name"),
    [
        ("timeout_seconds", "_timeout_seconds"),
        ("poll_timeout_seconds", "_poll_timeout_seconds"),
    ],
)
def test_remote_api_paddle_jobs_rejects_nan_timeouts(
    field_name: str,
    accessor_name: str,
) -> None:
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "configured-secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
            field_name: "nan",
        }
    )

    accessor = getattr(engine, accessor_name)
    with pytest.raises(ValueError, match=rf"{field_name} must be finite"):
        accessor()


def test_remote_api_paddle_jobs_uses_independent_default_poll_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_count = 0
    monotonic_values = iter((0.0, 0.0, 0.0, 300.0))

    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            assert timeout == 12
            del follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "slow-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            nonlocal status_count
            if url.endswith("/slow-job"):
                status_count += 1
                data: dict[str, Any] = {"state": "running"}
                if status_count == 2:
                    data = {
                        "state": "done",
                        "resultUrl": {
                            "jsonUrl": "https://results.example.test/slow.jsonl"
                        },
                    }
                return httpx.Response(
                    200,
                    json={"code": 0, "data": data},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                text='{"result":{"layoutParsingResults":[]}}\n',
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    monkeypatch.setattr(
        ocr_builtin_engines.time,
        "monotonic",
        lambda: next(monotonic_values, 300.0),
    )
    monkeypatch.setattr(ocr_builtin_engines.time, "sleep", lambda _seconds: None)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
            "timeout_seconds": 12,
        }
    )

    assert engine.ocr_image(b"image-bytes", language="en") == ""
    assert status_count == 2


def test_remote_api_paddle_jobs_limits_status_request_to_poll_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts: list[float | None] = []
    monotonic_values = iter((100.0, 108.0, 110.0))

    class _MockClient:
        def get(self, url: str, **kwargs: Any) -> httpx.Response:
            observed_timeouts.append(kwargs.get("timeout"))
            return httpx.Response(
                200,
                json={"code": 0, "data": {"state": "running"}},
                request=httpx.Request("GET", url),
            )

    def _monotonic() -> float:
        return next(monotonic_values, 110.0)

    monkeypatch.setattr(ocr_builtin_engines.time, "monotonic", _monotonic)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
            "timeout_seconds": 60,
            "poll_timeout_seconds": 10,
        }
    )

    with pytest.raises(RuntimeError, match="polling timed out"):
        engine._poll_paddle_job(
            _MockClient(),
            jobs_url="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
            job_id="deadline-job",
            headers={"Authorization": "Bearer secret-value"},
        )

    assert observed_timeouts == [pytest.approx(2.0)]


def test_remote_api_paddle_jobs_reports_result_download_http_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "download-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/download-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/download.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                503,
                text="Object storage temporarily unavailable",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(
        RuntimeError,
        match=r"result download failed \(HTTP 503\): Object storage temporarily unavailable",
    ):
        engine.ocr_image(b"image-bytes", language="en")


def test_remote_api_paddle_jobs_redacts_result_download_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "download-secret-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/download-secret-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/secret.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                503,
                text="access_token=secret-value Bearer upstream-secret",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine.ocr_image(b"image-bytes", language="en")

    detail = str(exc_info.value)
    assert "secret-value" not in detail
    assert "upstream-secret" not in detail
    assert "[REDACTED]" in detail


def test_remote_api_paddle_jobs_reports_result_download_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient(_MockStreamingClient):
        def __init__(
            self,
            *,
            timeout: float,
            follow_redirects: bool,
            **_kwargs: Any,
        ) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "timeout-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            if url.endswith("/timeout-job"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "state": "done",
                            "resultUrl": {
                                "jsonUrl": "https://results.example.test/timeout.jsonl"
                            },
                        },
                    },
                    request=httpx.Request("GET", url),
                )
            request = httpx.Request("GET", url)
            raise httpx.ReadTimeout("synthetic timeout", request=request)

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    monkeypatch.setattr(
        ocr_builtin_engines,
        "resolve_host_to_ips",
        lambda _host, _port: ["93.184.216.34"],
        raising=False,
    )
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="result download timed out"):
        engine.ocr_image(b"image-bytes", language="en")


def test_remote_api_paddle_jobs_rejects_unknown_job_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "unknown-state-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"state": "queued"}},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="unknown or missing state: 'queued'"):
        engine.ocr_image(b"image-bytes", language="en")


@pytest.mark.parametrize("invalid_state", [["running"], {"state": "running"}])
def test_remote_api_paddle_jobs_rejects_non_string_state_stably(
    invalid_state: object,
) -> None:
    class _MockClient:
        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"state": invalid_state}},
                request=httpx.Request("GET", url),
            )

    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="state must be a string"):
        engine._poll_paddle_job(
            _MockClient(),  # type: ignore[arg-type]
            jobs_url="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
            job_id="malformed-state-job",
            headers={"Authorization": "Bearer secret-value"},
        )


def test_remote_api_paddle_jobs_surfaces_failed_job_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "failed-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "state": "failed",
                        "errorMsg": "Page decoder failed",
                    },
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="failed-job failed: Page decoder failed"):
        engine.ocr_image(b"image-bytes", language="en")


def test_remote_api_paddle_jobs_redacts_failed_job_detail() -> None:
    class _MockClient:
        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "state": "failed",
                        "errorMsg": "access_token=secret-value Bearer upstream-secret",
                    },
                },
                request=httpx.Request("GET", url),
            )

    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine._poll_paddle_job(
            _MockClient(),  # type: ignore[arg-type]
            jobs_url="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
            job_id="failed-secret-job",
            headers={"Authorization": "Bearer secret-value"},
        )

    detail = str(exc_info.value)
    assert "secret-value" not in detail
    assert "upstream-secret" not in detail
    assert "[REDACTED]" in detail


def test_remote_api_paddle_jobs_rejects_done_state_without_json_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MockClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            del timeout, follow_redirects

        def __enter__(self) -> "_MockClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "malformed-job"}},
                request=httpx.Request("POST", url),
            )

        def get(self, url: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"state": "done", "resultUrl": {}},
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(ocr_builtin_engines.httpx, "Client", _MockClient)
    engine = RemoteApiOcrEngine(
        {
            "provider": "paddle_jobs",
            "api_key": "secret-value",
            "base_url": "https://paddleocr.aistudio-app.com",
            "model": "PaddleOCR-VL-1.6",
            "allow_remote_upload": True,
        }
    )

    with pytest.raises(RuntimeError, match="missing resultUrl.jsonUrl"):
        engine.ocr_image(b"image-bytes", language="en")


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
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
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


def test_paddleocr_status_requires_paddle_runtime_module(
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
    assert status["selected_engine"] is None
    assert paddle["available"] is False
    assert paddle["readiness_status"] == "dependency_missing"
    assert paddle["readiness_blockers"] == [
        "paddlepaddle runtime module 'paddle' is not installed in the active Python runtime"
    ]
    assert engine.is_available() is False
    assert engine.readiness_status() == "dependency_missing"
    assert health.ok is False
    assert health.detail == (
        "paddlepaddle runtime module 'paddle' is not installed in the active Python runtime"
    )


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


def test_rapidocr_external_python_execution_reads_v3_output_txts_tuple(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_dir = tmp_path / "fake_module"
    module_dir.mkdir()
    (module_dir / "rapidocr.py").write_text(
        """
class _RapidOCROutput:
    txts = ("external rapid v3 text",)


class RapidOCR:
    def __init__(self, **_kwargs):
        pass

    def __call__(self, _image_path):
        return _RapidOCROutput()
""".strip(),
        encoding="utf-8",
    )
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"png")
    monkeypatch.setenv("PYTHONPATH", str(module_dir))

    text = RapidOcrEngine({"python_executable": sys.executable}).ocr_image(
        image_path,
        language="en",
    )

    assert text == "external rapid v3 text"


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
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
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
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
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
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
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


def test_rapidocr_engine_reads_v3_output_txts_tuple(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RapidOCR 3.x returns a RapidOCROutput with tuple-valued txts."""

    class _FakeRapidOcrOutput:
        txts = ("Scholar AI RapidOCR proof 2026",)

    class _FakeRapidOCR:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __call__(self, _image_path: str) -> _FakeRapidOcrOutput:
            return _FakeRapidOcrOutput()

    fake_module = types.SimpleNamespace(RapidOCR=_FakeRapidOCR)
    image_path = tmp_path / "rapidocr-v3.png"
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

    assert RapidOcrEngine().ocr_image(image_path, language="en") == "Scholar AI RapidOCR proof 2026"


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


class _HealthAlignedMockOcrEngine(_MockOcrEngine):
    """Mock whose status-surface readiness mirrors its health_check result.

    Real built-in engines derive ``public_ocr_status`` readiness from
    ``readiness_status()`` while ``health_check()`` is a second, independent code
    path (see ``_health_from_availability``). This mock keeps the two paths
    aligned so the consistency contract below has a valid positive case without
    touching any real engine ``health_check`` that may run a local OCR probe.
    """

    def __init__(self, name: str, *, available: bool, blocker: str) -> None:
        super().__init__({"available": available})
        self.name = name
        self._blocker = blocker

    def readiness_status(self) -> str:
        return "ready" if self.is_available() else "dependency_missing"

    def readiness_blockers(self) -> tuple[str, ...]:
        return () if self.is_available() else (self._blocker,)

    def unavailable_reason(self) -> str | None:
        return None if self.is_available() else self._blocker

    def health_check(self) -> OcrEngineHealth:
        ok = self.is_available()
        return OcrEngineHealth(
            ok=ok,
            detail="available" if ok else self._blocker,
            engine=self.name,
            readiness_status="ready" if ok else self.readiness_status(),
            readiness_blockers=() if ok else self.readiness_blockers(),
        )


def test_public_ocr_status_readiness_matches_engine_health_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """public_ocr_status readiness must mirror each engine's health_check result.

    ``public_ocr_status`` advertises per-engine ``readiness_status``/``available``
    derived from ``readiness_status()``, while ``health_check()`` is a separate
    Protocol method that QA, MCP, and status surfaces also trust. Nothing pinned
    the two paths together, so an engine could report ``dependency_missing`` in
    status while ``health_check`` claimed ``ready`` (or vice versa) and CI would
    stay green. This forces an available and an unavailable engine and asserts
    the status-surface readiness equals the engine's own health_check, without
    invoking any real built-in health_check that could run a local OCR probe.
    """

    monkeypatch.setattr(
        "pdf_backends.ocr_engine_registry.load_builtin_ocr_engines", lambda: None
    )
    available_engine = _HealthAlignedMockOcrEngine(
        "mock_ready", available=True, blocker="unused"
    )
    unavailable_engine = _HealthAlignedMockOcrEngine(
        "mock_missing", available=False, blocker="mock runtime dependency missing"
    )
    register_ocr_engine("mock_ready", lambda config: available_engine)
    register_ocr_engine("mock_missing", lambda config: unavailable_engine)

    status = public_ocr_status(OcrRuntimeConfig(policy="auto"))
    status_by_name = {item["name"]: item for item in status["available_engines"]}
    assert {"mock_ready", "mock_missing"} <= set(status_by_name)

    for engine in (available_engine, unavailable_engine):
        health = engine.health_check()
        item = status_by_name[engine.name]
        assert health.engine == engine.name
        assert item["available"] is health.ok
        assert item["readiness_status"] == health.readiness_status
        assert item["readiness_blockers"] == list(health.readiness_blockers)

    # Negative self-check: an engine whose status-surface readiness drifts from
    # its health_check must be caught, proving the contract has teeth.
    drifted = _HealthAlignedMockOcrEngine(
        "mock_drift", available=False, blocker="drift blocker"
    )
    monkeypatch.setattr(
        drifted,
        "health_check",
        lambda: OcrEngineHealth(
            ok=True,
            detail="claims ready",
            engine="mock_drift",
            readiness_status="ready",
        ),
    )
    register_ocr_engine("mock_drift", lambda config: drifted)
    drift_status = public_ocr_status(OcrRuntimeConfig(policy="auto"))
    drift_item = {
        item["name"]: item for item in drift_status["available_engines"]
    }["mock_drift"]
    drift_health = drifted.health_check()
    assert drift_item["readiness_status"] != drift_health.readiness_status


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


class _NamedMockOcrEngine(_MockOcrEngine):
    """Configurable mock whose engine id matches its registry name.

    Used to stage several simultaneously-available engines under the real
    ``_AUTO_PRIORITY`` ids so the deterministic auto-selection order can be
    asserted by name without importing heavy optional OCR runtimes.
    """

    def __init__(self, name: str, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config)
        self.name = name


def _register_named_available(name: str) -> None:
    register_ocr_engine(
        name, lambda config, _n=name: _NamedMockOcrEngine(_n, {"available": True})
    )


# Pinned expected auto-selection order. Kept independent of the product tuple so
# a reordered or truncated _AUTO_PRIORITY fails the equality assertion below
# instead of silently re-deriving the "expected" order from the changed value.
_EXPECTED_AUTO_PRIORITY = ("paddleocr_gpu", "rapidocr", "windows", "remote_api")


def test_auto_policy_follows_deterministic_priority_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto policy must pick engines in the fixed ``_AUTO_PRIORITY`` order.

    select_ocr_engine(policy="auto") iterates _AUTO_PRIORITY and returns the
    first *available* engine. With only the single-engine happy-path test, a
    scrambled priority tuple or a wrong tie-break would still pass CI while
    silently changing which OCR engine real ingestion runs. This stages every
    priority id as simultaneously available and then removes the front of the
    order one id at a time, asserting the selected engine walks the tuple
    deterministically.

    The built-in loader re-registers the real optional engines over any same-id
    factory (see test_builtin_load_overwrites_same_id_registration), and their
    real availability depends on the host. To keep this an environment-independent
    contract over the ordering logic itself, the loader is neutralized so the
    staged mocks survive and every priority id is forced available.
    """

    # Pin the concrete order first so a reordered/truncated product tuple fails
    # here rather than being treated as the new "expected" order.
    assert _AUTO_PRIORITY == _EXPECTED_AUTO_PRIORITY

    monkeypatch.setattr(
        "pdf_backends.ocr_engine_registry.load_builtin_ocr_engines", lambda: None
    )

    # All priority ids available -> the highest-priority id must win.
    for name in _EXPECTED_AUTO_PRIORITY:
        _register_named_available(name)
    engine, warning = select_ocr_engine(OcrRuntimeConfig(policy="auto"))
    assert warning is None
    assert engine is not None
    assert engine.name == _EXPECTED_AUTO_PRIORITY[0]

    # Dropping the current front each time must fall through to the next id in
    # priority order, never to a lower-priority id while a higher one remains.
    for index in range(1, len(_EXPECTED_AUTO_PRIORITY)):
        clear_ocr_engines_for_tests()
        monkeypatch.setattr(
            "pdf_backends.ocr_engine_registry.load_builtin_ocr_engines", lambda: None
        )
        remaining = _EXPECTED_AUTO_PRIORITY[index:]
        for name in remaining:
            _register_named_available(name)
        engine, warning = select_ocr_engine(OcrRuntimeConfig(policy="auto"))
        assert warning is None
        assert engine is not None
        assert engine.name == remaining[0], (index, remaining)


def test_builtin_load_overwrites_same_id_registration() -> None:
    """Built-in loading must own the canonical built-in engine ids.

    load_builtin_ocr_engines() unconditionally re-registers the real optional
    engines, so any earlier same-id factory is replaced once built-ins load.
    This pins that documented precedence: a caller cannot shadow a built-in id
    such as ``paddleocr_gpu`` with a different implementation by registering it
    first, which is why the priority-order test neutralizes the loader instead
    of registering mocks under built-in ids.
    """

    register_ocr_engine(
        "paddleocr_gpu", lambda config: _NamedMockOcrEngine("paddleocr_gpu", config)
    )
    load_builtin_ocr_engines()
    rebuilt = build_ocr_engine("paddleocr_gpu", {}, include_builtins=False)
    assert isinstance(rebuilt, PaddleOcrGpuEngine)
    assert not isinstance(rebuilt, _NamedMockOcrEngine)


def test_auto_priority_covers_every_registered_builtin_engine() -> None:
    """Every built-in OCR engine id must appear in ``_AUTO_PRIORITY``.

    The auto policy can only select ids listed in _AUTO_PRIORITY. If a new
    built-in engine is registered in load_builtin_ocr_engines() but is not added
    to _AUTO_PRIORITY, it becomes permanently unreachable under policy="auto"
    even when available, with no other test catching the regression. This guard
    pins the two-way relationship: every registered built-in is reachable, and
    _AUTO_PRIORITY does not reference ids that no longer exist.
    """

    load_builtin_ocr_engines()
    builtin_names = set(list_ocr_engine_names(include_builtins=True))
    priority_names = set(_AUTO_PRIORITY)

    unreachable = sorted(builtin_names - priority_names)
    assert not unreachable, unreachable

    stale = sorted(priority_names - builtin_names)
    assert not stale, stale

    # The priority tuple must list each id once so ordering is unambiguous.
    assert len(_AUTO_PRIORITY) == len(set(_AUTO_PRIORITY))


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
