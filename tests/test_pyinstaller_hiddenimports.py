from __future__ import annotations

import ast
from pathlib import Path
from types import FunctionType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "literature_assistant" / "core" / "python_adapter_server.py"
SPEC_PATH = REPO_ROOT / "packaging" / "pyinstaller" / "literature-assistant.spec"


def _router_imports_from_server() -> set[str]:
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module
        if module and module.startswith("routers."):
            modules.add(module)
    return modules


def _hiddenimports_from_spec() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "hiddenimports" for target in node.targets):
            continue
        if not isinstance(node.value, ast.List):
            raise AssertionError("PyInstaller hiddenimports must remain a static string list.")
        imports: set[str] = set()
        for item in node.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise AssertionError("PyInstaller hiddenimports must contain only string literals.")
            imports.add(item.value)
        return imports
    raise AssertionError("PyInstaller spec does not define a hiddenimports list.")


def _load_spec_function(name: str) -> FunctionType:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    selected_nodes: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names):
            selected_nodes.append(node)
            continue
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "pathlib"
            and any(alias.name == "Path" for alias in node.names)
        ):
            selected_nodes.append(node)
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.startswith("_SOURCE_DATA_")
            for target in node.targets
        ):
            selected_nodes.append(node)
            continue
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_should_exclude_literature_assistant_data_path",
            "_collect_literature_assistant_datas",
        }:
            selected_nodes.append(node)

    namespace: dict[str, Any] = {}
    compiled = compile(
        ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[])),
        str(SPEC_PATH),
        "exec",
    )
    exec(compiled, namespace)  # noqa: S102 - controlled extraction from local spec file.
    loaded = namespace.get(name)
    if not isinstance(loaded, FunctionType):
        raise AssertionError(f"PyInstaller spec does not define {name}().")
    return loaded


def test_pyinstaller_hiddenimports_cover_adapter_router_imports() -> None:
    """Frozen builds must include every router imported by the adapter server."""

    missing = sorted(_router_imports_from_server() - _hiddenimports_from_spec())

    assert missing == []


def test_pyinstaller_literature_datas_exclude_runtime_state_and_secrets(tmp_path: Path) -> None:
    """PyInstaller datas must not bundle developer-local runtime state."""

    root = tmp_path / "literature_assistant"
    keep = root / "core" / "skills" / "builtin" / "skill.py"
    keep.parent.mkdir(parents=True)
    keep.write_text("print('ok')\n", encoding="utf-8")

    forbidden_files = [
        root / ".env",
        root / ".env.local",
        root / ".secrets.baseline",
        root / "core" / "credentials.json",
        root / "core" / "runtime_credentials.json",
        root / "core" / "runtime_mcp_servers.json",
        root / "core" / "key.txt",
        root / "core" / "id_rsa",
        root / "core" / "id_ed25519",
        root / "core" / "private.pem",
        root / "core" / "private.key",
        root / "core" / "module.pyc",
        root / "core" / "module.pyo",
        root / "core" / "skills" / "imported" / "user" / ".install_meta.json",
        root / "core" / "skills" / "imported" / "user" / ".audit" / "skill_audit.jsonl",
        root / "core" / "skills" / "imported" / "user" / ".approval" / "approvals.json",
        root
        / "core"
        / "skills"
        / "imported"
        / "user"
        / ".rollback_snapshots"
        / "backup.json",
        root / "core" / "logs" / "adapter.log",
        root / "core" / "chunk_store" / "chunk.bin",
        root / "core" / "mcp_servers" / "audit.jsonl",
    ]
    for file_path in forbidden_files:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("blocked\n", encoding="utf-8")
    (root / ".env.example").write_text("allowed=true\n", encoding="utf-8")

    collect_datas = _load_spec_function("_collect_literature_assistant_datas")
    collected = collect_datas(root, "literature_assistant")
    collected_srcs = {Path(src).relative_to(root).as_posix() for src, _dest in collected}

    assert "core/skills/builtin/skill.py" in collected_srcs
    assert ".env.example" in collected_srcs
    for file_path in forbidden_files:
        assert file_path.relative_to(root).as_posix() not in collected_srcs

    for src, dest in collected:
        rel_src = Path(src).relative_to(root)
        combined = Path(dest) / rel_src.name
        assert not any(part in {".audit", ".approval", ".rollback_snapshots"} for part in combined.parts)
        assert not any(part in {"logs", "chunk_store", "mcp_servers"} for part in combined.parts)


def test_default_release_excludes_local_inference_adapters(tmp_path: Path, monkeypatch) -> None:
    """Default release MUST NOT ship local_*_adapter.py to the onedir.

    Per "API-first 双线" packaging policy (CHANGELOG 0.1.8.3 / OPTIONAL_ADDONS.md):
      - Default Inno Setup installer excludes local GPU/CPU inference adapters
        so users get a 466MB bundle that depends only on remote APIs.
      - LITASSIST_BUNDLE_RAG=1 includes them for offline / firewalled deployments
        (~3.3GB onedir).

    Routes that import these adapters (rerank_config_router.get_local_*_status,
    model_config_router.get_local_embedding_status) wrap the import in
    try/except ImportError and return available=False, so excluding the .py
    files at the data layer is safe.
    """
    monkeypatch.delenv("LITASSIST_BUNDLE_RAG", raising=False)
    root = tmp_path / "literature_assistant"
    (root / "core").mkdir(parents=True)
    (root / "core" / "local_rerank_adapter.py").write_text("# adapter\n", encoding="utf-8")
    (root / "core" / "local_embedding_adapter.py").write_text("# adapter\n", encoding="utf-8")
    (root / "core" / "python_adapter_server.py").write_text("# server\n", encoding="utf-8")

    collect_datas = _load_spec_function("_collect_literature_assistant_datas")
    collected = collect_datas(root, "literature_assistant")
    collected_srcs = {Path(src).relative_to(root).as_posix() for src, _dest in collected}

    assert "core/python_adapter_server.py" in collected_srcs, "regular sources must still ship"
    assert "core/local_rerank_adapter.py" not in collected_srcs, (
        "local rerank adapter must be excluded from default release"
    )
    assert "core/local_embedding_adapter.py" not in collected_srcs, (
        "local embedding adapter must be excluded from default release"
    )


def test_bundle_rag_release_includes_local_inference_adapters(
    tmp_path: Path, monkeypatch
) -> None:
    """LITASSIST_BUNDLE_RAG=1 SHIPS local_*_adapter.py to the onedir.

    Counterpart to default-exclusion test: confirms the env-var opt-in
    actually pulls the adapters back in.
    """
    monkeypatch.setenv("LITASSIST_BUNDLE_RAG", "1")
    root = tmp_path / "literature_assistant"
    (root / "core").mkdir(parents=True)
    (root / "core" / "local_rerank_adapter.py").write_text("# adapter\n", encoding="utf-8")
    (root / "core" / "local_embedding_adapter.py").write_text("# adapter\n", encoding="utf-8")

    collect_datas = _load_spec_function("_collect_literature_assistant_datas")
    collected = collect_datas(root, "literature_assistant")
    collected_srcs = {Path(src).relative_to(root).as_posix() for src, _dest in collected}

    assert "core/local_rerank_adapter.py" in collected_srcs
    assert "core/local_embedding_adapter.py" in collected_srcs
