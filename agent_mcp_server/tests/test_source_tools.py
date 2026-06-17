"""Tests for basic source tools."""

from pathlib import Path

import pytest

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.policy import PathPolicy
from lit_assistant_mcp.tools.source import SourceTools


def _openai_key() -> str:
    return "sk-" + "abc123def456ghi789jkl012mno345"


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    """Create a small repository fixture for source tools."""
    repo = tmp_path
    (repo / "AI_WORKSPACE_GUIDE.md").write_text("# guide", encoding="utf-8")
    (repo / ".env").write_text("OPENAI_API_KEY=" + _openai_key(), encoding="utf-8")
    source_dir = repo / "literature_assistant/core/routers"
    source_dir.mkdir(parents=True)
    (source_dir / "chat_router.py").write_text(
        "class ChatRouter:\n"
        "    pass\n\n"
        "async def stream_chat() -> None:\n"
        "    return None\n\n"
        "def ask() -> str:\n"
        f"    return '{_openai_key()}'\n",
        encoding="utf-8",
    )
    (source_dir / "notes.txt").write_text("Needle line\nother line\n", encoding="utf-8")
    (repo / "workspace_artifacts/runtime_state").mkdir(parents=True)
    (repo / "workspace_artifacts/runtime_state/secrets.json").write_text("{}", encoding="utf-8")
    return repo


@pytest.fixture
def tools(source_repo: Path) -> SourceTools:
    """Create source tools with audit enabled."""
    policy = PathPolicy(
        repo_root=source_repo,
        allowed_roots=["literature_assistant/", "AI_WORKSPACE_GUIDE.md"],
        denied_patterns=["**/.env*", "workspace_artifacts/runtime_state/**"],
    )
    return SourceTools(
        repo_root=source_repo,
        policy=policy,
        audit=AuditLog(source_repo / "workspace_artifacts/agent_mcp_workflows/.audit"),
    )


def test_read_file_redacts_secrets(tools: SourceTools) -> None:
    """Allowed file reads return redacted content."""
    result = tools.read_file("literature_assistant/core/routers/chat_router.py")

    assert result["is_error"] is False
    content = result["data"]["content"]
    assert "sk-abc123" not in content
    assert "[REDACTED:" in content


def test_read_file_blocks_env(tools: SourceTools) -> None:
    """Denied paths are blocked."""
    result = tools.read_file(".env")

    assert result["is_error"] is True
    assert result["error_code"] == "path_blocked"


def test_search_returns_redacted_matches(tools: SourceTools) -> None:
    """Search returns bounded, redacted matches."""
    result = tools.search("Needle", root="literature_assistant", max_results=5)

    assert result["is_error"] is False
    assert result["data"]["matches"][0]["path"].endswith("notes.txt")
    assert result["data"]["matches"][0]["line"] == 1


def test_read_symbols_uses_python_ast(tools: SourceTools) -> None:
    """Symbol extraction returns top-level Python symbols."""
    result = tools.read_symbols("literature_assistant/core/routers/chat_router.py")

    assert result["is_error"] is False
    symbols = {(item["name"], item["kind"]) for item in result["data"]["symbols"]}
    assert ("ChatRouter", "class") in symbols
    assert ("stream_chat", "async_function") in symbols
    assert ("ask", "function") in symbols


def test_list_tree_only_includes_allowed_files(tools: SourceTools) -> None:
    """Tree listing exposes allowed files and skips denied runtime state."""
    result = tools.list_tree("literature_assistant", max_depth=4, max_entries=50)

    assert result["is_error"] is False
    paths = {entry["path"] for entry in result["data"]["entries"]}
    assert "literature_assistant/core/routers/chat_router.py" in paths
    assert all("workspace_artifacts/runtime_state" not in path for path in paths)


def test_audit_log_is_written(source_repo: Path, tools: SourceTools) -> None:
    """Source tool calls write a redacted audit event."""
    tools.read_file("literature_assistant/core/routers/chat_router.py")

    audit_files = list((source_repo / "workspace_artifacts/agent_mcp_workflows/.audit").glob("*.jsonl"))
    assert audit_files
    audit_text = audit_files[0].read_text(encoding="utf-8")
    assert "source.read_file" in audit_text
    assert "sk-abc123" not in audit_text


def test_inspect_routes_finds_fastapi_decorators(source_repo: Path, tools: SourceTools) -> None:
    """Advanced source tool statically parses FastAPI route decorators."""
    route_file = source_repo / "literature_assistant/core/routers/routes_demo.py"
    route_file.write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.get('/items/{item_id}', name='read_item')\n"
        "def read_item(item_id: str):\n"
        "    return {'id': item_id}\n",
        encoding="utf-8",
    )

    result = tools.inspect_routes(root="literature_assistant/core/routers")

    assert result["is_error"] is False
    route = next(item for item in result["data"]["routes"] if item["function"] == "read_item")
    assert route["method"] == "GET"
    assert route["path"] == "/items/{item_id}"
    assert route["name"] == "read_item"


def test_find_references_returns_bounded_text_matches(tools: SourceTools) -> None:
    """Reference finder returns literal matches from allowed files."""
    result = tools.find_references(symbol="ChatRouter", root="literature_assistant", max_results=2)

    assert result["is_error"] is False
    assert result["data"]["references"]
    assert "ChatRouter" in result["data"]["references"][0]["text"]


def test_explain_entrypoints_builds_bounded_import_graph(source_repo: Path, tools: SourceTools) -> None:
    """Entrypoint explanation follows local imports without executing modules."""
    package = source_repo / "literature_assistant/core/entry_demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "main.py").write_text("from . import helper\nVALUE = helper.VALUE\n", encoding="utf-8")

    result = tools.explain_entrypoints(path="literature_assistant/core/entry_demo/main.py", max_depth=2)

    assert result["is_error"] is False
    paths = {item["path"] for item in result["data"]["files"]}
    assert "literature_assistant/core/entry_demo/main.py" in paths
    assert "literature_assistant/core/entry_demo/helper.py" in paths
