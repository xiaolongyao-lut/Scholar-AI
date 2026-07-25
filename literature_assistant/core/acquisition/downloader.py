"""Allowlisted, bounded, resumable open-access PDF downloader."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from .models import SourcePolicy, sanitize_public_https_url
from .validator import DEFAULT_MAX_PDF_BYTES, PdfValidationResult, validate_pdf_file


_STREAM_CHUNK_BYTES = 1024 * 1024
_MAX_REDIRECTS = 5
_STOP_STATUS_GATE = {
    401: "http_401",
    403: "http_403",
    407: "http_407",
    429: "http_429",
    503: "http_503",
}
DownloadControl = Literal["continue", "pause", "cancel"]
Resolver = Callable[[str], Sequence[str]]
ControlProbe = Callable[[], DownloadControl]
PromotionRecorder = Callable[[str, PdfValidationResult], None]


class DownloadPolicyError(ValueError):
    """Raised before transfer when URL, host, DNS, or path policy fails."""


class DownloadTransferError(RuntimeError):
    """Bounded retryable or terminal transfer failure."""

    def __init__(self, code: str, message: str, *, bytes_downloaded: int = 0) -> None:
        super().__init__(message)
        self.code = str(code or "download_failed")[:80]
        self.safe_message = str(message or "download failed").replace("\n", " ")[:500]
        self.bytes_downloaded = max(0, int(bytes_downloaded))


class DownloadHumanGateRequired(DownloadTransferError):
    """Automatic access must stop and hand ownership to the user."""

    def __init__(self, gate_type: str, url: str, message: str) -> None:
        super().__init__("human_gate_required", message)
        self.gate_type = gate_type
        self.url = url


class DownloadPaused(DownloadTransferError):
    """Cooperative pause preserving the adjacent partial file."""

    def __init__(self, bytes_downloaded: int) -> None:
        super().__init__("paused", "Download paused by explicit control.", bytes_downloaded=bytes_downloaded)


class DownloadCancelled(DownloadTransferError):
    """Cooperative cancellation that removes the partial file."""

    def __init__(self, bytes_downloaded: int) -> None:
        super().__init__("cancelled", "Download cancelled by explicit control.", bytes_downloaded=bytes_downloaded)


@dataclass(frozen=True, slots=True)
class DownloadedPdf:
    """Validated final file produced immediately after atomic promotion."""

    path: Path
    final_url: str
    validation: PdfValidationResult


@dataclass(frozen=True, slots=True)
class _ContentRange:
    start: int
    end: int
    total: int | None

    @property
    def segment_bytes(self) -> int:
        return self.end - self.start + 1


def resolve_public_addresses(host: str) -> tuple[str, ...]:
    """Resolve all addresses for a host using the system resolver."""

    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DownloadPolicyError("download host DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise DownloadPolicyError("download host did not resolve")
    return addresses


def validate_download_url(
    url: str,
    *,
    allowed_hosts: Sequence[str],
    resolver: Resolver = resolve_public_addresses,
) -> str:
    """Validate HTTPS, exact host allowlist, and exclusively public DNS."""

    normalized = sanitize_public_https_url(url, field_name="download_url")
    host = (urlsplit(normalized).hostname or "").lower()
    exact_hosts = frozenset(str(item).strip().rstrip(".").lower() for item in allowed_hosts)
    if host not in exact_hosts:
        raise DownloadPolicyError("download host is not allowlisted")
    try:
        addresses = tuple(resolver(host))
    except DownloadPolicyError:
        raise
    except Exception as exc:
        raise DownloadPolicyError("download host DNS resolution failed") from exc
    if not addresses:
        raise DownloadPolicyError("download host did not resolve")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise DownloadPolicyError("download host resolved to an invalid address") from exc
        if not address.is_global or address.is_multicast or address.is_unspecified:
            raise DownloadPolicyError("download host must resolve only to public unicast addresses")
    return normalized


async def download_validated_pdf(
    *,
    source_url: str,
    policy: SourcePolicy,
    destination: str | Path,
    project_root: str | Path,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver = resolve_public_addresses,
    control_probe: ControlProbe | None = None,
    record_promotion: PromotionRecorder | None = None,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> DownloadedPdf:
    """Download, validate, and atomically promote one allowlisted OA PDF.

    Args:
        source_url: Exact URL bound to reviewed ``AccessEvidence``.
        policy: Source policy whose download hosts/evidence were checked by the
            service before this function is called.
        destination: Collision-safe final ``.pdf`` path.
        project_root: Canonical project directory containing ``destination``.
        client: Optional injected HTTPX client for local fixture tests.
        resolver: Injectable DNS resolver returning all addresses.
        control_probe: Cooperative pause/cancel state probe.
        record_promotion: Durable proof callback invoked after validation and
            before the adjacent partial file is atomically promoted.
        max_bytes: Hard streamed and structural size limit.

    Returns:
        Final path and structural validation evidence.

    Raises:
        DownloadPolicyError: Before transfer for path/URL/DNS violations.
        DownloadHumanGateRequired: For access gates or HTML responses.
        DownloadPaused: When an explicit pause is observed.
        DownloadCancelled: When an explicit cancellation is observed.
        DownloadTransferError: For bounded transport/validation failures.
    """

    if "download" not in policy.capabilities or not policy.enabled:
        raise DownloadPolicyError("source policy does not allow downloads")
    if policy.requires_authentication:
        raise DownloadPolicyError("authenticated sources require a visible browser route")
    if max_bytes < 4096 or max_bytes > DEFAULT_MAX_PDF_BYTES:
        raise ValueError(f"max_bytes must be between 4096 and {DEFAULT_MAX_PDF_BYTES}")
    target = validate_download_destination(destination, project_root)
    part = target.with_name(f"{target.name}.part")
    if target.exists():
        raise DownloadPolicyError("download destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    _partial_file_size(part)
    current_url = validate_download_url(source_url, allowed_hosts=policy.download_hosts, resolver=resolver)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"User-Agent": "ScholarAI/0.1.8.4 compliant-open-access-client"},
    )
    try:
        result = await _stream_with_redirects(
            client=http_client,
            initial_url=current_url,
            policy=policy,
            part=part,
            target=target,
            resolver=resolver,
            control_probe=control_probe,
            record_promotion=record_promotion,
            max_bytes=max_bytes,
        )
        return result
    finally:
        if owns_client:
            await http_client.aclose()


async def _stream_with_redirects(
    *,
    client: httpx.AsyncClient,
    initial_url: str,
    policy: SourcePolicy,
    part: Path,
    target: Path,
    resolver: Resolver,
    control_probe: ControlProbe | None,
    record_promotion: PromotionRecorder | None,
    max_bytes: int,
) -> DownloadedPdf:
    current_url = initial_url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        existing_size = _partial_file_size(part)
        if existing_size > max_bytes:
            _unlink_quietly(part)
            raise DownloadTransferError("partial_too_large", "Partial PDF exceeds the byte limit")
        headers = {"Accept": "application/pdf"}
        if existing_size:
            headers["Range"] = f"bytes={existing_size}-"
        try:
            async with client.stream(
                "GET",
                current_url,
                headers=headers,
                follow_redirects=False,
            ) as response:
                if response.status_code in _STOP_STATUS_GATE:
                    raise DownloadHumanGateRequired(
                        _STOP_STATUS_GATE[response.status_code],
                        current_url,
                        f"Source returned HTTP {response.status_code}; automatic access stopped.",
                    )
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_count >= _MAX_REDIRECTS:
                        raise DownloadTransferError("redirect_limit", "PDF redirect limit exceeded")
                    location = response.headers.get("location", "").strip()
                    if not location:
                        raise DownloadTransferError("redirect_missing_location", "PDF redirect omitted Location")
                    redirected = urljoin(current_url, location)
                    current_url = validate_download_url(
                        redirected,
                        allowed_hosts=policy.download_hosts,
                        resolver=resolver,
                    )
                    continue
                if response.status_code == 416 and existing_size:
                    _validate_unsatisfied_content_range(
                        response.headers.get("content-range", ""),
                        existing_size,
                    )
                    return _validate_and_promote(
                        part,
                        target,
                        current_url,
                        record_promotion=record_promotion,
                        max_bytes=max_bytes,
                    )
                if response.status_code not in {200, 206}:
                    raise DownloadTransferError(
                        "http_error",
                        f"PDF source returned HTTP {response.status_code}",
                        bytes_downloaded=existing_size,
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type in {"text/html", "application/xhtml+xml"}:
                    raise DownloadHumanGateRequired(
                        "html_instead_of_pdf",
                        current_url,
                        "PDF route returned HTML; automatic access stopped.",
                    )
                if content_type != "application/pdf":
                    raise DownloadTransferError("unexpected_content_type", "PDF route did not return application/pdf")

                append = response.status_code == 206 and existing_size > 0
                content_range: _ContentRange | None = None
                if response.status_code == 206:
                    content_range = _validate_content_range(
                        response.headers.get("content-range", ""),
                        existing_size,
                        max_bytes=max_bytes,
                    )
                else:
                    existing_size = 0
                declared_bytes = _parse_content_length(response.headers.get("content-length"))
                if declared_bytes is not None:
                    if content_range is not None and declared_bytes != content_range.segment_bytes:
                        raise DownloadTransferError(
                            "invalid_content_range",
                            "PDF resume response length disagrees with Content-Range",
                        )
                    projected = existing_size + declared_bytes
                    if projected > max_bytes:
                        raise DownloadTransferError("response_too_large", "PDF exceeds the configured byte limit")
                await _write_response(
                    response,
                    part=part,
                    append=append,
                    initial_size=existing_size,
                    control_probe=control_probe,
                    max_bytes=max_bytes,
                    current_url=current_url,
                )
                final_size = _partial_file_size(part)
                if content_range is not None and content_range.total is not None:
                    if final_size != content_range.total:
                        raise DownloadTransferError(
                            "incomplete_content_range",
                            "PDF resume response did not complete the declared representation",
                            bytes_downloaded=final_size,
                        )
                return _validate_and_promote(
                    part,
                    target,
                    current_url,
                    record_promotion=record_promotion,
                    max_bytes=max_bytes,
                )
        except (DownloadHumanGateRequired, DownloadPaused, DownloadCancelled, DownloadPolicyError, DownloadTransferError):
            raise
        except httpx.HTTPError as exc:
            raise DownloadTransferError(
                "transport_error",
                "PDF transfer failed",
                bytes_downloaded=part.stat().st_size if part.exists() else 0,
            ) from exc
    raise DownloadTransferError("redirect_limit", "PDF redirect limit exceeded")


async def _write_response(
    response: httpx.Response,
    *,
    part: Path,
    append: bool,
    initial_size: int,
    control_probe: ControlProbe | None,
    max_bytes: int,
    current_url: str,
) -> None:
    mode = "ab" if append else "wb"
    total = initial_size
    prefix = bytearray()
    try:
        with part.open(mode) as handle:
            async for chunk in response.aiter_bytes(_STREAM_CHUNK_BYTES):
                action = control_probe() if control_probe is not None else "continue"
                if action == "pause":
                    handle.flush()
                    os.fsync(handle.fileno())
                    raise DownloadPaused(total)
                if action == "cancel":
                    handle.close()
                    _unlink_quietly(part)
                    raise DownloadCancelled(total)
                if action != "continue":
                    raise DownloadTransferError("invalid_control", "Download control returned an invalid state")
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadTransferError("response_too_large", "PDF exceeds the configured byte limit", bytes_downloaded=total)
                if len(prefix) < 4096:
                    prefix.extend(chunk[: 4096 - len(prefix)])
                    gate_type = _html_gate_type(bytes(prefix))
                    if gate_type is not None:
                        handle.close()
                        _unlink_quietly(part)
                        raise DownloadHumanGateRequired(
                            gate_type,
                            current_url,
                            "PDF route returned an access page; automatic access stopped.",
                        )
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except (DownloadHumanGateRequired, DownloadPaused, DownloadCancelled, DownloadTransferError):
        raise
    except OSError as exc:
        raise DownloadTransferError("write_failed", "Unable to persist partial PDF", bytes_downloaded=total) from exc


def _validate_and_promote(
    part: Path,
    target: Path,
    final_url: str,
    *,
    record_promotion: PromotionRecorder | None,
    max_bytes: int,
) -> DownloadedPdf:
    try:
        validation = validate_pdf_file(part, max_bytes=max_bytes)
    except ValueError as exc:
        raise DownloadTransferError(
            "invalid_pdf",
            str(exc),
            bytes_downloaded=part.stat().st_size if part.exists() else 0,
        ) from exc
    if target.exists():
        raise DownloadPolicyError("download destination appeared during transfer")
    if record_promotion is not None:
        record_promotion(final_url, validation)
    try:
        os.replace(part, target)
    except OSError as exc:
        raise DownloadTransferError("atomic_promote_failed", "Unable to promote validated PDF") from exc
    return DownloadedPdf(path=target, final_url=final_url, validation=validation)


def validate_download_destination(destination: str | Path, project_root: str | Path) -> Path:
    """Return a canonical project-local regular PDF destination.

    Args:
        destination: Candidate final PDF path.
        project_root: Canonical project directory that must contain the file.

    Returns:
        The resolved destination path.

    Raises:
        DownloadPolicyError: If the path escapes the project, is not a PDF,
            or resolves through an unsafe final path.
    """

    root = Path(project_root).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if root == target or root not in target.parents:
        raise DownloadPolicyError("download destination must stay inside the project directory")
    if target.suffix.lower() != ".pdf":
        raise DownloadPolicyError("download destination must use .pdf")
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise DownloadPolicyError("download destination is not a regular file")
    if target.parent.exists() and target.parent.is_symlink():
        raise DownloadPolicyError("download destination parent must not be a symlink")
    return target


def _validate_content_range(
    value: str,
    expected_start: int,
    *,
    max_bytes: int,
) -> _ContentRange:
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", str(value or "").strip(), flags=re.IGNORECASE)
    if match is None:
        raise DownloadTransferError("invalid_content_range", "PDF resume response has an invalid Content-Range")
    start = int(match.group(1))
    end = int(match.group(2))
    total = None if match.group(3) == "*" else int(match.group(3))
    if start != expected_start or end < start:
        raise DownloadTransferError("invalid_content_range", "PDF resume response has an invalid Content-Range")
    if total is not None:
        if total <= end or total > max_bytes:
            raise DownloadTransferError("invalid_content_range", "PDF resume response has an invalid total size")
    return _ContentRange(start=start, end=end, total=total)


def _validate_unsatisfied_content_range(value: str, existing_size: int) -> None:
    match = re.fullmatch(r"bytes\s+\*/(\d+)", str(value or "").strip(), flags=re.IGNORECASE)
    if match is None or int(match.group(1)) != existing_size:
        raise DownloadTransferError(
            "invalid_content_range",
            "PDF range rejection did not prove the partial file is complete",
            bytes_downloaded=existing_size,
        )


def _parse_content_length(value: str | None) -> int | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        declared = int(normalized)
    except ValueError as exc:
        raise DownloadTransferError("invalid_content_length", "PDF Content-Length is invalid") from exc
    if declared < 0:
        raise DownloadTransferError("invalid_content_length", "PDF Content-Length is invalid")
    return declared


def _partial_file_size(part: Path) -> int:
    try:
        if part.is_symlink():
            raise DownloadPolicyError("download partial file must not be a symlink")
        if not part.exists():
            return 0
        if not part.is_file():
            raise DownloadPolicyError("download partial path must be a regular file")
        return part.stat().st_size
    except DownloadPolicyError:
        raise
    except OSError as exc:
        raise DownloadTransferError("partial_inspection_failed", "Unable to inspect partial PDF") from exc


def _html_gate_type(prefix: bytes) -> str | None:
    text = prefix.decode("utf-8", errors="ignore").casefold()
    if "<html" not in text and "<!doctype html" not in text:
        return None
    if "captcha" in text:
        return "captcha"
    if "cloudflare" in text:
        return "cloudflare"
    if "paywall" in text or "purchase access" in text:
        return "paywall"
    if "sign in" in text or "log in" in text or "login" in text:
        return "login"
    if "robots" in text:
        return "robots"
    return "html_instead_of_pdf"


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
