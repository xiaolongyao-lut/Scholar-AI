"""Tests for BackendClient with circuit breaker."""

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from lit_assistant_mcp.backend_client import BackendClient, CircuitState

DEFAULT_TEST_BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.Client for testing."""
    with patch("lit_assistant_mcp.backend_client.httpx.Client") as mock:
        yield mock


def test_circuit_breaker_opens_after_failures(mock_httpx_client):
    """Test that circuit breaker opens after fail_max failures."""
    # Setup mock to always raise ConnectError
    mock_instance = Mock()
    mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL, fail_max=3, reset_timeout_sec=30)

    # First 3 failures should increment fail_count
    for i in range(3):
        result = client.get("/health")
        assert result["is_error"] is True
        assert result["error_code"] == "backend_unavailable"

    # Circuit should now be OPEN
    assert client.state == CircuitState.OPEN

    # Next request should fail immediately without attempting
    result = client.get("/health")
    assert result["is_error"] is True
    assert result["error_code"] == "backend_circuit_open"
    assert "Circuit breaker is open" in result["message"]


def test_circuit_breaker_half_open_after_timeout(mock_httpx_client):
    """Test that circuit breaker enters half-open state after reset timeout."""
    # Setup mock to fail initially
    mock_instance = Mock()
    mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL, fail_max=3, reset_timeout_sec=1)

    # Trigger 3 failures to open circuit
    for _ in range(3):
        client.get("/health")

    assert client.state == CircuitState.OPEN

    # Wait for reset timeout
    time.sleep(1.1)

    # Now configure mock to succeed
    mock_response = Mock()
    mock_response.json.return_value = {"status": "healthy"}
    mock_instance.get = Mock(return_value=mock_response)

    # Next request should attempt (half-open)
    result = client.get("/health")

    # Should succeed and close circuit
    assert result["is_error"] is False
    assert client.state == CircuitState.CLOSED
    assert client.fail_count == 0


def test_backend_timeout_error(mock_httpx_client):
    """Test timeout error handling."""
    mock_instance = Mock()
    mock_instance.get.side_effect = httpx.TimeoutException("Request timeout")
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/health")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_timeout"


def test_backend_http_error(mock_httpx_client):
    """Test HTTP status error handling."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.status_code = 500
    mock_instance.get.side_effect = httpx.HTTPStatusError(
        "Server error", request=Mock(), response=mock_response
    )
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/health")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_bad_response"
    assert "500" in result["message"]


def test_backend_404_has_specific_error_code(mock_httpx_client):
    """Missing material/source-file responses should not look like schema failures."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.status_code = 404
    mock_instance.get.side_effect = httpx.HTTPStatusError(
        "Not found", request=Mock(), response=mock_response
    )
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/resources/document/mat-1/file_b64")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_not_found"


def test_backend_413_has_specific_error_code(mock_httpx_client):
    """Oversized file responses should be actionable for OCR callers."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.status_code = 413
    mock_instance.get.side_effect = httpx.HTTPStatusError(
        "Too large", request=Mock(), response=mock_response
    )
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/resources/document/mat-1/file_b64")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_payload_too_large"


def test_successful_request(mock_httpx_client):
    """Test successful request."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"status": "healthy", "version": "0.1.0"}
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/health")

    assert result["is_error"] is False
    assert result["error_code"] is None
    assert result["data"]["status"] == "healthy"


def test_runtime_descriptor_supplies_base_url_when_not_configured(
    mock_httpx_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP clients should attach to the visible desktop port without a fixed default."""

    runtime_root = tmp_path / "runtime_state"
    runtime_root.mkdir()
    capability_file = runtime_root / "api-capability.json"
    capability_file.write_text(
        json.dumps({"header": "X-LitAssist-Capability", "token": "local-token"}),
        encoding="utf-8",
    )
    descriptor_file = runtime_root / "desktop-runtime.json"
    descriptor_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pid": os.getpid(),
                "process_kind": "desktop",
                "base_url": "http://127.0.0.1:45678",
                "ready": True,
                "capability_file": str(capability_file),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", str(runtime_root))
    monkeypatch.delenv("LITERATURE_ASSISTANT_BASE_URL", raising=False)
    monkeypatch.delenv("LITASSIST_API_CAPABILITY_FILE", raising=False)
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"status": "healthy"}
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=None)
    result = client.get("/health")

    assert result["is_error"] is False
    assert mock_httpx_client.call_args.kwargs["base_url"] == "http://127.0.0.1:45678"
    assert mock_instance.get.call_args.kwargs["headers"] == {
        "X-LitAssist-Capability": "local-token"
    }


def test_unattached_runtime_has_actionable_message(
    mock_httpx_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing runtime state should ask for a pasted terminal base URL."""

    monkeypatch.setenv("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", str(tmp_path / "missing"))
    monkeypatch.delenv("LITERATURE_ASSISTANT_BASE_URL", raising=False)
    client = BackendClient(base_url=None)
    result = client.get("/health")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_unavailable"
    assert "LITERATURE_ASSISTANT_BASE_URL" in result["message"]
    mock_httpx_client.assert_not_called()


def test_successful_post_json_request(mock_httpx_client, tmp_path: Path):
    """POST JSON uses the same circuit and capability boundary as GET."""
    capability_file = tmp_path / "api-capability.json"
    capability_file.write_text(
        json.dumps({"header": "X-LitAssist-Capability", "token": "local-token"}),
        encoding="utf-8",
    )
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"answer": "ok"}
    mock_instance.post.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL, capability_file=capability_file)
    result = client.post_json("/chat/ask", payload={"query": "hello"})

    assert result["is_error"] is False
    assert result["data"]["answer"] == "ok"
    assert mock_instance.post.call_args.kwargs["json"] == {"query": "hello"}
    assert mock_instance.post.call_args.kwargs["headers"] == {
        "X-LitAssist-Capability": "local-token"
    }


def test_loopback_request_attaches_runtime_capability_header(mock_httpx_client, tmp_path: Path):
    """Test loopback backend requests include the local capability header."""
    capability_file = tmp_path / "api-capability.json"
    capability_file.write_text(
        json.dumps({"header": "X-LitAssist-Capability", "token": "local-token"}),
        encoding="utf-8",
    )
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"status": "ok"}
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(
        base_url="http://127.0.0.1:8000",
        capability_file=capability_file,
    )
    result = client.get("/resources/projects")

    assert result["is_error"] is False
    assert mock_instance.get.call_args.kwargs["headers"] == {
        "X-LitAssist-Capability": "local-token"
    }


def test_non_loopback_request_does_not_attach_capability_header(mock_httpx_client, tmp_path: Path):
    """Test capability tokens are never sent to non-loopback backends."""
    capability_file = tmp_path / "api-capability.json"
    capability_file.write_text(
        json.dumps({"header": "X-LitAssist-Capability", "token": "local-token"}),
        encoding="utf-8",
    )
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"status": "ok"}
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(
        base_url="https://example.invalid",
        capability_file=capability_file,
    )
    result = client.get("/resources/projects")

    assert result["is_error"] is False
    assert mock_instance.get.call_args.kwargs["headers"] == {}


def test_missing_capability_file_sends_no_header(mock_httpx_client, tmp_path: Path):
    """Test absent runtime capability file keeps requests usable for exempt routes."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"status": "ok"}
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(
        base_url="http://localhost:8000",
        capability_file=tmp_path / "missing.json",
    )
    result = client.get("/health")

    assert result["is_error"] is False
    assert mock_instance.get.call_args.kwargs["headers"] == {}


def test_non_json_response_returns_openapi_mismatch(mock_httpx_client):
    """Test non-JSON response handling for JSON endpoints."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.json.side_effect = ValueError("not json")
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/health")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_openapi_mismatch"


def test_capability_required_response_has_specific_error_code(mock_httpx_client):
    """Test local API guard errors are distinguishable from route failures."""
    mock_instance = Mock()
    response = httpx.Response(
        status_code=403,
        json={"error": {"code": "LOCAL_API_CAPABILITY_REQUIRED"}},
        request=httpx.Request("GET", "http://127.0.0.1:8000/resources/projects"),
    )
    mock_instance.get.side_effect = httpx.HTTPStatusError(
        "Forbidden",
        request=response.request,
        response=response,
    )
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get("/resources/projects")

    assert result["is_error"] is True
    assert result["error_code"] == "backend_capability_required"


def test_successful_text_request(mock_httpx_client):
    """Test successful text response."""
    mock_instance = Mock()
    mock_response = Mock()
    mock_response.text = "# Markdown"
    mock_instance.get.return_value = mock_response
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL)
    result = client.get_text("/api/annotations/mat-1/export.md")

    assert result["is_error"] is False
    assert result["data"] == "# Markdown"


def test_circuit_recovery_on_success(mock_httpx_client):
    """Test that successful request after failures resets circuit."""
    mock_instance = Mock()
    mock_httpx_client.return_value = mock_instance

    client = BackendClient(base_url=DEFAULT_TEST_BASE_URL, fail_max=3)

    # Fail twice
    mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
    client.get("/health")
    client.get("/health")
    assert client.fail_count == 2
    assert client.state == CircuitState.CLOSED

    # Succeed on third
    mock_response = Mock()
    mock_response.json.return_value = {"status": "ok"}
    mock_instance.get = Mock(return_value=mock_response)
    result = client.get("/health")

    assert result["is_error"] is False
    assert client.fail_count == 0
    assert client.state == CircuitState.CLOSED
