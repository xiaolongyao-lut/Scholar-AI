"""Distribution packaging tests for Codex and Claude local MCP setup."""

import json
import os
import platform
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "agent_mcp_server" / "bin" / "lit-assistant-mcp.ps1"
CODEX_CONFIG = REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "config.example.toml"
CODEX_PACKAGING = REPO_ROOT / "agent_mcp_server" / "packaging" / "codex"
CODEX_PLUGIN = REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "plugin"
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


def test_codex_plugin_manifest_and_mcp_config_are_valid() -> None:
    """Codex plugin must bundle both a skill and MCP config."""
    manifest = _load_json(CODEX_PLUGIN / ".codex-plugin" / "plugin.json")
    mcp_config = _load_json(CODEX_PLUGIN / ".mcp.json")
    marketplace = _load_json(REPO_ROOT / "agent_mcp_server" / "packaging" / "codex" / "marketplace.example.json")

    assert manifest["name"] == "literature-assistant-toolbox"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert (CODEX_PLUGIN / "skills" / "literature-toolbox" / "SKILL.md").is_file()

    server = mcp_config["mcpServers"]["literature_assistant"]
    assert server["command"] == "powershell"
    assert GENERIC_WRAPPER in server["args"]
    assert server["cwd"] == GENERIC_REPO_ROOT
    assert server["env"]["LITERATURE_ASSISTANT_REPO_ROOT"] == GENERIC_REPO_ROOT
    assert server["env"]["LITERATURE_ASSISTANT_BASE_URL"] == "http://127.0.0.1:8000"
    assert server["env"]["LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS"] == "1"
    assert marketplace["plugins"][0]["source"]["path"] == "./plugin"


def test_claude_desktop_manifest_uses_packaged_wrapper_and_repo_root_config() -> None:
    """MCPB manifest must be portable while locating the external repo safely."""
    manifest = _load_json(CLAUDE_DESKTOP / "manifest.json")
    config = manifest["server"]["mcp_config"]

    assert manifest["manifest_version"] == "0.3"
    assert manifest["name"] == "literature-assistant-toolbox"
    assert config["command"] == "powershell"
    assert "${__dirname}/server/lit-assistant-mcp.ps1" in config["args"]
    assert config["env"]["LITERATURE_ASSISTANT_REPO_ROOT"] == "${user_config.repository_root}"
    assert manifest["user_config"]["repository_root"]["default"] == GENERIC_REPO_ROOT
    assert manifest["user_config"]["backend_base_url"]["default"] == "http://127.0.0.1:8000"


def test_distribution_templates_do_not_embed_local_absolute_paths() -> None:
    """Committed local-distribution templates must stay portable across machines."""
    template_paths = [
        CODEX_CONFIG,
        CODEX_PLUGIN / ".mcp.json",
        CODEX_PLUGIN / ".codex-plugin" / "mcp_server_config.toml",
        CODEX_PLUGIN / "README.md",
        CODEX_PLUGIN / ".codex-plugin" / "plugin.json",
        CLAUDE_DESKTOP / "manifest.json",
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


def test_build_mcpb_creates_small_package_with_manifest_and_wrapper(tmp_path: Path) -> None:
    """MCPB build should package only metadata plus the shared wrapper shim."""
    if platform.system() != "Windows":
        return

    output_path = tmp_path / "literature-assistant-toolbox.mcpb"
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CLAUDE_DESKTOP / "build_mcpb.ps1"),
            "-OutputPath",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert output_path.is_file()
    assert output_path.stat().st_size < 200_000
    with zipfile.ZipFile(output_path) as archive:
        names = set(archive.namelist())
    assert "manifest.json" in names
    assert "server/lit-assistant-mcp.ps1" in names
