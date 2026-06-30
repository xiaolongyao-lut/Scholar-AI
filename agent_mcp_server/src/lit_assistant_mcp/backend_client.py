"""HTTP client for Literature Assistant backend with circuit breaker."""

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .repo_root import is_repo_root

DESKTOP_RUNTIME_FILENAME = "desktop-runtime.json"


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject immediately
    HALF_OPEN = "half_open"  # Testing recovery


class BackendClient:
    """HTTP client with timeouts and circuit breaker."""

    def __init__(
        self,
        base_url: str | None = None,
        capability_file: str | Path | None = None,
        fail_max: int = 3,
        reset_timeout_sec: int = 30,
        connect_timeout_sec: int = 2,
        read_timeout_sec: int = 15,
    ) -> None:
        """Initialize backend client.

        Args:
            base_url: Backend base URL. ``None`` defers to runtime discovery.
            capability_file: Runtime capability JSON file written by the backend
            fail_max: Max consecutive failures before opening circuit
            reset_timeout_sec: Seconds to wait before trying half-open
            connect_timeout_sec: Connection timeout
            read_timeout_sec: Read timeout
        """
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise ValueError("base_url must be a non-empty string or None")
        if not isinstance(fail_max, int) or fail_max < 1:
            raise ValueError("fail_max must be an integer >= 1")
        if not isinstance(reset_timeout_sec, int) or reset_timeout_sec < 1:
            raise ValueError("reset_timeout_sec must be an integer >= 1")
        if not isinstance(connect_timeout_sec, int) or connect_timeout_sec < 1:
            raise ValueError("connect_timeout_sec must be an integer >= 1")
        if not isinstance(read_timeout_sec, int) or read_timeout_sec < 1:
            raise ValueError("read_timeout_sec must be an integer >= 1")

        self._configured_base_url = base_url.rstrip("/") if isinstance(base_url, str) else None
        self.base_url = ""
        self._configured_capability_file = capability_file
        self.fail_max = fail_max
        self.reset_timeout_sec = reset_timeout_sec
        self.connect_timeout_sec = connect_timeout_sec
        self.read_timeout_sec = read_timeout_sec
        self.capability_file = _resolve_capability_file(capability_file)

        self.state = CircuitState.CLOSED
        self.fail_count = 0
        self.last_fail_time: float | None = None

        self.client: httpx.Client | None = None

    def _ensure_client(self) -> tuple[httpx.Client | None, dict[str, Any] | None]:
        """Return an HTTP client for the current runtime descriptor."""
        next_base_url = _resolve_backend_base_url(self._configured_base_url)
        if next_base_url is None:
            return None, {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": (
                    "Literature Assistant backend is not attached. Start the desktop app, then share "
                    "or set the terminal line LITERATURE_ASSISTANT_BASE_URL=http://127.0.0.1:<port>."
                ),
                "data": None,
            }
        if self.client is not None and self.base_url == next_base_url:
            return self.client, None
        if self.client is not None:
            self.client.close()
        self.base_url = next_base_url
        self.capability_file = _resolve_capability_file(self._configured_capability_file)
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                connect=self.connect_timeout_sec,
                read=self.read_timeout_sec,
                write=5.0,
                pool=5.0,
            ),
        )
        return self.client, None

    def _capability_headers(self) -> dict[str, str]:
        """Return local API capability headers for loopback backends only."""
        if not _is_loopback_http_url(self.base_url):
            return {}
        capability = _read_capability_file(self.capability_file)
        if capability is None:
            return {}
        return {capability.header: capability.token}

    def _should_attempt(self) -> tuple[bool, str | None]:
        """Check if request should be attempted."""
        if self.state == CircuitState.CLOSED:
            return True, None

        if self.state == CircuitState.OPEN:
            # Check if reset timeout elapsed
            if (
                self.last_fail_time is not None
                and time.time() - self.last_fail_time >= self.reset_timeout_sec
            ):
                self.state = CircuitState.HALF_OPEN
                return True, None
            return False, "backend_circuit_open"

        # HALF_OPEN: allow one test request
        return True, None

    def _record_success(self) -> None:
        """Record successful request."""
        self.fail_count = 0
        self.state = CircuitState.CLOSED

    def _record_failure(self) -> None:
        """Record failed request."""
        self.fail_count += 1
        self.last_fail_time = time.time()

        if self.fail_count >= self.fail_max:
            self.state = CircuitState.OPEN

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform GET request.

        Args:
            path: URL path (e.g., "/health")
            params: Query parameters

        Returns:
            Structured result with error codes on failure
        """
        should_attempt, error_code = self._should_attempt()
        if not should_attempt:
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Circuit breaker is open (state={self.state.value})",
                "data": None,
            }
        client, setup_error = self._ensure_client()
        if setup_error is not None or client is None:
            self._record_failure()
            return setup_error or {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        try:
            response = client.get(path, params=params, headers=self._capability_headers())
            response.raise_for_status()
            self._record_success()

            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": response.json(),
            }

        except ValueError:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_openapi_mismatch",
                "message": "Backend returned non-JSON response",
                "data": None,
            }

        except httpx.ConnectError:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        except httpx.TimeoutException:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_timeout",
                "message": "Backend request timed out",
                "data": None,
            }

        except httpx.HTTPStatusError as e:
            self._record_failure()
            error_code = _classify_http_error(e.response)
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Backend returned {e.response.status_code}",
                "data": None,
            }

        except Exception as e:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unknown_error",
                "message": str(e),
                "data": None,
            }

    def get_text(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform GET request expecting a text response.

        Args:
            path: URL path (e.g., "/api/annotations/id/export.md")
            params: Query parameters

        Returns:
            Structured result with text data or error codes on failure
        """
        should_attempt, error_code = self._should_attempt()
        if not should_attempt:
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Circuit breaker is open (state={self.state.value})",
                "data": None,
            }
        client, setup_error = self._ensure_client()
        if setup_error is not None or client is None:
            self._record_failure()
            return setup_error or {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        try:
            response = client.get(path, params=params, headers=self._capability_headers())
            response.raise_for_status()
            self._record_success()

            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": response.text,
            }

        except httpx.ConnectError:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        except httpx.TimeoutException:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_timeout",
                "message": "Backend request timed out",
                "data": None,
            }

        except httpx.HTTPStatusError as e:
            self._record_failure()
            error_code = _classify_http_error(e.response)
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Backend returned {e.response.status_code}",
                "data": None,
            }

        except Exception as e:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unknown_error",
                "message": str(e),
                "data": None,
            }

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform POST request expecting a JSON response.

        Args:
            path: URL path such as ``/chat/ask``.
            payload: JSON object sent to the backend.
            params: Optional query parameters.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        should_attempt, error_code = self._should_attempt()
        if not should_attempt:
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Circuit breaker is open (state={self.state.value})",
                "data": None,
            }
        client, setup_error = self._ensure_client()
        if setup_error is not None or client is None:
            self._record_failure()
            return setup_error or {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        try:
            response = client.post(
                path,
                params=params,
                json=payload,
                headers=self._capability_headers(),
            )
            response.raise_for_status()
            self._record_success()

            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": response.json(),
            }

        except ValueError:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_openapi_mismatch",
                "message": "Backend returned non-JSON response",
                "data": None,
            }

        except httpx.ConnectError:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        except httpx.TimeoutException:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_timeout",
                "message": "Backend request timed out",
                "data": None,
            }

        except httpx.HTTPStatusError as e:
            self._record_failure()
            error_code = _classify_http_error(e.response)
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Backend returned {e.response.status_code}",
                "data": None,
            }

        except Exception as e:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unknown_error",
                "message": str(e),
                "data": None,
            }

    def post_binary(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform POST request expecting a binary response.

        Args:
            path: URL path such as ``/api/export/docx``.
            payload: JSON object sent to the backend.
            params: Optional query parameters.

        Returns:
            Structured result whose data contains bytes and response headers.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        should_attempt, error_code = self._should_attempt()
        if not should_attempt:
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Circuit breaker is open (state={self.state.value})",
                "data": None,
            }
        client, setup_error = self._ensure_client()
        if setup_error is not None or client is None:
            self._record_failure()
            return setup_error or {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        try:
            response = client.post(
                path,
                params=params,
                json=payload,
                headers=self._capability_headers(),
            )
            response.raise_for_status()
            self._record_success()
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "content": response.content,
                    "headers": dict(response.headers),
                    "status_code": response.status_code,
                },
            }

        except httpx.ConnectError:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unavailable",
                "message": "Backend is not reachable",
                "data": None,
            }

        except httpx.TimeoutException:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_timeout",
                "message": "Backend request timed out",
                "data": None,
            }

        except httpx.HTTPStatusError as e:
            self._record_failure()
            error_code = _classify_http_error(e.response)
            return {
                "is_error": True,
                "error_code": error_code,
                "message": f"Backend returned {e.response.status_code}",
                "data": None,
            }

        except Exception as e:
            self._record_failure()
            return {
                "is_error": True,
                "error_code": "backend_unknown_error",
                "message": str(e),
                "data": None,
            }

    def close(self) -> None:
        """Close underlying HTTP client."""
        if self.client is not None:
            self.client.close()


class LocalApiCapability:
    """Runtime token shape read from the backend capability file."""

    def __init__(self, header: str, token: str) -> None:
        """Create a capability record.

        Args:
            header: HTTP header name expected by the backend.
            token: Process-local capability token.
        """
        if not isinstance(header, str) or not header.strip():
            raise ValueError("header must be a non-empty string")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        self.header = header.strip()
        self.token = token.strip()


def _is_loopback_http_url(value: str) -> bool:
    """Return whether a URL points at a local HTTP backend.

    Args:
        value: Base URL configured for the Literature Assistant backend.
    """
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and hostname in {"localhost", "127.0.0.1", "::1"}


def _find_repo_root(start: Path | None = None) -> Path | None:
    """Find the active workspace root without importing product modules."""
    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd().resolve())
    except OSError:
        pass
    current = (start or Path(__file__)).resolve()
    candidates.append(current)
    candidates.extend(current.parents)
    for candidate in candidates:
        if is_repo_root(candidate):
            return candidate
    return None


def _runtime_state_root() -> Path | None:
    """Return the configured runtime-state root without importing backend code."""
    runtime_root = os.environ.get("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", "").strip()
    if runtime_root:
        return Path(runtime_root).expanduser().resolve()

    user_root = os.environ.get("LITERATURE_ASSISTANT_USER_ROOT", "").strip()
    if user_root:
        return Path(user_root).expanduser().resolve() / "runtime_state"

    repo_root = _find_repo_root()
    if repo_root is None:
        return None
    return repo_root / "workspace_artifacts" / "runtime_state"


def _descriptor_file() -> Path | None:
    """Return the desktop-runtime descriptor path used for port discovery."""
    explicit = os.environ.get("LITASSIST_DESKTOP_RUNTIME_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    runtime_root = _runtime_state_root()
    if runtime_root is None:
        return None
    return runtime_root / DESKTOP_RUNTIME_FILENAME


def _read_runtime_descriptor() -> dict[str, Any] | None:
    """Read a healthy-enough desktop descriptor for local MCP attachment."""
    descriptor = _descriptor_file()
    if descriptor is None or not descriptor.is_file():
        return None
    try:
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("ready") is not True or payload.get("process_kind") != "desktop":
        return None
    pid = _coerce_pid(payload.get("pid"))
    if pid is None or not _pid_exists(pid):
        return None
    return payload


def _resolve_backend_base_url(configured_base_url: str | None) -> str | None:
    """Resolve the current backend URL from explicit config or runtime state."""
    if configured_base_url is not None:
        return configured_base_url.rstrip("/")

    env_base_url = os.environ.get("LITERATURE_ASSISTANT_BASE_URL", "").strip()
    if env_base_url:
        return env_base_url.rstrip("/")

    descriptor = _read_runtime_descriptor()
    if descriptor is None:
        return None
    base_url = str(descriptor.get("base_url") or "").strip().rstrip("/")
    if not base_url or not _is_loopback_http_url(base_url):
        return None
    return base_url


def _resolve_capability_file(value: str | Path | None) -> Path:
    """Resolve the runtime API capability file used by local launchers."""
    explicit = value if value is not None else os.environ.get("LITASSIST_API_CAPABILITY_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    descriptor = _read_runtime_descriptor()
    if descriptor is not None:
        capability_file = str(descriptor.get("capability_file") or "").strip()
        if capability_file:
            return Path(capability_file).expanduser().resolve()

    runtime_root = _runtime_state_root()
    if runtime_root is not None:
        return runtime_root / "api-capability.json"

    return Path("workspace_artifacts/runtime_state/api-capability.json").resolve()


def _coerce_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_capability_file(path: Path) -> LocalApiCapability | None:
    """Read and validate the backend runtime capability file.

    Args:
        path: JSON file containing ``header`` and ``token`` fields.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    header = payload.get("header")
    token = payload.get("token")
    if not isinstance(header, str) or not isinstance(token, str):
        return None
    try:
        return LocalApiCapability(header=header, token=token)
    except ValueError:
        return None


def _classify_http_error(response: httpx.Response) -> str:
    """Map backend HTTP failures into stable MCP-facing error codes."""
    if response.status_code == 404:
        return "backend_not_found"
    if response.status_code == 413:
        return "backend_payload_too_large"
    if response.status_code == 403:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("code") == "LOCAL_API_CAPABILITY_REQUIRED":
                return "backend_capability_required"
    return "backend_bad_response"
