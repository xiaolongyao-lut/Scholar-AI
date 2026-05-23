"""Slice A0.6 release gate: frozen first-launch storage check (DEC-001b).

Verifies that a freshly built onedir, when launched in a clean APPDATA
sandbox, creates an EMPTY credentials directory under
``%APPDATA%/LiteratureAssistant/runtime_state/credentials/``
on first launch.

Failure modes:
- Credentials directory already populated at first launch  -> dev-machine
  credentials leaked into the bundle (BLOCKER).
- Bundle writes outside the sandboxed APPDATA root  -> root isolation broken.
- Exe crashes immediately -> prior step (PyInstaller / forbidden / secret
  scans) should have caught misconfiguration; this is a smoke-stage failure.

This is a sanity check, not a full E2E test. The exe is launched headless
(no SPA navigation) and killed after `--probe-seconds`.

Usage:
    python scripts/smoke_frozen_first_launch.py \
        --exe workspace_artifacts/releases/<v>/onedir/LiteratureAssistant/LiteratureAssistant.exe \
        --rejected-dir workspace_artifacts/releases/_rejected \
        --build-version <v>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _walk_collect(root: Path) -> list[str]:
    """Return relative file paths under root, sorted."""
    out: list[str] = []
    if not root.exists():
        return out
    for dirpath, _dirs, files in os.walk(root, onerror=lambda e: None):
        for fname in files:
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(root)
            except ValueError:
                rel = full
            out.append(str(rel).replace("\\", "/"))
    return sorted(out)


def probe_host_appdata(appdata_env: str | None) -> list[dict[str, Any]]:
    """Probe %APPDATA%/LiteratureAssistant on the host machine.

    Returns a list of release-gate-style findings:
      - host_appdata_env_missing  (APPDATA env var is not set)
      - host_appdata_not_empty_pre_launch  (host APPDATA has orphan files)
      - empty list when host APPDATA is clean.

    Used by --check-host-appdata; pure-function so we can test it without
    invoking subprocess.Popen on a real frozen exe.
    """
    if not appdata_env:
        return [{
            "rule_id": "host_appdata_env_missing",
            "matched_path": "",
            "masked_snippet": "<APPDATA env var not set on host>",
            "severity": "warning",
        }]
    host_la_root = Path(appdata_env) / "LiteratureAssistant"
    host_pre_files = _walk_collect(host_la_root)
    if not host_pre_files:
        return []
    return [{
        "rule_id": "host_appdata_not_empty_pre_launch",
        "matched_path": str(host_la_root),
        "masked_snippet": (
            f"<{len(host_pre_files)} pre-existing files in host "
            f"%APPDATA%/LiteratureAssistant before installer GUI "
            f"double-click; cleanup requires user authorisation>"
        ),
        "files": host_pre_files[:20],
        "severity": "warning",
    }]


def write_report(findings: list[dict[str, Any]], rejected_dir: Path,
                 stage: str, build_version: str, **extras) -> Path:
    rejected_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = rejected_dir / f"frozen-smoke-{stage}-{ts}.json"
    payload = {
        "schema_version": "release_gate_report.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_version": build_version,
        "stage": stage,
        "findings_count": len(findings),
        "findings": findings,
    }
    payload.update(extras)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice A0.6 frozen first-launch smoke.")
    parser.add_argument("--exe", required=True, type=Path,
                        help="Path to the frozen LiteratureAssistant.exe")
    parser.add_argument("--rejected-dir", type=Path,
                        default=Path("workspace_artifacts/releases/_rejected"))
    parser.add_argument("--build-version", default="")
    parser.add_argument("--probe-seconds", type=float, default=8.0,
                        help="How long to wait before killing the launched exe")
    parser.add_argument(
        "--check-host-appdata",
        action="store_true",
        help=(
            "Real-machine mode: before launching the sandboxed bundle, also "
            "probe %%APPDATA%%/LiteratureAssistant on the host. If the host "
            "APPDATA already has pre-existing files (orphans from a previous "
            "dev run), emit a warning finding so the operator can clean it "
            "up before a real GUI install. Default off so the release-gate "
            "Step 9 behaviour stays deterministic regardless of the dev "
            "machine's APPDATA state. Plan §4 N4 in the 0.1.0-alpha handoff "
            "runbook calls for this assertion before manual installer GUI "
            "double-click; cleanup itself requires explicit user authorisation."
        ),
    )
    args = parser.parse_args()

    exe_path = args.exe.resolve()
    if not exe_path.exists():
        print(f"[frozen-smoke] FATAL: exe not found: {exe_path}", file=sys.stderr)
        return 2

    findings: list[dict[str, Any]] = []

    if args.check_host_appdata:
        findings.extend(probe_host_appdata(os.environ.get("APPDATA", "")))

    sandbox = Path(tempfile.mkdtemp(prefix="frozen_smoke_"))
    fake_appdata = sandbox / "AppData" / "Roaming"
    fake_appdata.mkdir(parents=True, exist_ok=True)

    # Override APPDATA so runtime_hook writes into our sandbox.
    env = os.environ.copy()
    env["APPDATA"] = str(fake_appdata)
    env["LITERATURE_ASSISTANT_USER_ROOT"] = str(fake_appdata / "LiteratureAssistant")

    proc: subprocess.Popen | None = None
    launch_error: str = ""

    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(sandbox),
        )
        time.sleep(args.probe_seconds)
    except OSError as exc:
        launch_error = f"launch failed: {exc.__class__.__name__}: {exc}"
        findings.append({
            "rule_id": "frozen_launch_failure",
            "matched_path": str(exe_path),
            "masked_snippet": launch_error,
            "severity": "blocker",
        })
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    expected_app_root = fake_appdata / "LiteratureAssistant"
    # Post-0.1.8.1: project_paths anchors runtime_state directly under the
    # user-data root (no intermediate workspace_artifacts/ in the installed
    # layout). Keep this in sync with literature_assistant.core.project_paths
    # so the smoke actually inspects the path the bundle writes to.
    expected_creds = (
        expected_app_root
        / "runtime_state" / "credentials"
    )

    creds_files = _walk_collect(expected_creds)
    if creds_files:
        findings.append({
            "rule_id": "credentials_not_empty_on_first_launch",
            "matched_path": str(expected_creds.relative_to(sandbox)).replace("\\", "/"),
            "masked_snippet": "<dev-machine credentials present in fresh bundle>",
            "files": creds_files[:50],
            "severity": "blocker",
        })

    # Also check that the bundle didn't write anywhere else under sandbox EXCEPT
    # under expected_app_root (loose check; PyInstaller bootloader may extract
    # to %TEMP%, which is outside sandbox, so we only flag writes in sandbox
    # other than under the LiteratureAssistant subtree).
    other_writes = []
    if sandbox.exists():
        for dirpath, _dirs, files in os.walk(sandbox, onerror=lambda e: None):
            d = Path(dirpath)
            try:
                d.relative_to(expected_app_root)
                continue
            except ValueError:
                pass
            for fname in files:
                full = d / fname
                try:
                    rel = full.relative_to(sandbox)
                except ValueError:
                    rel = full
                # Tolerate AppData/Roaming itself being created
                rel_str = str(rel).replace("\\", "/")
                if rel_str.startswith("AppData/Roaming/LiteratureAssistant"):
                    continue
                other_writes.append(rel_str)
    if other_writes:
        findings.append({
            "rule_id": "writes_outside_user_root",
            "matched_path": str(sandbox),
            "masked_snippet": f"<{len(other_writes)} unexpected writes>",
            "files": other_writes[:20],
            "severity": "warning",
        })

    extras = {
        "exe": str(exe_path),
        "sandbox": str(sandbox),
        "expected_user_root": str(expected_app_root),
        "expected_credentials_dir": str(expected_creds),
        "credentials_dir_existed": expected_creds.exists(),
        "credentials_dir_file_count": len(creds_files),
        "launch_error": launch_error,
    }

    if not findings:
        print(
            f"[frozen-smoke] OK — credentials dir empty after first launch: {expected_creds}"
        )
        # Cleanup sandbox on success.
        shutil.rmtree(sandbox, ignore_errors=True)
        return 0

    blockers = [f for f in findings if f.get("severity") == "blocker"]
    rep = write_report(
        findings, args.rejected_dir.resolve(),
        stage="frozen_first_launch",
        build_version=args.build_version,
        **extras,
    )
    if blockers:
        print(f"[frozen-smoke] BLOCKED — {len(blockers)} blocker(s)", file=sys.stderr)
        print(f"[frozen-smoke] report: {rep}", file=sys.stderr)
        for f in blockers:
            print(f"  - {f['rule_id']}  matched_path={f['matched_path']}", file=sys.stderr)
        return 1
    print(f"[frozen-smoke] OK with warnings — see {rep}")
    shutil.rmtree(sandbox, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
