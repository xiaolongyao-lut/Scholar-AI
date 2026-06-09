"""MCP template installer.

Orchestrates scan → preview → install → probe → approval-advance, applying
the local install safety contract:

- install request references launch candidate by content sha, not index.
  Mismatched / stale sha → ``InstallCandidateMismatchError``.
- install record stores absolute cwd under
  ``workspace_artifacts/mcp_installs/<install_id>/``. (For directory sources
  the cwd is the source dir itself — the install_id dir holds the install
  manifest sidecar for delete-time cleanup.)
- probing the package launches its process and would expose the
  bound credentials to the package code. Probe is GATED behind
  ``trust_to_probe`` — without it, server is created at ``registered`` only
  and never spawned.

Failure modes are typed errors with stable codes so the router layer maps
them to deterministic HTTP responses.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from credential_store import CredentialNotFoundError, RuntimeCredentialStore
from extension_secret_policy import require_no_plaintext_secret_config
from models.mcp import (
    McpApprovalState,
    McpProvenance,
    McpServerConfig,
    McpServerConfigCreate,
    McpServerConfigPublic,
    McpServerConfigUpdate,
    McpStdioConfig,
    McpStreamableHttpConfig,
    McpTransport,
)
from models.mcp_installation import McpLaunchCandidate, McpPackageScanResult

from mcp_runtime.client_manager import (
    McpClientManagerError,
    McpServerLaunchError,
    McpStreamableHttpDisabledError,
)
from credential_bindings import CredentialBindingIndex
from mcp_runtime.scan_registry import (
    McpScanRegistry,
    ScanExpiredError,
    ScanNotFoundError,
)
from mcp_runtime.tool_catalog import McpToolCatalog


logger = logging.getLogger("McpTemplateInstaller")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


INSTALL_RECORD_FILENAME = "install_record.json"
"""Per-install sidecar written into ``workspace_artifacts/mcp_installs/<id>/``
with the absolute cwd, source_path, launch_candidate sha, and credential
binding env names (credential references stay in the MCP server config).
Read by the installer at delete time to clean up the install dir."""

_BARE_PYTHON_LAUNCHERS = frozenset({"python", "python.exe", "python3", "python3.exe", "py", "py.exe"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InstallError(ValueError):
    """Base class for install rejections. Each subclass has a stable ``code``."""

    code: str = "install_error"


class InstallScanExpiredError(InstallError):
    code = "scan_expired"


class InstallScanNotFoundError(InstallError):
    code = "scan_not_found"


class InstallCandidateMismatchError(InstallError):
    code = "candidate_mismatch"


class InstallCredentialMissingError(InstallError):
    code = "credential_not_found"


class InstallCredentialDisabledError(InstallError):
    code = "credential_disabled"


class InstallPlaintextSecretConfigError(InstallError):
    code = "plaintext_secret_config"


class InstallTransportUnsupportedError(InstallError):
    code = "transport_unsupported"


class InstallSlugConflictError(InstallError):
    code = "server_slug_conflict"


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallProbeResult:
    status: str  # "ok" | "skipped_untrusted" | "probe_failed"
    tool_count: int = 0
    tools: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


@dataclass(frozen=True)
class InstallResult:
    server: McpServerConfigPublic
    install_id: str
    install_dir: str  # absolute path
    absolute_cwd: str  # the cwd the launched process will use
    probe: InstallProbeResult
    approval_state: str


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class McpTemplateInstaller:
    """Orchestrate one install based on a registered scan + user choices.

    Stateless aside from the injected store/catalog refs; safe to share a
    single instance across requests.
    """

    def __init__(
        self,
        *,
        server_store,
        scan_registry: McpScanRegistry,
        credential_store: RuntimeCredentialStore,
        tool_catalog: McpToolCatalog,
        binding_index: CredentialBindingIndex,
        install_root: Path,
    ) -> None:
        self._servers = server_store
        self._scans = scan_registry
        self._credentials = credential_store
        self._catalog = tool_catalog
        self._bindings = binding_index
        self._install_root = install_root

    # ----------------------------------------------------------- preview path

    def preview(
        self,
        *,
        scan_id: str,
        launch_candidate_sha: str,
    ) -> tuple[McpPackageScanResult, McpLaunchCandidate]:
        """Validate scan_id + sha; return the resolved scan + candidate.

        Frontend uses this to confirm the wizard's selections are still
        valid before showing the final "信任并安装" screen. Pure read; no
        side effects.
        """
        scan = self._lookup_scan(scan_id)
        candidate = self._lookup_candidate(scan, launch_candidate_sha)
        return scan, candidate

    # -------------------------------------------------------------- install

    async def install(
        self,
        *,
        scan_id: str,
        launch_candidate_sha: str,
        server_slug: str,
        display_name: str,
        config_values: dict[str, str],
        credential_bindings: dict[str, str],
        trust_to_probe: bool,
        enable_for_session: bool = False,
        notes: str = "",
    ) -> InstallResult:
        """End-to-end install: validate → create server → optionally probe
        → optionally advance approval → audit → rebuild binding index.

        Raises a subclass of ``InstallError`` (with stable ``code``) on any
        validation failure; the router maps these to HTTP 400 with the code
        in the body so the frontend can show a localized message.
        """
        scan = self._lookup_scan(scan_id)
        candidate = self._lookup_candidate(scan, launch_candidate_sha)

        # Only stdio is supported by the current installer; streamable_http
        # packages need a separate flow because their cwd / process semantics
        # differ.
        if scan.transport != "stdio":
            raise InstallTransportUnsupportedError(
                f"v1 installer supports stdio only; scan transport={scan.transport!r}"
            )

        # Validate credentials before creating any state.
        self._validate_credential_bindings(credential_bindings)
        self._validate_plain_config_values(config_values)

        # Allocate install directory. For directory sources we keep
        # the source dir as the cwd and store an install_record sidecar
        # so delete-time cleanup can remove the marker without touching
        # the user's package.
        install_id = self._generate_install_id()
        install_dir = self._install_root / install_id
        install_dir.mkdir(parents=True, exist_ok=True)

        source_path = Path(scan.source_path)
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            # Zip extraction is deferred to a follow-up commit; reject for
            # now so we don't half-install something.
            install_dir.rmdir()  # roll back the empty marker dir
            raise InstallTransportUnsupportedError(
                "zip install not yet implemented; please extract first and "
                "supply the directory path"
            )

        absolute_cwd = (source_path / candidate.cwd).resolve()
        try:
            absolute_cwd.relative_to(source_path.resolve())
        except ValueError as exc:
            install_dir.rmdir()
            raise InstallTransportUnsupportedError(
                f"launch cwd escapes package root: {candidate.cwd!r}"
            ) from exc
        if not absolute_cwd.is_dir():
            install_dir.rmdir()
            raise InstallTransportUnsupportedError(
                f"launch cwd does not exist or is not a directory: {candidate.cwd!r}"
            )

        resolved_command = self._resolve_launch_command(candidate.command)

        # Build the server config. env carries non-sensitive values; saved
        # credential bindings are kept as references in the server config.
        stdio = McpStdioConfig(
            command=resolved_command,
            args=list(candidate.args),
            cwd=str(absolute_cwd),
            env=dict(config_values),
            env_refs=dict(credential_bindings),
            cwd_relative=None,
        )
        body = McpServerConfigCreate(
            name=display_name,
            server_slug=server_slug,
            transport=McpTransport.STDIO,
            stdio=stdio,
            provenance=McpProvenance.RUNTIME_USER_CONFIRMED,
            notes=notes,
        )
        try:
            public = self._servers.create(body)
        except ValueError as exc:
            install_dir.rmdir()
            # server_slug conflict is the most common ValueError from create.
            if "server_slug" in str(exc):
                raise InstallSlugConflictError(str(exc)) from exc
            raise InstallError(str(exc)) from exc

        server_id = public.server_id
        approval_state = McpApprovalState.REGISTERED

        # Write install_record sidecar.
        self._write_install_record(
            install_dir=install_dir,
            server_id=server_id,
            scan_id=scan_id,
            source_path=str(source_path),
            absolute_cwd=str(absolute_cwd),
            launch_candidate_sha=launch_candidate_sha,
            original_command=candidate.command,
            resolved_command=resolved_command,
            credential_env_names=sorted(credential_bindings.keys()),
        )

        # Rebuild the reverse binding index so the credentials center can
        # immediately show this server in its "used by" list.
        self._rebuild_binding_index()

        # Probing spawns the package and exposes bound credential material.
        # Only run when the user explicitly trusted the package.
        probe = InstallProbeResult(status="skipped_untrusted")
        if trust_to_probe:
            probe = await self._probe(server_id)
            if probe.status == "ok":
                self._servers.update(
                    server_id,
                    McpServerConfigUpdate(
                        approval_state=McpApprovalState.CATALOG_REVIEWED
                    ),
                )
                approval_state = McpApprovalState.CATALOG_REVIEWED
                if enable_for_session:
                    self._servers.update(
                        server_id,
                        McpServerConfigUpdate(
                            approval_state=McpApprovalState.ENABLED_FOR_SESSION
                        ),
                    )
                    approval_state = McpApprovalState.ENABLED_FOR_SESSION

        # Audit emits one event per install (separate from per-tool-call
        # audit). Best-effort; never raise.
        self._audit_install(
            install_id=install_id,
            server_id=server_id,
            server_slug=server_slug,
            scan_id=scan_id,
            launch_candidate_sha=launch_candidate_sha,
            credential_env_names=sorted(credential_bindings.keys()),
            trust_to_probe=trust_to_probe,
            probe_status=probe.status,
            approval_state=approval_state.value,
        )

        return InstallResult(
            server=self._servers.get_public(server_id),
            install_id=install_id,
            install_dir=str(install_dir),
            absolute_cwd=str(absolute_cwd),
            probe=probe,
            approval_state=approval_state.value,
        )

    # -------------------------------------------------------------- delete

    def cleanup_install_dir(self, server_id: str) -> bool:
        """Remove the install_record sidecar dir for a server. Caller is
        ``mcp_router.delete_server`` after RuntimeMcpServerStore.delete.

        Returns True if a directory was found and removed.
        """
        for child in self._install_root.iterdir() if self._install_root.exists() else []:
            record = child / INSTALL_RECORD_FILENAME
            if not record.is_file():
                continue
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("server_id") == server_id:
                try:
                    record.unlink()
                    child.rmdir()
                except OSError as exc:
                    logger.warning(
                        "install_dir_cleanup_failed: cleanup_error_type=%s",
                        exc.__class__.__name__,
                    )
                    return False
                self._rebuild_binding_index()
                return True
        return False

    # ------------------------------------------------------------------ helpers

    def _lookup_scan(self, scan_id: str) -> McpPackageScanResult:
        try:
            return self._scans.get(scan_id)
        except ScanExpiredError as exc:
            raise InstallScanExpiredError(
                f"scan {scan_id} has expired; please re-scan the package"
            ) from exc
        except ScanNotFoundError as exc:
            raise InstallScanNotFoundError(
                f"scan {scan_id} not found"
            ) from exc

    def _lookup_candidate(
        self,
        scan: McpPackageScanResult,
        launch_candidate_sha: str,
    ) -> McpLaunchCandidate:
        for c in scan.launch_candidates:
            if c.sha == launch_candidate_sha:
                return c
        raise InstallCandidateMismatchError(
            f"no launch candidate with sha={launch_candidate_sha!r} in scan "
            f"{scan.scan_id}; got {[c.sha for c in scan.launch_candidates]}"
        )

    def _validate_credential_bindings(
        self, bindings: dict[str, str]
    ) -> None:
        for env_name, cred_id in bindings.items():
            try:
                cred = self._credentials.get_internal(cred_id)
            except CredentialNotFoundError as exc:
                raise InstallCredentialMissingError(
                    "credential binding references an unknown saved credential"
                ) from exc
            if not cred.enabled:
                raise InstallCredentialDisabledError(
                    "credential binding references a disabled saved credential"
                )

    @staticmethod
    def _validate_plain_config_values(values: dict[str, str]) -> None:
        """Reject credential-shaped values before runtime state is created."""
        try:
            require_no_plaintext_secret_config(values)
        except ValueError as exc:
            raise InstallPlaintextSecretConfigError(str(exc)) from exc

    async def _probe(self, server_id: str) -> InstallProbeResult:
        config = self._servers.get_internal(server_id)
        try:
            tools = await self._catalog.get_tools(config, refresh=True)
        except McpStreamableHttpDisabledError as exc:
            return InstallProbeResult(
                status="probe_failed",
                reason="MCP streamable HTTP execution is disabled.",
            )
        except (McpServerLaunchError, McpClientManagerError) as exc:
            return InstallProbeResult(
                status="probe_failed",
                reason="MCP service probe failed. Check the service configuration.",
            )
        return InstallProbeResult(
            status="ok",
            tool_count=len(tools),
            tools=[t.model_dump(mode="json") for t in tools],
        )

    def _rebuild_binding_index(self) -> None:
        all_configs = self._servers.list_internal()
        self._bindings.rebuild_from_mcp_store(all_configs)

    def _write_install_record(
        self,
        *,
        install_dir: Path,
        server_id: str,
        scan_id: str,
        source_path: str,
        absolute_cwd: str,
        launch_candidate_sha: str,
        original_command: str,
        resolved_command: str,
        credential_env_names: list[str],
    ) -> None:
        record = {
            "version": 1,
            "install_id": install_dir.name,
            "server_id": server_id,
            "scan_id": scan_id,
            "source_path": source_path,
            "absolute_cwd": absolute_cwd,
            "launch_candidate_sha": launch_candidate_sha,
            "original_command": original_command,
            "resolved_command": resolved_command,
            "credential_env_names": credential_env_names,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (install_dir / INSTALL_RECORD_FILENAME).write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _audit_install(self, **fields: Any) -> None:
        """Append a structured install event to the MCP audit JSONL.

        Best-effort: failure is logged at warning, never raised, so the
        audit layer cannot break installs (mirror of audit.append).

        Never logs saved credential identifiers or credential material.
        Records env names only so an operator can later see which settings
        were bound without revealing the saved credential that answered.
        """
        try:
            from mcp_runtime import audit as mcp_audit

            path = mcp_audit.audit_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "kind": "install",
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **fields,
            }
            line = json.dumps(payload, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_install_audit_failed: %s", exc)

    @staticmethod
    def _resolve_launch_command(command: str) -> str:
        """Resolve bare Python launchers to the active interpreter path.

        Why:
            A package manifest may reasonably say `python -m package.server`,
            but persisting a bare executable lets PATH choose a different
            interpreter at probe time. Absolute commands and non-Python
            launchers are preserved for transparency.
        """
        cleaned = str(command or "").strip()
        if not cleaned:
            raise InstallTransportUnsupportedError("launch command must be non-empty")
        if "/" in cleaned or "\\" in cleaned:
            return cleaned
        if cleaned.lower() not in _BARE_PYTHON_LAUNCHERS:
            return cleaned
        resolved = str(sys.executable or "").strip()
        if not resolved:
            raise InstallTransportUnsupportedError(
                "current Python interpreter could not be resolved"
            )
        return resolved

    @staticmethod
    def _generate_install_id() -> str:
        return f"install_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Module-level singleton (FastAPI registration)
# ---------------------------------------------------------------------------


_singleton: McpTemplateInstaller | None = None


def get_template_installer() -> McpTemplateInstaller:
    """Return the process-wide installer.

    The router's lifespan / startup hook is expected to call
    ``set_template_installer(...)`` once with the canonical store +
    catalog + binding_index wiring. Until then, callers get a clear
    error rather than a half-wired default — installs are too important
    to silently no-op.
    """
    if _singleton is None:
        raise RuntimeError(
            "McpTemplateInstaller singleton not initialized — "
            "call set_template_installer(...) at app startup"
        )
    return _singleton


def set_template_installer(installer: McpTemplateInstaller | None) -> None:
    global _singleton
    _singleton = installer


__all__ = [
    "INSTALL_RECORD_FILENAME",
    "InstallCandidateMismatchError",
    "InstallCredentialDisabledError",
    "InstallCredentialMissingError",
    "InstallPlaintextSecretConfigError",
    "InstallError",
    "InstallProbeResult",
    "InstallResult",
    "InstallScanExpiredError",
    "InstallScanNotFoundError",
    "InstallSlugConflictError",
    "InstallTransportUnsupportedError",
    "McpTemplateInstaller",
    "get_template_installer",
    "set_template_installer",
]
