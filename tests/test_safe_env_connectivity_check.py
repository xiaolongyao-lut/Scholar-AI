from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "safe_env_connectivity_check.py"
SPEC = importlib.util.spec_from_file_location("safe_env_connectivity_check", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


ProbeResult = MODULE.ProbeResult


def test_parse_groups_pairs_repeated_key_and_base_blocks() -> None:
    lines = [
        "API_KEY=key-a\n",
        "BASE_URL=https://a.example.com\n",
        "MODEL=model-a\n",
        "API_KEY=key-b\n",
        "BASE_URL=https://b.example.com\n",
    ]

    groups = MODULE.parse_groups(lines)

    assert len(groups) == 2
    assert groups[0].key_var == "API_KEY"
    assert groups[0].key_value == "key-a"
    assert groups[0].base_url == "https://a.example.com"
    assert groups[1].key_value == "key-b"
    assert groups[1].base_url == "https://b.example.com"


def test_build_team_summary_marks_usable_entries_and_counts() -> None:
    results = [
        ProbeResult(
            index=0,
            keyVar="API_KEY",
            baseVar="BASE_URL",
            baseUrl="https://ok.example.com",
            method="GET",
            status=200,
            errorClass=None,
            verdict="ok",
            maskedKey="sk-a...1234",
        ),
        ProbeResult(
            index=1,
            keyVar="API_KEY",
            baseVar="BASE_URL",
            baseUrl="https://warn.example.com",
            method="POST",
            status=400,
            errorClass=None,
            verdict="reachable_but_error",
            maskedKey="sk-b...5678",
        ),
        ProbeResult(
            index=2,
            keyVar="API_KEY",
            baseVar="BASE_URL",
            baseUrl="https://bad.example.com",
            method="GET",
            status=None,
            errorClass="timeout",
            verdict="unreachable",
            maskedKey="sk-c...9999",
        ),
    ]

    summary = MODULE.build_team_summary(results)

    assert summary["teamReady"] is True
    assert summary["counts"]["ok"] == 1
    assert summary["counts"]["reachable_but_error"] == 1
    assert summary["counts"]["unreachable"] == 1
    assert [entry["baseUrl"] for entry in summary["usableEntries"]] == [
        "https://ok.example.com",
        "https://warn.example.com",
    ]
    assert summary["strictFailures"][0]["baseUrl"] == "https://bad.example.com"


def test_determine_exit_code_honors_strict_failures() -> None:
    ok_results = [
        ProbeResult(
            index=0,
            keyVar="API_KEY",
            baseVar="BASE_URL",
            baseUrl="https://ok.example.com",
            method="GET",
            status=200,
            errorClass=None,
            verdict="ok",
            maskedKey="sk-a...1234",
        )
    ]
    bad_results = [
        ProbeResult(
            index=1,
            keyVar="API_KEY",
            baseVar="BASE_URL",
            baseUrl="https://bad.example.com",
            method="GET",
            status=401,
            errorClass=None,
            verdict="auth_failed",
            maskedKey="sk-b...5678",
        )
    ]

    assert MODULE.determine_exit_code(ok_results, strict=False) == 0
    assert MODULE.determine_exit_code(ok_results, strict=True) == 0
    assert MODULE.determine_exit_code(bad_results, strict=False) == 0
    assert MODULE.determine_exit_code(bad_results, strict=True) == 2
