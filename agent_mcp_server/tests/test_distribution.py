"""Distribution template tests for Codex and Claude local MCP setup."""

import json
import os
import platform
import subprocess
import tomllib
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "agent_mcp_server" / "bin" / "lit-assistant-mcp.ps1"
CODEX_CONFIG = REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "config.example.toml"
CODEX_PACKAGING = REPO_ROOT / "agent_mcp_server" / "packaging" / "codex"
CLAUDE_DESKTOP = REPO_ROOT / "agent_mcp_server" / "packaging" / "claude-desktop"
CLAUDE_CODE = REPO_ROOT / "agent_mcp_server" / "packaging" / "claude-code"
GENERIC_REPO_ROOT = "C:\\path\\to\\Scholar-AI"
GENERIC_WRAPPER = f"{GENERIC_REPO_ROOT}\\agent_mcp_server\\bin\\lit-assistant-mcp.ps1"


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from a package file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return payload


def test_codex_config_example_points_to_shared_wrapper() -> None:
    """Codex raw config must use the shared PowerShell wrapper."""
    payload = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))

    server = payload["mcp_servers"]["literature_assistant"]
    assert server["command"] == "powershell"
    assert GENERIC_WRAPPER in server["args"]
    assert server["cwd"] == GENERIC_REPO_ROOT
    assert server["env"]["LITERATURE_ASSISTANT_REPO_ROOT"] == GENERIC_REPO_ROOT
    assert server["env"]["LITERATURE_ASSISTANT_BASE_URL"] == "http://127.0.0.1:8000"
    assert server["env"]["LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS"] == "1"
    assert server["default_tools_approval_mode"] == "prompt"


def test_claude_desktop_config_example_points_to_shared_wrapper() -> None:
    """Claude Desktop config must use the shared PowerShell wrapper."""
    payload = _load_json(CLAUDE_DESKTOP / "claude_desktop_config.example.json")

    server = payload["mcpServers"]["literature-assistant"]
    assert server["command"] == "powershell"
    assert GENERIC_WRAPPER in server["args"]
    assert server["env"]["LITERATURE_ASSISTANT_REPO_ROOT"] == GENERIC_REPO_ROOT
    assert server["env"]["LITERATURE_ASSISTANT_BASE_URL"] == "http://127.0.0.1:8000"
    assert server["env"]["LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS"] == "1"


def test_distribution_templates_do_not_embed_local_absolute_paths() -> None:
    """Committed local-distribution templates must stay portable across machines."""
    template_paths = [
        CODEX_CONFIG,
        CLAUDE_DESKTOP / "claude_desktop_config.example.json",
    ]
    forbidden_fragments = [
        str(REPO_ROOT),
        str(REPO_ROOT).replace("\\", "\\\\"),
        "C:\\Users\\xiao",
        "C:\\\\Users\\\\xiao",
        "Desktop\\tools\\Modular-Pipeline-Script",
        "Desktop\\\\tools\\\\Modular-Pipeline-Script",
    ]

    for path in template_paths:
        text = path.read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{path} embeds local path fragment: {fragment}"


def test_legacy_local_plugin_packages_are_not_published() -> None:
    """Current direction is direct MCP config, not local plugin or MCPB packages."""
    removed_paths = [
        REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "plugin" / "README.md",
        REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "plugin" / ".mcp.json",
        REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "plugin" / ".codex-plugin" / "plugin.json",
        REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "marketplace.example.json",
        REPO_ROOT / "agent_mcp_server" / "packaging" / "claude-desktop" / "manifest.json",
        REPO_ROOT / "agent_mcp_server" / "packaging" / "claude-desktop" / "build_mcpb.ps1",
    ]

    for path in removed_paths:
        assert not path.exists(), f"legacy plugin/MCPB package file should stay absent: {path}"


def test_claude_code_script_prints_non_mutating_add_command() -> None:
    """Claude Code helper should support a safe print-only mode."""
    if platform.system() != "Windows":
        return

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CLAUDE_CODE / "add-user.ps1"),
            "-PrintOnly",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert "claude mcp add literature-assistant --scope user --transport stdio" in completed.stdout
    assert str(WRAPPER) in completed.stdout


def test_codex_script_prints_non_mutating_add_command() -> None:
    """Codex helper should support a safe print-only mode."""
    if platform.system() != "Windows":
        return

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CODEX_PACKAGING / "add-user.ps1"),
            "-PrintOnly",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert "codex mcp add literature_assistant" in completed.stdout
    assert str(WRAPPER) in completed.stdout


def test_wrapper_self_test_registers_expected_tools() -> None:
    """Wrapper self-test must launch through the repo venv and import MCP tools."""
    if platform.system() != "Windows":
        return

    env = os.environ.copy()
    env["LITERATURE_ASSISTANT_BASE_URL"] = "http://127.0.0.1:8000"
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
            "-SelfTest",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert "lit-assistant-mcp self-test ok" in completed.stdout
    assert "tool_count=26" in completed.stdout
