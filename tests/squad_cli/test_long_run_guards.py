from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SQUAD_LOCK = REPO_ROOT / "tools" / "squad" / "squad-lock.ps1"
AUTOPILOT = REPO_ROOT / "tools" / "squad" / "start-squad-autopilot.ps1"
LONG_RUN = REPO_ROOT / "tools" / "squad" / "start-long-run.ps1"


def run_powershell_file(script: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=env,
    )


def test_acquire_identity_same_pid_is_reentrant_and_does_not_rejoin(tmp_path: Path) -> None:
    state_dir = tmp_path / ".squad" / "state"
    state_dir.mkdir(parents=True)

    cli_log = tmp_path / "cli.log"
    fake_cli = tmp_path / "fake_squad.ps1"
    fake_cli.write_text(
        "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)\n"
        f"Add-Content -Path '{cli_log}' -Value ($Args -join ' ')\n"
        "exit 0\n",
        encoding="utf-8",
    )

    harness = tmp_path / "harness.ps1"
    harness.write_text(
        f"$env:SQUAD_TEST_ROOT = '{tmp_path}'\n"
        f"$env:SQUAD_REAL_CLI = '{fake_cli}'\n"
        f". '{SQUAD_LOCK}'\n"
        "$null = Acquire-SquadIdentity -Role 'owner' -OwnerPid 4242\n"
        "$null = Acquire-SquadIdentity -Role 'owner' -OwnerPid 4242\n"
        f"$callCount = if (Test-Path '{cli_log}') {{ (Get-Content '{cli_log}' | Measure-Object).Count }} else {{ 0 }}\n"
        "Write-Output ('CALLS=' + $callCount)\n",
        encoding="utf-8",
    )

    result = run_powershell_file(harness)
    combined = (result.stdout or "") + (result.stderr or "")

    assert result.returncode == 0, combined
    assert "CALLS=1" in combined


def test_start_squad_autopilot_skips_daemons_with_live_locks(tmp_path: Path) -> None:
    script_dir = tmp_path / "tools" / "squad"
    script_dir.mkdir(parents=True)
    (script_dir / "start-squad-autopilot.ps1").write_text(AUTOPILOT.read_text(encoding="utf-8"), encoding="utf-8")

    state_dir = tmp_path / ".squad" / "state"
    state_dir.mkdir(parents=True)

    harness = tmp_path / "autopilot-harness.ps1"
    harness.write_text(
        f"$stateDir = '{state_dir}'\n"
        "$pidText = [string]$PID\n"
        "Set-Content -Path (Join-Path $stateDir 'squad-watcher.lock') -Value $pidText -Encoding ascii\n"
        "Set-Content -Path (Join-Path $stateDir 'squad-sweeper.lock') -Value $pidText -Encoding ascii\n"
        "$global:processCalls = 0\n"
        "function Start-Process { param([string]$FilePath,[object[]]$ArgumentList,[string]$WindowStyle,[switch]$PassThru) $global:processCalls++; return [pscustomobject]@{ Id = 99999 } }\n"
        "function Start-Sleep { param([int]$Milliseconds) }\n"
        f". '{script_dir / 'start-squad-autopilot.ps1'}'\n"
        "Write-Output ('PROCESS_CALLS=' + $global:processCalls)\n",
        encoding="utf-8",
    )

    result = run_powershell_file(harness)
    combined = (result.stdout or "") + (result.stderr or "")

    assert result.returncode == 0, combined
    assert "PROCESS_CALLS=0" in combined


def test_start_long_run_skips_eval_daemon_with_live_lock(tmp_path: Path) -> None:
    script_dir = tmp_path / "tools" / "squad"
    script_dir.mkdir(parents=True)
    (script_dir / "start-long-run.ps1").write_text(LONG_RUN.read_text(encoding="utf-8"), encoding="utf-8")
    (script_dir / "rag-eval-daemon.ps1").write_text("Write-Host 'stub rag eval daemon'\n", encoding="utf-8")

    state_dir = tmp_path / ".squad" / "state"
    state_dir.mkdir(parents=True)

    harness = tmp_path / "long-run-harness.ps1"
    harness.write_text(
        f"$stateDir = '{state_dir}'\n"
        "$pidText = [string]$PID\n"
        "Set-Content -Path (Join-Path $stateDir 'rag-eval-daemon.lock') -Value $pidText -Encoding ascii\n"
        "$global:processCalls = 0\n"
        "function Start-Process { param([string]$FilePath,[object[]]$ArgumentList,[string]$WindowStyle,[switch]$PassThru,[string]$WorkingDirectory) $global:processCalls++; return [pscustomobject]@{ Id = 99999 } }\n"
        "function Start-Sleep { param([int]$Milliseconds) }\n"
        f"& '{script_dir / 'start-long-run.ps1'}' -SkipAutopilot -SkipMorpheus\n"
        "Write-Output ('PROCESS_CALLS=' + $global:processCalls)\n",
        encoding="utf-8",
    )

    result = run_powershell_file(harness)
    combined = (result.stdout or "") + (result.stderr or "")

    assert result.returncode == 0, combined
    assert "PROCESS_CALLS=0" in combined
