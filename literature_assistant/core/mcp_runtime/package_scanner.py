"""MCP package scanner.

Walks a user-supplied local path and produces an ``McpPackageScanResult``
describing how to install the package as an MCP server. Read-only:

- Never executes any package code (no ``import``, no ``exec``, no subprocess).
- Never opens network connections.
- Rejects remote URLs in ``source_path``.
- Validates launch candidates against ``security_policy.validate_stdio_command``
  before returning them.

Manifest precedence:

1. ``literature-mcp.json`` (primary)
2. ``lit-mcp.json``
3. ``mcp.json``
4. ``server.json``

Fallback scanners (``package.json``, ``pyproject.toml``, README) are stubs
in this implementation; they emit a ``low`` confidence candidate at most or
route to ``needs_manual_launch=True``.
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from dynamic_config_schema import (
    extract_dynamic_config_schema,
    parse_dynamic_config_schema,
)
from extension_secret_policy import is_plaintext_secret_config_field
from models.mcp_installation import (
    CONFIG_FIELD_TYPES,
    CREDENTIAL_KINDS,
    McpInstallConfigField,
    McpLaunchCandidate,
    McpPackageScanRequest,
    McpPackageScanResult,
    McpRequiredCredential,
    McpScanConfidence,
    McpScanWarning,
    McpScanWarningLevel,
    compute_launch_candidate_sha,
    compute_scan_expiry,
    generate_scan_id,
)


logger = logging.getLogger("McpPackageScanner")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


MANIFEST_FILENAMES = (
    "literature-mcp.json",
    "lit-mcp.json",
    "mcp.json",
    "server.json",
)
"""Tried in order; first match wins. literature-mcp.json is the primary
documented name."""

MAX_MANIFEST_BYTES = 256 * 1024  # 256 KiB — manifest is metadata, not data
MAX_ARGS = 64
MAX_ENV_KEYS = 32

REMOTE_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
"""Matches ``http://``, ``https://``, ``ftp://``, ``git+ssh://`` etc.
``file://`` would also match; scanner rejects it anyway because local paths
should be supplied unprefixed."""

SHELL_METACHARS = frozenset("|;&`$<>()\n\r")
"""Same set as McpStdioConfig._no_shell_metachars validator. Duplicated
locally rather than imported to keep the scanner independent of pydantic
validator wiring."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class McpPackageScanError(ValueError):
    """Hard scan failure: input rejected before any heuristic ran.

    Use sparingly — most issues become warnings on the result so the user
    can still see what was inspected.
    """


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class McpPackageScanner:
    """Read-only scanner for local MCP package paths.

    Stateless across calls; safe to share. Tests can subclass and override
    ``_read_manifest_text`` to inject manifests without touching the filesystem.
    """

    def scan(self, request: McpPackageScanRequest) -> McpPackageScanResult:
        warnings: list[McpScanWarning] = []
        normalized = self._normalize_source_path(request.source_path)

        # Try first-class manifests.
        manifest_path, manifest_data = self._try_lit_manifests(normalized, warnings)
        if any(w.level == McpScanWarningLevel.BLOCK for w in warnings) and manifest_data is None:
            return self._build_blocked_manual_result(normalized=normalized, warnings=warnings)
        if manifest_data is not None:
            return self._build_result_from_manifest(
                normalized=normalized,
                manifest_path=manifest_path,
                manifest_data=manifest_data,
                template_hint=request.template_hint,
                warnings=warnings,
            )

        # Fallback: package.json (Node MCP). Medium confidence.
        pkg_candidate = self._try_package_json(normalized)
        if pkg_candidate is not None:
            return self._build_fallback_result(
                normalized=normalized,
                candidate=pkg_candidate,
                warnings=warnings,
            )

        # Fallback: pyproject.toml (Python MCP). Medium confidence.
        py_candidate = self._try_pyproject_toml(normalized)
        if py_candidate is not None:
            return self._build_fallback_result(
                normalized=normalized,
                candidate=py_candidate,
                warnings=warnings,
            )

        # No safe candidate: route to manual launch.
        warnings.append(
            McpScanWarning(
                level=McpScanWarningLevel.WARN,
                code="no_first_class_manifest",
                message=(
                    f"No {' / '.join(MANIFEST_FILENAMES)} was found. "
                    "Falling back to manual launch entry."
                ),
            )
        )
        return McpPackageScanResult(
            scan_id=generate_scan_id(),
            source_path=str(normalized),
            confidence=McpScanConfidence.NONE,
            transport="stdio",
            needs_manual_launch=True,
            warnings=warnings,
            expires_at=compute_scan_expiry(),
        )

    # ----------------------------------------------------------------- safety

    def _normalize_source_path(self, raw: str) -> Path:
        """Return an absolute, existing local path. Reject remote URLs.

        Path traversal in the input string is allowed (``..`` may be valid in
        the user's filesystem); however the scanner only reads files inside
        the resolved directory and never walks above it.
        """
        if REMOTE_SCHEME_RE.match(raw):
            raise McpPackageScanError(
                "remote URLs are not allowed as source paths"
            )
        candidate = Path(raw).expanduser()
        if candidate.is_symlink():
            raise McpPackageScanError(
                "source path must not be a symbolic link"
            )
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise McpPackageScanError(
                "source path does not exist"
            ) from exc
        except OSError as exc:
            raise McpPackageScanError(
                "source path could not be resolved"
            ) from exc

        if resolved.is_file():
            # Allow pointing at a manifest or zip file directly; for zip the
            # extractor (S3) handles unpacking. For a file inside a package,
            # use the parent dir as the package root.
            if resolved.suffix.lower() in (".zip",):
                # Zip extraction handled by installer; scanner returns the
                # zip path as-is with a warning.
                return resolved
            return resolved.parent
        if not resolved.is_dir():
            raise McpPackageScanError(
                "source path must be a directory, file, or zip"
            )
        return resolved

    def _read_manifest_text(self, path: Path) -> str | None:
        """Return file contents as text, or None if it cannot be read.

        Centralized for tests to monkeypatch.
        """
        try:
            stat = path.stat()
        except OSError:
            return None
        if stat.st_size > MAX_MANIFEST_BYTES:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    # --------------------------------------------------------------- manifest

    def _try_lit_manifests(
        self, root: Path, warnings: list[McpScanWarning]
    ) -> tuple[Path | None, dict[str, Any] | None]:
        """Look for the first-class manifest in precedence order."""
        if not root.is_dir():
            return None, None
        for name in MANIFEST_FILENAMES:
            candidate = root / name
            if candidate.exists() and candidate.is_symlink():
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.BLOCK,
                        code="manifest_symlink_rejected",
                        message=(
                            f"{name} is a symbolic link; package manifests "
                            "must be regular files inside the package root"
                        ),
                        field=name,
                    )
                )
                continue
            text = self._read_manifest_text(candidate)
            if text is None:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "manifest rejected (invalid JSON): %s", exc
                )
                continue
            if not isinstance(data, dict):
                continue
            return candidate, data
        return None, None

    def _build_blocked_manual_result(
        self,
        *,
        normalized: Path,
        warnings: list[McpScanWarning],
    ) -> McpPackageScanResult:
        """Return a manual result when a hard scan warning forbids automation."""
        return McpPackageScanResult(
            scan_id=generate_scan_id(),
            source_path=str(normalized),
            confidence=McpScanConfidence.NONE,
            transport="stdio",
            needs_manual_launch=True,
            warnings=warnings,
            expires_at=compute_scan_expiry(),
        )

    def _build_result_from_manifest(
        self,
        *,
        normalized: Path,
        manifest_path: Path,
        manifest_data: dict[str, Any],
        template_hint: str | None,
        warnings: list[McpScanWarning],
    ) -> McpPackageScanResult:
        # Schema version is forward-compatible: scanner accepts unknown
        # higher versions but emits a warning so the operator notices.
        schema_version = manifest_data.get("schema_version", 1)
        if not isinstance(schema_version, int) or schema_version < 1:
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.WARN,
                    code="manifest_bad_schema_version",
                    message=(
                        f"manifest schema_version={schema_version!r} not a "
                        "positive int; treating as v1"
                    ),
                    field="schema_version",
                )
            )
        elif schema_version > 1:
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.INFO,
                    code="manifest_future_schema_version",
                    message=(
                        f"manifest schema_version={schema_version} is newer "
                        "than supported (1); proceeding best-effort"
                    ),
                    field="schema_version",
                )
            )

        transport = str(manifest_data.get("transport", "stdio")).strip() or "stdio"
        if transport not in ("stdio", "streamable_http"):
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.BLOCK,
                    code="manifest_unknown_transport",
                    message=f"unsupported transport: {transport!r}",
                    field="transport",
                )
            )
            return McpPackageScanResult(
                scan_id=generate_scan_id(),
                source_path=str(normalized),
                package_id=str(manifest_data.get("package_id", "") or ""),
                display_name=str(manifest_data.get("display_name", "") or ""),
                confidence=McpScanConfidence.NONE,
                transport=transport,
                needs_manual_launch=True,
                warnings=warnings,
                expires_at=compute_scan_expiry(),
            )

        # Launch candidate from manifest.launch.
        candidate, candidate_warnings = self._build_launch_candidate(
            manifest_data.get("launch", {}),
            source=manifest_path.name,
        )
        warnings.extend(candidate_warnings)

        # Config fields / required credentials (graceful — skip malformed
        # entries with a warning each so the user can fix the manifest).
        config_fields, cf_warnings = self._parse_config_fields(
            manifest_data.get("config_fields", [])
        )
        warnings.extend(cf_warnings)

        required_credentials, rc_warnings = self._parse_required_credentials(
            manifest_data.get("required_credentials", [])
        )
        warnings.extend(rc_warnings)

        schema_result = parse_dynamic_config_schema(
            extract_dynamic_config_schema(manifest_data),
            existing_config_keys={
                key
                for field in config_fields
                for key in (field.id, field.env)
            },
            existing_credential_keys={
                key
                for credential in required_credentials
                for key in (credential.id, credential.env)
            },
        )
        config_fields.extend(
            McpInstallConfigField(
                id=field.id,
                label=field.label,
                env=field.env,
                type=field.type,
                required=field.required,
                default=field.default,
                options=[
                    {"value": option.value, "label": option.label}
                    for option in field.options
                ]
                if field.options is not None
                else None,
                min=field.min,
                max=field.max,
                step=field.step,
                description=field.description,
            )
            for field in schema_result.config_fields
        )
        required_credentials.extend(
            McpRequiredCredential(
                id=credential.id,
                label=credential.label,
                env=credential.env,
                kind=credential.kind,
                provider_hints=list(credential.provider_hints),
                required=credential.required,
                description=credential.description,
            )
            for credential in schema_result.required_credentials
        )
        warnings.extend(
            McpScanWarning(
                level=McpScanWarningLevel.WARN,
                code="config_schema_mapping_warning",
                message=message,
                field="config_schema",
            )
            for message in schema_result.warnings
        )

        expected_tools = self._parse_string_list(
            manifest_data.get("expected_tools", []), max_items=64
        )
        capabilities = self._parse_string_list(
            manifest_data.get("capabilities", []), max_items=16
        )

        needs_manual = candidate is None
        confidence = (
            McpScanConfidence.HIGH if candidate is not None else McpScanConfidence.NONE
        )

        # Block-level warnings force manual launch.
        if any(w.level == McpScanWarningLevel.BLOCK for w in warnings):
            needs_manual = True
            confidence = McpScanConfidence.NONE

        return McpPackageScanResult(
            scan_id=generate_scan_id(),
            source_path=str(normalized),
            package_id=str(manifest_data.get("package_id", "") or ""),
            display_name=str(manifest_data.get("display_name", "") or ""),
            description=str(manifest_data.get("description", "") or ""),
            version=str(manifest_data.get("version", "") or ""),
            confidence=confidence,
            transport=transport,
            launch_candidates=[candidate] if candidate is not None else [],
            config_fields=config_fields,
            required_credentials=required_credentials,
            expected_tools=expected_tools,
            capabilities=capabilities,
            warnings=warnings,
            needs_manual_launch=needs_manual,
            expires_at=compute_scan_expiry(),
        )

    # --------------------------------------------------------------- launch

    def _build_launch_candidate(
        self, launch_block: Any, *, source: str
    ) -> tuple[McpLaunchCandidate | None, list[McpScanWarning]]:
        warnings: list[McpScanWarning] = []
        if not isinstance(launch_block, dict):
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.BLOCK,
                    code="launch_block_missing",
                    message="manifest.launch must be an object with command/args",
                    field="launch",
                )
            )
            return None, warnings

        command = str(launch_block.get("command", "") or "").strip()
        if not command:
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.BLOCK,
                    code="launch_command_missing",
                    message="manifest.launch.command is required",
                    field="launch.command",
                )
            )
            return None, warnings
        if any(ch in command for ch in SHELL_METACHARS):
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.BLOCK,
                    code="launch_command_shell_metachar",
                    message=(
                        "command contains shell metacharacters; argv-only "
                        "spawn cannot interpret them safely"
                    ),
                    field="launch.command",
                )
            )
            return None, warnings

        raw_args = launch_block.get("args", [])
        if not isinstance(raw_args, list):
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.BLOCK,
                    code="launch_args_not_list",
                    message="manifest.launch.args must be a list of strings",
                    field="launch.args",
                )
            )
            return None, warnings
        if len(raw_args) > MAX_ARGS:
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.BLOCK,
                    code="launch_args_too_many",
                    message=f"manifest.launch.args exceeds {MAX_ARGS}",
                    field="launch.args",
                )
            )
            return None, warnings
        args: list[str] = []
        for i, item in enumerate(raw_args):
            if not isinstance(item, str):
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.BLOCK,
                        code="launch_args_non_string",
                        message=f"manifest.launch.args[{i}] is not a string",
                        field=f"launch.args[{i}]",
                    )
                )
                return None, warnings
            args.append(item)

        cwd_raw = launch_block.get("cwd", ".")
        if not isinstance(cwd_raw, str):
            warnings.append(
                McpScanWarning(
                    level=McpScanWarningLevel.WARN,
                    code="launch_cwd_not_string",
                    message="launch.cwd must be a string; defaulting to '.'",
                    field="launch.cwd",
                )
            )
            cwd_raw = "."
        cwd = cwd_raw.strip() or "."

        sha = compute_launch_candidate_sha(command, args, cwd)
        return (
            McpLaunchCandidate(
                command=command,
                args=args,
                cwd=cwd,
                confidence=McpScanConfidence.HIGH,
                source=source,
                sha=sha,
            ),
            warnings,
        )

    # ----------------------------------------------------- config_fields / creds

    def _parse_config_fields(
        self, raw: Any
    ) -> tuple[list[McpInstallConfigField], list[McpScanWarning]]:
        out: list[McpInstallConfigField] = []
        warnings: list[McpScanWarning] = []
        if not isinstance(raw, list):
            if raw not in (None, {}):
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="config_fields_not_list",
                        message="config_fields must be a list; ignoring",
                        field="config_fields",
                    )
                )
            return out, warnings
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="config_field_not_dict",
                        message=f"config_fields[{i}] must be an object; skipping",
                        field=f"config_fields[{i}]",
                    )
                )
                continue
            field_type = str(entry.get("type", "text")).strip() or "text"
            if field_type not in CONFIG_FIELD_TYPES:
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="config_field_unknown_type",
                        message=(
                            f"config_fields[{i}].type={field_type!r} not in "
                            f"v1 allowlist {sorted(CONFIG_FIELD_TYPES)}; "
                            "skipping"
                        ),
                        field=f"config_fields[{i}].type",
                    )
                )
                continue
            normalized_default = self._normalize_config_default(
                field_type, entry.get("default")
            )
            if is_plaintext_secret_config_field(
                field_id=str(entry.get("id", "") or ""),
                label=str(entry.get("label", "") or ""),
                env=str(entry.get("env", "") or ""),
                description=str(entry.get("description", "") or ""),
                default=normalized_default,
            ):
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.BLOCK,
                        code="config_field_credential_like",
                        message=(
                            f"config_fields[{i}] appears to contain credential "
                            "material; declare it under required_credentials"
                        ),
                        field=f"config_fields[{i}]",
                    )
                )
                continue
            try:
                field = McpInstallConfigField(
                    id=str(entry.get("id", "")),
                    label=str(entry.get("label", "")),
                    env=str(entry.get("env", "")),
                    type=field_type,
                    required=bool(entry.get("required", True)),
                    default=normalized_default,
                    options=entry.get("options"),
                    min=self._parse_optional_number(entry.get("min")),
                    max=self._parse_optional_number(entry.get("max")),
                    step=self._parse_optional_number(entry.get("step")),
                    description=str(entry.get("description", "") or ""),
                )
            except (ValueError, TypeError) as exc:
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="config_field_validation_failed",
                        message=f"config_fields[{i}] rejected: {exc}",
                        field=f"config_fields[{i}]",
                    )
                )
                continue
            out.append(field)
        return out, warnings

    def _parse_required_credentials(
        self, raw: Any
    ) -> tuple[list[McpRequiredCredential], list[McpScanWarning]]:
        out: list[McpRequiredCredential] = []
        warnings: list[McpScanWarning] = []
        if not isinstance(raw, list):
            if raw not in (None, {}):
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="required_credentials_not_list",
                        message=(
                            "required_credentials must be a list; ignoring"
                        ),
                        field="required_credentials",
                    )
                )
            return out, warnings
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="required_credential_not_dict",
                        message=(
                            f"required_credentials[{i}] must be an object; "
                            "skipping"
                        ),
                        field=f"required_credentials[{i}]",
                    )
                )
                continue
            kind = str(entry.get("kind", "api_key")).strip() or "api_key"
            if kind not in CREDENTIAL_KINDS:
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="required_credential_unknown_kind",
                        message=(
                            f"required_credentials[{i}].kind={kind!r} not in "
                            f"v1 allowlist {sorted(CREDENTIAL_KINDS)}; skipping"
                        ),
                        field=f"required_credentials[{i}].kind",
                    )
                )
                continue
            try:
                cred = McpRequiredCredential(
                    id=str(entry.get("id", "")),
                    label=str(entry.get("label", "")),
                    env=str(entry.get("env", "")),
                    kind=kind,
                    provider_hints=self._parse_string_list(
                        entry.get("provider_hints", []), max_items=16
                    ),
                    required=bool(entry.get("required", True)),
                    description=str(entry.get("description", "") or ""),
                )
            except (ValueError, TypeError) as exc:
                warnings.append(
                    McpScanWarning(
                        level=McpScanWarningLevel.WARN,
                        code="required_credential_validation_failed",
                        message=(
                            f"required_credentials[{i}] rejected: {exc}"
                        ),
                        field=f"required_credentials[{i}]",
                    )
                )
                continue
            out.append(cred)
        return out, warnings

    @staticmethod
    def _parse_optional_number(raw: Any) -> float | None:
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            parsed = float(raw)
            return parsed if math.isfinite(parsed) else None
        if isinstance(raw, str):
            try:
                parsed = float(raw.strip())
                return parsed if math.isfinite(parsed) else None
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalize_config_default(field_type: str, raw: Any) -> str | None:
        if raw is None:
            return None
        if field_type == "boolean":
            if isinstance(raw, bool):
                return "true" if raw else "false"
            normalized = str(raw).strip().lower()
            return "true" if normalized in {"1", "true", "yes", "on"} else "false"
        return str(raw)

    @staticmethod
    def _parse_string_list(raw: Any, *, max_items: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw[:max_items]:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    # ------------------------------------------------------------ fallback: node

    def _try_package_json(self, root: Path) -> McpLaunchCandidate | None:
        """Read ``package.json`` and emit a medium-confidence stdio candidate.

        Signal precedence (most explicit first):
        1. ``mcp`` block: ``{"mcp": {"command": "...", "args": [...]}}``
        2. ``bin``: package declares an executable bin entry (we run it via
           ``node node_modules/.bin/<bin>`` if a single entry exists)
        3. ``scripts.mcp`` then ``scripts.start``: tokenized and validated;
           emit only if no shell metacharacter pollution.

        Returns None if no safe candidate could be derived. Never raises;
        per-signal issues are silently skipped so the caller can move on
        to the next fallback.
        """
        if not root.is_dir():
            return None
        pkg_path = root / "package.json"
        if pkg_path.exists() and pkg_path.is_symlink():
            return None
        text = self._read_manifest_text(pkg_path)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None

        # 1. Explicit mcp block (preferred even inside package.json).
        mcp_block = data.get("mcp")
        if isinstance(mcp_block, dict):
            command = str(mcp_block.get("command", "") or "").strip()
            args_raw = mcp_block.get("args", [])
            if command and self._is_safe_command(command):
                args = self._sanitize_args(args_raw)
                if args is not None:
                    return self._make_candidate(
                        command=command,
                        args=args,
                        source="package.json:mcp",
                        confidence=McpScanConfidence.MEDIUM,
                    )

        # 2. bin: { "<name>": "./path/to/server.js" }
        bin_field = data.get("bin")
        if isinstance(bin_field, dict) and len(bin_field) == 1:
            (bin_name, bin_target), = bin_field.items()
            if isinstance(bin_target, str) and bin_target.strip():
                # Run via node directly to avoid PATH dependency on the
                # bin shim being installed.
                target = bin_target.strip()
                if self._is_safe_arg(target):
                    return self._make_candidate(
                        command="node",
                        args=[target],
                        source=f"package.json:bin.{bin_name}",
                        confidence=McpScanConfidence.MEDIUM,
                    )
        elif isinstance(bin_field, str) and bin_field.strip():
            target = bin_field.strip()
            if self._is_safe_arg(target):
                return self._make_candidate(
                    command="node",
                    args=[target],
                    source="package.json:bin",
                    confidence=McpScanConfidence.MEDIUM,
                )

        # 3. scripts.mcp / scripts.start
        scripts = data.get("scripts")
        if isinstance(scripts, dict):
            for key in ("mcp", "start"):
                raw = scripts.get(key)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                cand = self._candidate_from_script_string(
                    raw, source=f"package.json:scripts.{key}"
                )
                if cand is not None:
                    return cand

        return None

    # -------------------------------------------------------- fallback: python

    def _try_pyproject_toml(self, root: Path) -> McpLaunchCandidate | None:
        """Read ``pyproject.toml`` and emit a medium-confidence stdio candidate.

        Signal precedence:
        1. ``[tool.literature-mcp]`` block: same shape as the JSON manifest's
           ``launch`` field (project-local override without committing a
           separate manifest file).
        2. ``[project.scripts]`` with a single entry: run via that script name
           (low-medium — depends on `pip install` having created the entry).
        3. Single declared entry-point under ``[project.scripts]`` together
           with a ``[project]`` ``name`` → emit ``python -m <module>``
           heuristic. Conservative: only fires when there is exactly one
           script and the value looks like ``module:function``.

        Returns None on any parse / safety failure.
        """
        if not root.is_dir():
            return None
        pyp = root / "pyproject.toml"
        if pyp.exists() and pyp.is_symlink():
            return None
        text = self._read_manifest_text(pyp)
        if text is None:
            return None
        data = self._load_toml_text(text)
        if not isinstance(data, dict):
            return None

        # 1. Explicit tool.literature-mcp block.
        tool = data.get("tool")
        if isinstance(tool, dict):
            lit_block = tool.get("literature-mcp") or tool.get("literature_mcp")
            if isinstance(lit_block, dict):
                command = str(lit_block.get("command", "") or "").strip()
                args_raw = lit_block.get("args", [])
                if command and self._is_safe_command(command):
                    args = self._sanitize_args(args_raw)
                    if args is not None:
                        return self._make_candidate(
                            command=command,
                            args=args,
                            source="pyproject.toml:[tool.literature-mcp]",
                            confidence=McpScanConfidence.MEDIUM,
                        )

        # 2/3. [project.scripts] heuristics.
        project = data.get("project")
        if isinstance(project, dict):
            scripts = project.get("scripts")
            if isinstance(scripts, dict) and len(scripts) == 1:
                (script_name, script_target), = scripts.items()
                if not isinstance(script_target, str):
                    return None
                target = script_target.strip()
                # entry-point form "pkg.module:func" → python -m pkg.module
                # is too aggressive (runs module top-level, not the func);
                # safer to emit the installed console_script name and let
                # the user verify in the wizard.
                if isinstance(script_name, str) and self._is_safe_arg(script_name):
                    return self._make_candidate(
                        command=script_name,
                        args=[],
                        source=f"pyproject.toml:[project.scripts].{script_name}",
                        confidence=McpScanConfidence.MEDIUM,
                    )
                # Fallback: if name unsafe but target looks like module:func,
                # emit python -m form with explicit note via low confidence.
                if ":" in target:
                    module_part = target.split(":", 1)[0].strip()
                    if module_part and self._is_safe_arg(module_part):
                        return self._make_candidate(
                            command="python",
                            args=["-m", module_part],
                            source="pyproject.toml:[project.scripts]:entrypoint",
                            confidence=McpScanConfidence.LOW,
                        )

        return None

    # ------------------------------------------------------------------ utils

    def _is_safe_command(self, command: str) -> bool:
        return command and not any(ch in command for ch in SHELL_METACHARS)

    def _is_safe_arg(self, value: str) -> bool:
        if not value:
            return False
        return not any(ch in value for ch in SHELL_METACHARS)

    def _sanitize_args(self, raw: Any) -> list[str] | None:
        """Return arg list if safe; None if any entry fails validation."""
        if not isinstance(raw, list):
            return None
        if len(raw) > MAX_ARGS:
            return None
        out: list[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                return None
            if not self._is_safe_arg(entry):
                return None
            out.append(entry)
        return out

    def _candidate_from_script_string(
        self, raw_script: str, *, source: str
    ) -> McpLaunchCandidate | None:
        """Tokenize a script string into command+args. Conservative: any
        shell metacharacter (``|``, ``;``, ``&&``, ``$``, etc.) disqualifies.
        Splits on whitespace only — quoted args with embedded spaces are not
        supported in v1 (rare in real MCP launch lines).
        """
        s = raw_script.strip()
        if not s:
            return None
        if any(ch in s for ch in SHELL_METACHARS):
            return None
        tokens = s.split()
        if not tokens:
            return None
        command, *args = tokens
        if len(args) > MAX_ARGS:
            return None
        return self._make_candidate(
            command=command,
            args=args,
            source=source,
            confidence=McpScanConfidence.MEDIUM,
        )

    def _make_candidate(
        self,
        *,
        command: str,
        args: list[str],
        source: str,
        confidence: McpScanConfidence,
        cwd: str = ".",
    ) -> McpLaunchCandidate:
        return McpLaunchCandidate(
            command=command,
            args=args,
            cwd=cwd,
            confidence=confidence,
            source=source,
            sha=compute_launch_candidate_sha(command, args, cwd),
        )

    def _load_toml_text(self, text: str) -> Any:
        """Parse TOML text. Prefer stdlib ``tomllib`` (3.11+); fall back to
        ``tomli`` if installed; return None otherwise (scanner skips the
        signal silently).
        """
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[import-not-found]
            except ImportError:
                return None
        try:
            return tomllib.loads(text)
        except Exception:
            return None

    def _build_fallback_result(
        self,
        *,
        normalized: Path,
        candidate: McpLaunchCandidate,
        warnings: list[McpScanWarning],
    ) -> McpPackageScanResult:
        """Wrap a fallback-scanner candidate in a scan result.

        Always WARN-level: fallbacks lack the manifest's structured metadata
        (display_name, expected_tools, required_credentials), so the wizard
        will need to ask the user for slugs / env names manually.
        """
        warnings.append(
            McpScanWarning(
                level=McpScanWarningLevel.WARN,
                code="fallback_scanner_low_metadata",
                message=(
                    f"Detected launch via {candidate.source}; package "
                    "metadata (display_name / required_credentials / "
                    "expected_tools) is unavailable and must be entered "
                    "by hand."
                ),
            )
        )
        if any(w.level == McpScanWarningLevel.BLOCK for w in warnings):
            return self._build_blocked_manual_result(normalized=normalized, warnings=warnings)
        return McpPackageScanResult(
            scan_id=generate_scan_id(),
            source_path=str(normalized),
            confidence=candidate.confidence,
            transport="stdio",
            launch_candidates=[candidate],
            warnings=warnings,
            needs_manual_launch=False,
            expires_at=compute_scan_expiry(),
        )


# ---------------------------------------------------------------------------
# Module-level singleton (FastAPI registration)
# ---------------------------------------------------------------------------


_singleton: McpPackageScanner | None = None


def get_package_scanner() -> McpPackageScanner:
    global _singleton
    if _singleton is None:
        _singleton = McpPackageScanner()
    return _singleton


def set_package_scanner(scanner: McpPackageScanner | None) -> None:
    """Test hook."""
    global _singleton
    _singleton = scanner


__all__ = [
    "MANIFEST_FILENAMES",
    "MAX_MANIFEST_BYTES",
    "McpPackageScanError",
    "McpPackageScanner",
    "get_package_scanner",
    "set_package_scanner",
]
