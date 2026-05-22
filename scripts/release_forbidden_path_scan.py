"""Slice A0 release gate: forbidden-path scan (DEC-006c, R3 + plan v2 §13.2 #5/6/9 + §15.3)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Third-party runtime CA bundles vendored by trusted upstream packages.
# These specific bundled files are NOT secrets — they are reusable public
# trust roots required for HTTPS / TLS in the runtime:
#   - certifi/cacert.pem    : Mozilla CA bundle
#     (https://pypi.org/project/certifi/)
#   - grpc roots.pem        : gRPC TLS root certificates
#     (https://grpc.io/docs/guides/auth/)
#
# Allowlist is EXACT-PATH (frozenset, not pattern) to prevent any other
# *.pem (e.g. private CA, customer keys) from being bypassed accidentally.
# If PyInstaller bundle layout changes (e.g. _internal/ path drops), the
# allowlist entries become unmatched and *.pem rule re-engages — this is
# intentional and forces a human review on every layout change.
_THIRD_PARTY_PEM_ALLOWLIST = frozenset({
    "_internal/certifi/cacert.pem",
    "_internal/grpc/_cython/_credentials/roots.pem",
})


def _is_forbidden_pem(p: Path) -> bool:
    """Return True if `p` is a .pem path NOT in the third-party CA allowlist."""
    if p.suffix != ".pem":
        return False
    posix = p.as_posix()
    return posix not in _THIRD_PARTY_PEM_ALLOWLIST


FORBIDDEN_RULES = [
    (".env exact", lambda p: p.name == ".env"),
    (".env.* (not .env.example)",
     lambda p: p.name.startswith(".env.") and p.name != ".env.example"),
    ("workspace_artifacts/runtime_state/**",
     lambda p: "runtime_state" in p.parts and "workspace_artifacts" in p.parts),
    ("runtime_credentials.json", lambda p: p.name == "runtime_credentials.json"),
    ("runtime_mcp_servers.json", lambda p: p.name == "runtime_mcp_servers.json"),
    ("mcp_servers/** (audit + workdirs)",
     lambda p: "mcp_servers" in p.parts),
    ("credentials.json", lambda p: p.name == "credentials.json"),
    ("key.txt", lambda p: p.name == "key.txt"),
    ("*.pem (excludes vendored 3rd-party CA bundles)", _is_forbidden_pem),
    ("*.key", lambda p: p.suffix == ".key"),
    ("id_rsa", lambda p: p.name == "id_rsa"),
    ("id_ed25519", lambda p: p.name == "id_ed25519"),
    ("logs/", lambda p: "logs" in p.parts),
    ("chunk_store/", lambda p: "chunk_store" in p.parts),
    ("_rejected/ inside payload", lambda p: "_rejected" in p.parts),
    (".secrets.baseline", lambda p: p.name == ".secrets.baseline"),
]


def check_path(s: str) -> list[str]:
    if not s:
        return []
    p = Path(s)
    out: list[str] = []
    for name, pred in FORBIDDEN_RULES:
        try:
            if pred(p):
                out.append(name)
        except Exception:
            pass
    return out


def file_sha256_prefix(p: Path) -> str:
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    except OSError:
        return ""


def scan_manifest(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [{
            "rule_id": "manifest_unreadable",
            "detector": "forbidden_path/manifest",
            "matched_path": str(path),
            "masked_snippet": f"<manifest_load_failed:{exc.__class__.__name__}>",
            "file_sha256_prefix": "",
            "severity": "blocker",
        }]

    def scan_field(field: str, items: list[Any]) -> None:
        for entry in items or []:
            for key in ("src", "dest"):
                cand = entry.get(key, "") if isinstance(entry, dict) else ""
                for rule in check_path(cand):
                    findings.append({
                        "rule_id": f"manifest:{field}:{key}:{rule}",
                        "detector": "forbidden_path/manifest",
                        "matched_path": str(cand),
                        "masked_snippet": "<not_extracted>",
                        "file_sha256_prefix": "",
                        "severity": "blocker",
                    })

    scan_field("datas", manifest.get("datas", []) or [])
    scan_field("binaries", manifest.get("binaries", []) or [])
    for tree in manifest.get("trees", []) or []:
        for rule in check_path(tree.get("root", "")):
            findings.append({
                "rule_id": f"manifest:tree:{rule}",
                "detector": "forbidden_path/manifest",
                "matched_path": str(tree.get("root", "")),
                "masked_snippet": "<not_extracted>",
                "file_sha256_prefix": "",
                "severity": "blocker",
            })
    return findings


def scan_onedir(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not root.exists():
        return [{
            "rule_id": "onedir_missing",
            "detector": "forbidden_path/onedir",
            "matched_path": str(root),
            "masked_snippet": "<onedir_not_found>",
            "file_sha256_prefix": "",
            "severity": "blocker",
        }]
    for dirpath, _dirs, files in os.walk(root, onerror=lambda e: None):
        for fname in files:
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(root)
            except ValueError:
                rel = full
            for rule in check_path(str(rel)):
                findings.append({
                    "rule_id": f"onedir:{rule}",
                    "detector": "forbidden_path/onedir",
                    "matched_path": str(rel).replace("\\", "/"),
                    "masked_snippet": "<not_extracted>",
                    "file_sha256_prefix": file_sha256_prefix(full),
                    "severity": "blocker",
                })
    return findings


def write_report(findings: list[dict[str, Any]], rejected_dir: Path,
                 stage: str, scan_root: str, build_version: str) -> Path:
    rejected_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = rejected_dir / f"forbidden-path-{stage}-{ts}.json"
    out.write_text(json.dumps({
        "schema_version": "release_gate_report.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_version": build_version,
        "stage": stage,
        "scan_root": scan_root,
        "findings_count": len(findings),
        "findings": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice A0 release gate: forbidden-path scan.")
    parser.add_argument("--mode", required=True, choices=["manifest", "onedir"])
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--rejected-dir", type=Path,
                        default=Path("workspace_artifacts/releases/_rejected"))
    parser.add_argument("--build-version", default="")
    args = parser.parse_args()

    if args.mode == "manifest":
        findings = scan_manifest(args.input.resolve())
    else:
        findings = scan_onedir(args.input.resolve())

    if not findings:
        print(f"[forbidden-path:{args.mode}] OK - no forbidden paths in {args.input}")
        return 0

    rep = write_report(findings, args.rejected_dir.resolve(),
                       stage=f"forbidden_path_{args.mode}",
                       scan_root=str(args.input.resolve()).replace("\\", "/"),
                       build_version=args.build_version)
    print(f"[forbidden-path:{args.mode}] BLOCKED - {len(findings)} finding(s)", file=sys.stderr)
    print(f"[forbidden-path:{args.mode}] report: {rep}", file=sys.stderr)
    for f in findings[:10]:
        print(f"  - {f['rule_id']}  matched_path={f['matched_path']}", file=sys.stderr)
    if len(findings) > 10:
        print(f"  ... ({len(findings) - 10} more in report)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
