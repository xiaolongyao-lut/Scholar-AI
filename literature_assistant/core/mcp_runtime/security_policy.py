"""Q3a-hardened process runner safety policy (Phase 1B / TASK-103).

Per plan v0.3 §3.2 #Q3 / §4.3 / §5 TASK-103, this module enforces the
"hardened local process runner" preconditions before client_manager
launches a stdio MCP server subprocess. NOT a true OS sandbox (Job
Object / firejail / container would be needed for that).

What this module does:
  - argv-only validation (no shell string)
  - dangerous-command lint (rm/format/sudo/...)
  - env allowlist + redaction (only explicit user env passes; PATH /
    SYSTEMROOT etc. are added as a minimal allowlist for the subprocess
    to actually be launchable on Windows / POSIX)
  - cwd isolation (subprocess gets its own runtime_state-anchored dir)
  - output caps (stdout/stderr line + char limits)
  - timeout caps (startup + per-call)

What this module does NOT do:
  - Restrict syscalls or filesystem access (process inherits user privs)
  - Block network (subprocess can still connect anywhere)

Documented limitation: Phase 5 may add OS-level sandbox; Q3b/c upgrade
in a separate slice.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project_paths import runtime_state_path

from models.mcp import McpStdioConfig, mask_env_value


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class McpSecurityPolicyError(ValueError):
    """Raised when a server config fails pre-launch validation."""


# ---------------------------------------------------------------------------
# Tunable defaults (kept conservative; can be tightened by env var later)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessLaunchPolicy:
    """Per-launch safety envelope. Defaults are intentionally tight."""

    startup_timeout_seconds: float = 10.0
    """Hard cap on initialize() handshake."""
    per_call_timeout_seconds: float = 20.0
    """Hard cap on a single tool call (matches plan §3.2 Q7)."""
    max_stdout_chars: int = 1_048_576
    """1 MiB total. Prevents a runaway server from blowing memory."""
    max_stderr_chars: int = 262_144
    """256 KiB. Bigger error messages get truncated with marker."""


DEFAULT_LAUNCH_POLICY = ProcessLaunchPolicy()


# Known-dangerous tokens. Match either exact command basename OR substring
# in args (for things like ``rm -rf /``).
_DANGEROUS_COMMAND_BASENAMES = {
    "rm", "rmdir", "mv", "dd", "mkfs", "format", "shred", "fdisk",
    "del", "rd", "diskpart",  # Windows
    "chmod", "chown", "icacls", "takeown", "attrib",
    "sudo", "su", "doas", "runas",
    "shutdown", "reboot", "poweroff", "halt",
    "kill", "killall", "taskkill",
    "wget", "curl", "ftp", "tftp", "scp", "rsync",  # network exfil
    "nc", "ncat", "netcat", "socat",
    "bash", "sh", "zsh", "fish", "csh", "powershell", "pwsh", "cmd",
}

_DANGEROUS_ARG_PATTERNS = [
    re.compile(r"\brm\s+-rf?\b"),
    re.compile(r"\b/dev/sd[a-z]\b"),
    re.compile(r"\b:(){:\|:&};:\b"),  # fork bomb
    re.compile(r"\b\\\\\.\\PHYSICALDRIVE\d", re.IGNORECASE),  # Windows raw disk
    re.compile(r"--no-preserve-root"),
]

# Minimal env allowlist passed to subprocess in addition to user-provided
# env. These are required for python interpreter to actually launch on
# Windows + POSIX. Values are read from current process env.
_PASSTHROUGH_ENV_KEYS = {
    "PATH",
    "PATHEXT",         # Windows
    "SYSTEMROOT",      # Windows; required for socket etc.
    "WINDIR",          # Windows
    "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE",  # cross-platform home
    "LANG", "LC_ALL", "LC_CTYPE",
    "PYTHONIOENCODING",
    "PYTHONPATH",      # so importable fixtures resolve
}

# User keys that are OBVIOUSLY too sensitive to allow a server to inherit
# silently from the parent process. They can still pass them explicitly via
# ``McpStdioConfig.env``, but never inherited.
_DENY_INHERIT_KEYS_REGEX = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|credential|bearer|oauth)"
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_stdio_command(stdio: McpStdioConfig) -> None:
    """Reject obvious foot-guns before client_manager spawns a process.

    Raises ``McpSecurityPolicyError`` on rejection. The ``McpStdioConfig``
    model already rejects shell metacharacters in ``command``; this layer
    adds command-basename + arg-pattern lint.
    """
    cmd = stdio.command.strip()
    if not cmd:
        raise McpSecurityPolicyError("stdio.command must be non-empty")

    basename = Path(cmd).name.lower()
    # Strip Windows .exe / .bat for matching.
    for suffix in (".exe", ".bat", ".cmd", ".com", ".ps1"):
        if basename.endswith(suffix):
            basename = basename[: -len(suffix)]
            break

    if basename in _DANGEROUS_COMMAND_BASENAMES:
        raise McpSecurityPolicyError(
            f"command basename {basename!r} is on the dangerous list; "
            f"refuse to launch"
        )

    flat_args = " ".join(stdio.args)
    for pattern in _DANGEROUS_ARG_PATTERNS:
        if pattern.search(flat_args):
            raise McpSecurityPolicyError(
                f"dangerous pattern matched in args: {pattern.pattern}"
            )


# ---------------------------------------------------------------------------
# Env preparation
# ---------------------------------------------------------------------------


def prepare_subprocess_env(
    *,
    server_id: str,
    user_env: dict[str, str],
) -> dict[str, str]:
    """Build the environment passed to a subprocess.

    Composition (highest priority last):
      1. minimal allowlist read from current process env (PATH etc.)
      2. user-provided env from McpStdioConfig.env

    Keys matching _DENY_INHERIT_KEYS_REGEX are excluded from the parent
    process inheritance step (the user can still pass them explicitly via
    user_env). Returns a fresh dict; never mutates os.environ.
    """
    out: dict[str, str] = {}
    for key in _PASSTHROUGH_ENV_KEYS:
        val = os.environ.get(key)
        if val is None:
            continue
        # Even allowlisted keys are checked for sensitive name shape
        # (defensive — should not match standard system keys).
        if _DENY_INHERIT_KEYS_REGEX.search(key):
            continue
        out[key] = val
    # User env overrides / adds. Caller is responsible for putting actual
    # secrets here (and for storing them in the masked store).
    for k, v in user_env.items():
        out[k] = v
    # Tag every MCP subprocess so the server can detect it's running under
    # this orchestrator (plus useful for logs).
    out["LITERATURE_MCP_SERVER_ID"] = server_id
    return out


def redact_env_for_audit(env: dict[str, str]) -> dict[str, str]:
    """Return a redacted copy of ``env`` safe to log / dump to audit JSONL."""
    out: dict[str, str] = {}
    for k, v in env.items():
        if _DENY_INHERIT_KEYS_REGEX.search(k):
            out[k] = mask_env_value(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# CWD isolation
# ---------------------------------------------------------------------------


def prepare_isolated_cwd(server_id: str) -> Path:
    """Create + return the per-server sandbox cwd under runtime_state.

    Layout: ``runtime_state_path("mcp_servers", "{server_id}", "workdir")``.
    Created with ``mkdir -p`` semantics. Caller passes this path as the
    subprocess cwd so the server can't accidentally write to the project
    tree.
    """
    if not server_id or not isinstance(server_id, str):
        raise McpSecurityPolicyError("server_id must be a non-empty string")
    if "/" in server_id or "\\" in server_id or ".." in server_id:
        raise McpSecurityPolicyError(
            f"server_id contains path-separator characters: {server_id!r}"
        )
    workdir = runtime_state_path("mcp_servers", server_id, "workdir")
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


# ---------------------------------------------------------------------------
# Output caps applied at read time (helper struct used by client_manager)
# ---------------------------------------------------------------------------


@dataclass
class CappedStreamBuffer:
    """Bounded-capacity buffer; over-writes are truncated with a marker."""

    max_chars: int
    chars_written: int = 0
    truncated: bool = False
    parts: list[str] = field(default_factory=list)

    def write(self, chunk: str) -> None:
        if self.truncated:
            return
        remaining = self.max_chars - self.chars_written
        if remaining <= 0:
            self.truncated = True
            return
        if len(chunk) > remaining:
            self.parts.append(chunk[:remaining])
            self.chars_written = self.max_chars
            self.truncated = True
            return
        self.parts.append(chunk)
        self.chars_written += len(chunk)

    def render(self) -> str:
        out = "".join(self.parts)
        if self.truncated:
            out += "\n[...truncated by mcp.security_policy CappedStreamBuffer...]"
        return out


# ---------------------------------------------------------------------------
# Output / preview redaction
# ---------------------------------------------------------------------------


_SECRET_LIKE_TEXT_REGEXES = [
    # Bearer/JWT-ish tokens (long base64-ish strings).
    re.compile(r"\b(?:Bearer|Token)\s+[A-Za-z0-9._\-+/=]{16,}", re.IGNORECASE),
    # api_key / token / secret = "..." or : "..."
    re.compile(
        r"((?:api[_-]?key|secret|token|password|authorization)\s*[:=]\s*['\"]?)"
        r"([A-Za-z0-9._\-+/=]{12,})",
        re.IGNORECASE,
    ),
    # Common provider prefixes.
    re.compile(r"\b(?:sk-|pk-|key-)[A-Za-z0-9_\-]{16,}\b"),
]


def redact_text_for_audit(text: str) -> str:
    """Best-effort redaction of secret-like substrings inside free text.

    Used by tool_result_formatter on tool stdout previews so we don't
    accidentally surface a tool's leaked credentials in the audit log or
    LLM transcript. Conservative: only matches well-known patterns;
    anything novel leaks through (an MCP server feeding us its own
    secrets is itself an integration smell).
    """
    if not text:
        return text
    out = text
    for rx in _SECRET_LIKE_TEXT_REGEXES:
        if rx.groups >= 2:
            out = rx.sub(r"\1***", out)
        else:
            out = rx.sub("***", out)
    return out


# ---------------------------------------------------------------------------
# Streamable HTTP URL guard (Phase 5 / TASK-503)
# ---------------------------------------------------------------------------


_PRIVATE_HOST_PATTERNS = [
    re.compile(r"^localhost$", re.IGNORECASE),
    re.compile(r"^127\."),
    re.compile(r"^10\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[0-1])\."),
    re.compile(r"^169\.254\."),
    re.compile(r"^::1$"),
    re.compile(r"^fc[0-9a-f]{2}:", re.IGNORECASE),  # IPv6 ULA
    re.compile(r"^fe80:", re.IGNORECASE),  # IPv6 link-local
]


def _allow_private_streamable_http() -> bool:
    return os.environ.get(
        "LITERATURE_MCP_HTTP_ALLOW_PRIVATE", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


def validate_streamable_http_url(url: str) -> None:
    """Reject obvious SSRF foot-guns before client_manager opens an HTTP
    session. Even though streamable_http execution is gated behind the
    LITERATURE_ENABLE_MCP_STREAMABLE_HTTP feature flag, the registry
    accepts these URLs at any time — validating here as well keeps the
    audit trail honest.

    Rules:
      - scheme must be http or https
      - host must be present
      - host must not match private/loopback/link-local ranges unless
        LITERATURE_MCP_HTTP_ALLOW_PRIVATE=1
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise McpSecurityPolicyError(
            f"streamable_http URL must use http/https scheme, got {parsed.scheme!r}"
        )
    host = (parsed.hostname or "").strip()
    if not host:
        raise McpSecurityPolicyError("streamable_http URL missing host")
    if _allow_private_streamable_http():
        return
    for pat in _PRIVATE_HOST_PATTERNS:
        if pat.search(host):
            raise McpSecurityPolicyError(
                f"streamable_http host {host!r} is in a private/loopback "
                f"range; set LITERATURE_MCP_HTTP_ALLOW_PRIVATE=1 to allow"
            )


__all__ = [
    "CappedStreamBuffer",
    "DEFAULT_LAUNCH_POLICY",
    "McpSecurityPolicyError",
    "ProcessLaunchPolicy",
    "prepare_isolated_cwd",
    "prepare_subprocess_env",
    "redact_env_for_audit",
    "redact_text_for_audit",
    "validate_stdio_command",
    "validate_streamable_http_url",
]
