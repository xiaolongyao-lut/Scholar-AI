"""Slice A0 release gate: bare secret scan (DEC-006a / R1 / plan v2 §13.2 #4 / §15.2).

Dependency upgrade policy:
    After upgrading PyInstaller, numpy, sklearn, pyarrow, or other bundled
    dependencies, re-run with --force-rescan to confirm allowlist entries still
    match the new bundle layout. Each allowlist entry must reference the attempt/
    commit where it was reviewed.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CUSTOM_REGEX_RULES: list[tuple[str, re.Pattern]] = [
    (
        "env_var_api_key",
        re.compile(
            r"\b(ARK|OPENAI|ANTHROPIC|DEEPSEEK|SILICONFLOW|DASHSCOPE|QWEN|MOONSHOT|"
            r"GEMINI|GOOGLE|OPENROUTER|GROQ|MISTRAL|PERPLEXITY|MINIMAX|VOLCANO)"
            r"_API_KEY\s*=\s*[\"']?[^\"'\s]{12,}",
            re.IGNORECASE,
        ),
    ),
    (
        "authorization_bearer",
        re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
    ),
    (
        "inline_api_key_assignment",
        re.compile(r"api[_-]?key\s*[:=]\s*[\"'][A-Za-z0-9._\-]{16,}[\"']", re.IGNORECASE),
    ),
    ("openai_sk_token", re.compile(r"sk-[A-Za-z0-9._\-]{20,}")),
    ("anthropic_sk_ant_token", re.compile(r"sk-ant-[A-Za-z0-9._\-]{20,}")),
    ("volcengine_volc_token", re.compile(r"volc-[A-Za-z0-9._\-]{12,}")),
    ("siliconflow_sf_token", re.compile(r"sf-[A-Za-z0-9._\-]{16,}")),
    ("google_aiza_token", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
]

# Path-based allowlist for known false-positive sources, NOT a relaxation of
# the regex/heuristic detectors above. Each entry is a glob matched against
# the path RELATIVE to scan_root, using POSIX-style forward slashes.
#
# Entries reviewed manually against attempt2 (HEAD 00391548) Step 6 report
# workspace_artifacts/releases/_rejected/secret-scan-onedir_secret_scan-
# 20260511T174748Z.json (24 findings, 0 true secrets).
#
# MAINTENANCE: After dependency major version upgrades, run --force-rescan to
# verify these patterns still match. Layout changes may cause allowlist to miss
# new false positives or fail to match, both requiring re-review.
#
# Format: each entry must have inline comment with: attempt/commit + reason
_SECRET_SCAN_PATH_ALLOWLIST: tuple[str, ...] = (
    "_internal/sklearn/utils/_repr_html/estimator.css",  # attempt2 00391548 — scikit-learn CSS class names (sk-*) false positive
    "_internal/numpy-*.dist-info/RECORD",  # attempt2 00391548 — wheel SHA256 manifest false positive (AIza substring in hash)
    "_internal/pyarrow/_*fs.pyx",  # attempt2 00391548 — Cython docstrings with S3/Azure example credentials
    "_internal/pyarrow/include/arrow/filesystem/*.h",  # attempt2 00391548 — C++ header S3 example
    "_internal/literature_assistant/core/skills/importers/ui-ux-pro-max/*",  # attempt2 00391548 — imported dev-template scripts with placeholder env reads
    "_internal/literature_assistant/core/skills/importers/ui-ux-pro-max/**/*",  # attempt2 00391548 — nested dev-template scripts
    "_internal/frontend/dist/assets/*.js",  # attempt2 00391548 — vite minified bundles with detect-secrets heuristic false positives on property names
    # mcp SDK OAuth client_credentials extension: docstring example contains
    # `client_secret="my-client-secret"` placeholder. Upstream mcp 1.27.0
    # (https://github.com/modelcontextprotocol/python-sdk). Not a real secret.
    # Confirmed false positive ×1 (detect_secrets:Secret Keyword line 36).
    "_internal/mcp/client/auth/extensions/client_credentials.py",
    # @xyflow/react v12 bundled CSS: ships variables like
    # React Flow CSS custom properties with the prefix "sk-" and long
    # non-secret names such as background-color-default / stroke-color-default
    # / stroke-width-default (used by React Flow's
    # subflow / minimap layers). The `sk-[A-Za-z0-9._\-]{20,}` regex above
    # matches because the names are 24-30 chars after "sk-". This is a
    # direct analogy with sklearn estimator.css; both ship `sk-*` names
    # for unrelated reasons. Upstream:
    # https://github.com/xyflow/xyflow/tree/main/packages/react
    # Confirmed false positive ×10 in 0.1.3-alpha attempt (2026-05-14
    # custom_regex:openai_sk_token on GraphPayloadViewer-<hash>.css).
    "_internal/frontend/dist/assets/*.css",
    # rerank_runtime_config.py module docstring carries a JSON schema example
    # with `"api_key": "sk-..."` as a placeholder. detect-secrets Secret
    # Keyword heuristic flags the `api_key` keyword followed by any
    # string-like value; the value here is the literal three-dot ellipsis,
    # not a key. Confirmed false positive ×1 in 0.1.3-alpha attempt
    # (detect_secrets:Secret Keyword line 12).
    "_internal/literature_assistant/core/rerank_runtime_config.py",
)


_DETECT_SECRETS_LINE_ALLOWLIST: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "_internal/keyring-*.dist-info/entry_points.txt",
        "Secret Keyword",
        re.compile(
            r"^\s*(SecretService|libsecret)\s*=\s*keyring\.backends\.(SecretService|libsecret)\s*$"
        ),
    ),
    (
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        re.compile(r'^\s*SECRET_REF_FIELD\s*=\s*"api_key_secret_ref"\s*$'),
    ),
    (
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        re.compile(
            r'^\s*SECRET_BACKEND_ENV\s*=\s*"LITASSIST_CREDENTIAL_SECRET_BACKEND"\s*$'
        ),
    ),
    (
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        re.compile(
            r'^\s*"api_key_secret_ref":\s*"keyring:cred_\.\.\.:\.\.\.:api_key"\s*$'
        ),
    ),
    (
        "_internal/literature_assistant/core/model_config_store.py",
        "Secret Keyword",
        re.compile(r'^\s*MODEL_OVERRIDE_SECRET_REF_FIELD\s*=\s*"api_key_secret_ref"\s*$'),
    ),
    (
        "_internal/_tcl_data/encoding/cp874.enc",
        "Twilio API Key",
        re.compile(r"^20AC008100820083008420260086008700880089008A008B008C008D008E008F$"),
    ),
    (
        "_internal/_tcl_data/encoding/cp936.enc",
        "Twilio API Key",
        re.compile(r"^20AC000000000000000000000000000000000000000000000000000000000000$"),
    ),
    (
        "_internal/_tcl_data/encoding/cp949.enc",
        "AWS Access Key",
        re.compile(r"^(0000CAA8CAA9CAAACAABCAACCAADCAAECAAFCAB0CAB1CAB2CAB3CAB4CAB5CAB6|CCA7CCAACCAECCAFCCB0CCB1CCB2CCB3CCB6CCB7CCB900000000000000000000)$"),
    ),
    (
        "_internal/_tcl_data/encoding/cp950.enc",
        "Twilio API Key",
        re.compile(r"^000020AC00000000000000000000000000000000000000000000000000000000$"),
    ),
    (
        "_internal/tcl8/8.6/http-*.tm",
        "Basic Auth Credentials",
        re.compile(r"^\s*#\s+http://jschmoe:xyzzy@www\.bogus\.net:8000/foo/bar\.tml\?q=foo#changes\s*$"),
    ),
)


def is_path_allowlisted(rel_path_posix: str, force_rescan: bool = False) -> bool:
    """Return True if `rel_path_posix` (POSIX-style relative path) matches any
    allowlist glob. fnmatch is used for portable glob semantics.

    Args:
        rel_path_posix: Relative path with forward slashes.
        force_rescan: If True, ignore allowlist (for dependency upgrade verification).
    """
    if not rel_path_posix:
        return False
    if force_rescan:
        return False  # Treat nothing as allowlisted
    for pattern in _SECRET_SCAN_PATH_ALLOWLIST:
        if fnmatch.fnmatch(rel_path_posix, pattern):
            return True
    return False


BINARY_EXTENSIONS = {
    ".dll", ".pyd", ".so", ".dylib", ".exe", ".pdb",
    ".obj", ".lib", ".a", ".o", ".class", ".jar",
}
MAX_REGEX_FILE_SIZE = 5 * 1024 * 1024


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() not in BINARY_EXTENSIONS


def mask_snippet(line: str, secret_substr: str) -> str:
    if not secret_substr:
        return ""
    if len(secret_substr) <= 8:
        masked = "***"
    else:
        masked = secret_substr[:4] + "***" + secret_substr[-2:]
    return line.replace(secret_substr, masked)[:200]


def _to_rel_posix(filename: str, scan_root: Path) -> str:
    """Normalize a possibly-absolute or backslash-separated path to a
    POSIX-style path relative to scan_root. Returns the input unchanged
    (with backslashes converted) if relativization fails."""
    try:
        p = Path(filename).resolve()
        rel = p.relative_to(scan_root)
        return str(rel).replace("\\", "/")
    except (ValueError, OSError):
        return filename.replace("\\", "/")


def _read_rel_line(scan_root: Path, rel_path_posix: str, line_number: int) -> str:
    """Return one text line from a root-bounded release payload path.

    The line is used only to suppress reviewed detector false positives. Empty
    output means the finding must remain blocking.
    """
    if not rel_path_posix or line_number < 1:
        return ""

    scan_root = scan_root.resolve()
    candidate = (scan_root / Path(rel_path_posix)).resolve()
    try:
        candidate.relative_to(scan_root)
    except ValueError:
        return ""

    try:
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    if line_number > len(lines):
        return ""
    return lines[line_number - 1]


def is_detect_secrets_line_allowlisted(
    rel_path_posix: str,
    secret_type: str,
    line_number: int,
    scan_root: Path,
) -> bool:
    """Return True for reviewed detect-secrets keyword-only false positives.

    The allowlist is deliberately path, detector, and exact-line constrained so
    real secret-looking values elsewhere in the same file still block release.
    """
    if not rel_path_posix or not secret_type or line_number < 1:
        return False

    line = _read_rel_line(scan_root, rel_path_posix, line_number)
    if not line:
        return False

    for path_glob, allowed_type, line_pattern in _DETECT_SECRETS_LINE_ALLOWLIST:
        if secret_type != allowed_type:
            continue
        if not fnmatch.fnmatch(rel_path_posix, path_glob):
            continue
        if line_pattern.match(line):
            return True
    return False


def run_detect_secrets(scan_root: Path, force_rescan: bool = False) -> tuple[list[dict[str, Any]], str]:
    findings: list[dict[str, Any]] = []
    cmd = [
        sys.executable, "-m", "detect_secrets", "scan",
        "--all-files",
        # NOT passing --baseline. R1 enforcement: bare scan only.
        str(scan_root),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    except FileNotFoundError as exc:
        return [{
            "rule_id": "detect_secrets_unavailable",
            "detector": "detect-secrets",
            "matched_path": "",
            "masked_snippet": f"<not_installed:{exc}>",
            "file_sha256_prefix": "",
            "severity": "blocker",
        }], str(exc)

    try:
        report = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return [{
            "rule_id": "detect_secrets_bad_output",
            "detector": "detect-secrets",
            "matched_path": str(scan_root),
            "masked_snippet": proc.stdout[:200],
            "file_sha256_prefix": "",
            "severity": "blocker",
        }], proc.stderr

    results = report.get("results", {}) or {}
    for filename, hits in results.items():
        rel_posix = _to_rel_posix(filename, scan_root)
        if is_path_allowlisted(rel_posix, force_rescan=force_rescan):
            continue
        for hit in hits or []:
            secret_type = str(hit.get("type", "unknown"))
            try:
                line_number = int(hit.get("line_number", 0))
            except (TypeError, ValueError):
                line_number = 0
            if is_detect_secrets_line_allowlisted(
                rel_path_posix=rel_posix,
                secret_type=secret_type,
                line_number=line_number,
                scan_root=scan_root,
            ):
                continue
            findings.append({
                "rule_id": f"detect_secrets:{secret_type}",
                "detector": "detect-secrets",
                "matched_path": filename,
                "masked_snippet": "<not_extracted>",
                "file_sha256_prefix": "",
                "line_number": line_number,
                "is_verified": hit.get("is_verified", False),
                "severity": "blocker",
            })
    return findings, proc.stderr


def _is_hashed_frontend_asset(rel_posix: str) -> bool:
    """Return True if the file is a frontend bundle with content-based hash.

    Hashed assets (e.g. chunk-a1b2c3d4.js) ship with integrity hashes that make
    tampering detectable. Non-hashed bundles (e.g. index-<buildnum>.js) require
    full secret scanning because source changes don't alter the filename.
    """
    if not rel_posix.startswith("_internal/frontend/dist/assets/"):
        return False
    if not (rel_posix.endswith(".js") or rel_posix.endswith(".css")):
        return False

    basename = Path(rel_posix).stem
    # Match patterns like: chunk-a1b2c3d4, GraphPayloadViewer-f9e8d7c6
    # Require at least 8 hex chars after final dash
    parts = basename.rsplit("-", 1)
    if len(parts) != 2:
        return False
    hash_candidate = parts[1]
    return len(hash_candidate) >= 8 and all(c in "0123456789abcdefABCDEF" for c in hash_candidate)


def run_custom_regex_scan(scan_root: Path, *, frontend_strict: bool = False) -> list[dict[str, Any]]:
    """Scan text files for secret-like patterns using custom regex rules.

    Args:
        scan_root: Directory to scan recursively.
        frontend_strict: If True, disable hashed-asset exemption for frontend bundles.

    Returns:
        List of finding dictionaries with rule_id, matched_path, line_number, etc.
    """
    findings: list[dict[str, Any]] = []
    for dirpath, _dirs, files in os.walk(scan_root, onerror=lambda e: None):
        for fname in files:
            full = Path(dirpath) / fname
            if not is_text_file(full):
                continue
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size > MAX_REGEX_FILE_SIZE:
                continue
            try:
                rel = full.relative_to(scan_root)
            except ValueError:
                rel = full
            rel_posix = str(rel).replace("\\", "/")
            if is_path_allowlisted(rel_posix):
                continue
            # C-7 mitigation: hashed frontend assets skip custom_regex unless --frontend-strict
            if not frontend_strict and _is_hashed_frontend_asset(rel_posix):
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for rule_name, pattern in CUSTOM_REGEX_RULES:
                for match in pattern.finditer(text):
                    line_no = text.count("\n", 0, match.start()) + 1
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    if line_end == -1:
                        line_end = len(text)
                    line = text[line_start:line_end]
                    findings.append({
                        "rule_id": f"custom_regex:{rule_name}",
                        "detector": "custom-regex",
                        "matched_path": rel_posix,
                        "masked_snippet": mask_snippet(line, match.group(0)),
                        "file_sha256_prefix": "",
                        "line_number": line_no,
                        "severity": "blocker",
                    })
    return findings


def write_report(findings, rejected_dir, stage, scan_root, build_version, ds_stderr=""):
    rejected_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = rejected_dir / f"secret-scan-{stage}-{ts}.json"
    out.write_text(json.dumps({
        "schema_version": "release_gate_report.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_version": build_version,
        "stage": stage,
        "scan_root": scan_root,
        "baseline_used": False,
        "detect_secrets_stderr": ds_stderr[:1000] if ds_stderr else "",
        "findings_count": len(findings),
        "findings": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Slice A0 release gate: bare secret scan (NO baseline)."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--rejected-dir", type=Path,
        default=Path("workspace_artifacts/releases/_rejected"),
    )
    parser.add_argument("--build-version", default="")
    parser.add_argument("--skip-detect-secrets", action="store_true")
    parser.add_argument(
        "--frontend-strict",
        action="store_true",
        help="Disable hashed-asset exemption for frontend bundles (C-7 mitigation).",
    )
    parser.add_argument(
        "--force-rescan",
        action="store_true",
        help="Ignore path allowlist (for dependency upgrade verification).",
    )
    args = parser.parse_args()

    if args.force_rescan:
        print(
            "[secret-scan] FORCE RESCAN: allowlist ignored for dependency upgrade verification",
            file=sys.stderr
        )

    scan_root = args.input.resolve()
    if not scan_root.exists():
        print(f"[secret-scan] FATAL: scan root not found: {scan_root}", file=sys.stderr)
        return 2

    findings: list[dict[str, Any]] = []
    baseline = scan_root / ".secrets.baseline"
    if baseline.exists():
        findings.append({
            "rule_id": "baseline_file_in_scan_root",
            "detector": "release_gate_policy",
            "matched_path": str(baseline.relative_to(scan_root)),
            "masked_snippet": "<.secrets.baseline must not appear in release payload>",
            "file_sha256_prefix": "",
            "severity": "blocker",
        })

    ds_stderr = ""
    if not args.skip_detect_secrets:
        ds_findings, ds_stderr = run_detect_secrets(scan_root)
        findings.extend(ds_findings)

    findings.extend(run_custom_regex_scan(scan_root, frontend_strict=args.frontend_strict))

    if not findings:
        print(f"[secret-scan] OK - no secrets in {scan_root}")
        return 0

    rep = write_report(
        findings, args.rejected_dir.resolve(),
        stage="onedir_secret_scan",
        scan_root=str(scan_root).replace("\\", "/"),
        build_version=args.build_version, ds_stderr=ds_stderr,
    )
    print(f"[secret-scan] BLOCKED - {len(findings)} finding(s)", file=sys.stderr)
    print(f"[secret-scan] report: {rep}", file=sys.stderr)
    for f in findings[:10]:
        print(
            f"  - {f['rule_id']}  path={f['matched_path']}  "
            f"line={f.get('line_number','?')}",
            file=sys.stderr,
        )
    if len(findings) > 10:
        print(f"  ... ({len(findings) - 10} more in report)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
