# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Literature Assistant Windows desktop bundle.

Layer 1 of the two-layer packaging architecture (PyInstaller onedir).
Layer 2 (Inno Setup) wraps the onedir output into a single .exe installer.

Reference: docs/plans/runbooks/windows-exe-release-standard.md
"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# Resolve repo root from spec file location: packaging/pyinstaller/<spec>.
REPO_ROOT = Path(SPECPATH).resolve().parent.parent  # type: ignore[name-defined]

block_cipher = None


def _collect_literature_assistant_datas(root: Path, dest_prefix: str) -> list[tuple[str, str]]:
    """Build (src, dest) tuples for literature_assistant/ contents, excluding
    .env / .env.<x> (keeping .env.example) and Python bytecode cache.

    Aligns with the policy enforced by scripts/release_forbidden_path_scan.py
    rule '.env.* (not .env.example)'. PyInstaller `datas=[(src, dest)]` tuple
    form does not support excludes; expanding here gives explicit control.

    Reference:
      - PyInstaller spec datas: https://pyinstaller.org/en/latest/spec-files.html
      - alpha-prep attempt1 was blocked by Step 5 release gate for shipping
        literature_assistant/core/.env (see workspace_artifacts/releases/
        _rejected/forbidden-path-forbidden_path_onedir-20260511T172332Z.json).
      - alpha-prep attempt4 was blocked by Step 8 (Inno Setup) MAX_PATH
        because bundled .pyc files under
        literature_assistant/core/skills/importers/ui-ux-pro-max/.claude/
        skills/.../__pycache__/*.cpython-313.pyc pushed the absolute path
        past 260 chars. The .pyc files are redundant — PyInstaller bundles
        compile their own .pyc cache from .py sources during build, so
        excluding source-tree __pycache__ is a correct fix, not a workaround.
        References:
        - https://docs.python.org/3/tutorial/modules.html#compiled-python-files
        - https://learn.microsoft.com/en-us/windows/win32/fileio/
          maximum-file-path-limitation
    """
    out: list[tuple[str, str]] = []
    for src_dir, dirs, files in os.walk(root):
        # Prune build-only / metadata directories from descent (os.walk dirs[:] contract).
        # - __pycache__: redundant with PyInstaller's own .pyc cache (see Patch 5 above).
        # - .claude: skill-authoring template metadata vendored alongside third-party
        #   skill imports (e.g. literature_assistant/core/skills/importers/
        #   ui-ux-pro-max/.claude/skills/...). Wrappers in
        #   literature_assistant/core/skills/importers/*_wrapper.py invoke each skill
        #   via its own cli/src entrypoint; the nested .claude tree is documentation
        #   for *authoring* additional Claude skills, not a runtime dependency.
        #   Bundling it added 7MB / 205 files including .ttf fonts under
        #   .claude/skills/ui-styling/canvas-fonts/ whose absolute paths breached
        #   the Windows MAX_PATH (260) limit during Inno Setup compress at Step 8
        #   (alpha-prep attempt5, 2026-05-12). Pruning brings longest in-tree
        #   path back to ~124 chars (all source .py).
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".claude")]
        for fname in files:
            if fname == ".env":
                continue
            if fname.startswith(".env.") and fname != ".env.example":
                continue
            if fname.endswith(".pyc") or fname.endswith(".pyo"):
                continue
            full_src = Path(src_dir) / fname
            rel_parent = full_src.parent.relative_to(root)
            dest = dest_prefix if str(rel_parent) == "." else f"{dest_prefix}/{rel_parent.as_posix()}"
            out.append((str(full_src), dest))
    return out


datas = [
    (str(REPO_ROOT / "frontend" / "dist"), "frontend/dist"),
] + _collect_literature_assistant_datas(REPO_ROOT / "literature_assistant", "literature_assistant")


# FastAPI router modules accessed by string-based imports during route registration.
# Listed explicitly so PyInstaller bundles them even though static analysis
# might miss them in some import patterns.
hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "fastapi.middleware.cors",
    "fastapi.responses",
    "fastapi.staticfiles",
    "fastapi.exceptions",
    # "pywebview" removed: the package name on PyPI is `pywebview` but the
    # importable name is `webview` (see pywebview/__init__.py). Listing the
    # wrong name produced a harmless "Hidden import not found" WARNING in
    # attempt 6 log. `webview` below is the correct entry.
    "webview",
    "literature_assistant.bootstrap",
    "literature_assistant.core.python_adapter_server",
    "routers.pipeline_router",
    "routers.skills_router",
    "routers.resources_router",
    "routers.memory_router",
    # "routers.semantic_causal_router" removed: module was never committed to
    # alpha branch (lives in stash integration-working-tree-hold-20260512).
    # python_adapter_server.py:435 already has a matching NOTE comment.
    # Restore together with the router file in a future feature commit.
    "routers.runtime_router",
    "routers.recovery_router",
    "routers.inspiration_router",
    "routers.agent_router",
    "routers.chat_router",
    "routers.intelligent_chat_router",
    "routers.llm_cost_router",
    "routers.sampling_router",
    "routers.volume_router",
    "routers.wiki_router",
    "routers.export_router",
    "routers.annotation_router",
    "routers.discussion_router",
    "recovery_autopilot_router",
]

# MCP runtime: mcp 1.27.0 uses lazy/dynamic imports that PyInstaller static
# analysis misses. collect_all gathers submodules, data files (JSON schemas,
# py.typed markers), and any native extensions.
# fastmcp is NOT collected: it's a server-side SDK used only by external MCP
# servers (which run in their own Python environment, not inside this bundle).
# Ref: https://pyinstaller.org/en/latest/hooks.html#collect-all
_mcp_datas, _mcp_binaries, _mcp_hiddenimports = collect_all("mcp")


a = Analysis(
    [str(REPO_ROOT / "start_desktop.py")],
    pathex=[
        str(REPO_ROOT),
        str(REPO_ROOT / "literature_assistant" / "core"),
    ],
    binaries=[] + _mcp_binaries,
    datas=datas + _mcp_datas,
    hiddenimports=hiddenimports + _mcp_hiddenimports,
    hookspath=[],
    runtime_hooks=[str(REPO_ROOT / "packaging" / "pyinstaller" / "runtime_hook.py")],
    excludes=[
        "tests",
        "workspace_tests",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiteratureAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(REPO_ROOT / "packaging" / "assets" / "icon.ico") if (REPO_ROOT / "packaging" / "assets" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LiteratureAssistant",
)
