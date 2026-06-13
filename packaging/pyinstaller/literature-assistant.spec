# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Literature Assistant Windows desktop bundle.

Layer 1 of the two-layer packaging architecture (PyInstaller onedir).
Layer 2 (Inno Setup) wraps the onedir output into a single .exe installer.

Reference: docs/plans/runbooks/windows-exe-release-standard.md
"""
import os
import tempfile
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# Resolve repo root from spec file location: packaging/pyinstaller/<spec>.
REPO_ROOT = Path(SPECPATH).resolve().parent.parent  # type: ignore[name-defined]

# Read version from pyproject.toml (single source of truth).
def _read_version() -> str:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return "0.0.0"
    with open(pyproject_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("version"):
                # Extract version = "x.y.z"
                parts = line.split("=", 1)
                if len(parts) == 2:
                    version_str = parts[1].strip().strip('"').strip("'")
                    return version_str
    return "0.0.0"

APP_VERSION = _read_version()


def _make_version_info_path(version_str: str) -> str:
    """Generate a Windows VS_VERSION_INFO resource file; return its path.

    PyInstaller's EXE(version=...) requires a path to a text file holding a
    VSVersionInfo(...) expression (it is read via load_version_info_from_text_file),
    NOT a bare version string. Passing the raw "x.y.z" string makes PyInstaller
    try to open a file literally named after the version and fail with
    FileNotFoundError. The dotted version is normalized to a 4-int tuple because
    Win32 filevers/prodvers require exactly four 16-bit fields.
    """
    parts = [int(p) for p in version_str.split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    vers = tuple(parts[:4])
    content = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={vers}, prodvers={vers},\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        "        StringStruct('CompanyName', 'Scholar AI'),\n"
        "        StringStruct('FileDescription', 'Scholar AI'),\n"
        f"        StringStruct('FileVersion', '{version_str}'),\n"
        "        StringStruct('InternalName', 'Scholar-AI'),\n"
        "        StringStruct('OriginalFilename', 'Scholar-AI.exe'),\n"
        "        StringStruct('ProductName', 'Scholar AI'),\n"
        f"        StringStruct('ProductVersion', '{version_str}')\n"
        "      ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )
    fd, tmp_path = tempfile.mkstemp(prefix="scholarai_versioninfo_", suffix=".txt")
    os.close(fd)
    Path(tmp_path).write_text(content, encoding="utf-8")
    return tmp_path


_VERSION_INFO_PATH = _make_version_info_path(APP_VERSION)

block_cipher = None

_SOURCE_DATA_DIR_EXCLUDES = frozenset({
    "__pycache__",
    ".claude",
    ".audit",
    ".approval",
    ".rollback_snapshots",
    "chunk_store",
    "logs",
    "mcp_servers",
})

_SOURCE_DATA_FILE_EXCLUDES = frozenset({
    ".env",
    ".install_meta.json",
    ".secrets.baseline",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "key.txt",
    "runtime_credentials.json",
    "runtime_mcp_servers.json",
})

_SOURCE_DATA_SUFFIX_EXCLUDES = frozenset({
    ".key",
    ".pem",
    ".pyc",
    ".pyo",
})

# Source files that ship ONLY in source builds + the LITASSIST_BUNDLE_RAG=1 full
# release. Default release packs API-first only; local GPU/CPU inference adapters
# are excluded at the data-copy layer so the .py files don't reach the bundle.
# Routes that import these adapters lazily (rerank_config_router.get_local_*_status,
# model_config_router.get_local_embedding_status) already wrap the import in
# try/except ImportError → return available=False, so the frontend status chip
# degrades to "本地回退: 不可用" with no runtime error.
_SOURCE_DATA_LOCAL_FALLBACK_FILES = frozenset({
    "local_rerank_adapter.py",
    "local_embedding_adapter.py",
    "local_rerank_server.py",
    "local_embedding_server.py",
})
_SOURCE_DATA_INCLUDE_LOCAL_FALLBACK = os.environ.get("LITASSIST_BUNDLE_RAG", "").strip() == "1"


def _should_exclude_literature_assistant_data_path(path: Path, is_dir: bool) -> bool:
    """Return True for source-tree files that must never enter release datas.

    The PyInstaller `datas` list is assembled before the release forbidden-path
    scan runs. Mirroring the release gate here prevents local runtime logs,
    approvals, credentials, and private keys from being copied into the frozen
    app when a developer builds from a used workspace.
    """
    if not path.name:
        raise ValueError("path must include a file or directory name")
    if is_dir:
        return path.name in _SOURCE_DATA_DIR_EXCLUDES
    if path.name in _SOURCE_DATA_FILE_EXCLUDES:
        return True
    if path.name.startswith(".env.") and path.name != ".env.example":
        return True
    if (
        not _SOURCE_DATA_INCLUDE_LOCAL_FALLBACK
        and path.name in _SOURCE_DATA_LOCAL_FALLBACK_FILES
    ):
        return True
    return path.suffix in _SOURCE_DATA_SUFFIX_EXCLUDES


def _collect_literature_assistant_datas(root: Path, dest_prefix: str) -> list[tuple[str, str]]:
    """Build (src, dest) tuples for literature_assistant/ contents, excluding
    .env / .env.<x> (keeping .env.example) and Python bytecode cache.

    Aligns with the policy enforced by scripts/release_forbidden_path_scan.py.
    PyInstaller `datas=[(src, dest)]` tuple form does not support excludes;
    expanding here gives explicit control.

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
        dirs[:] = [
            d for d in dirs
            if not _should_exclude_literature_assistant_data_path(Path(src_dir) / d, is_dir=True)
        ]
        for fname in files:
            full_src = Path(src_dir) / fname
            if _should_exclude_literature_assistant_data_path(full_src, is_dir=False):
                continue
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
    "routers.rerank_config_router",
    "routers.model_config_router",
    "routers.llm_cost_router",
    "routers.sampling_router",
    "routers.volume_router",
    "routers.wiki_router",
    "routers.export_router",
    "routers.annotation_router",
    "routers.discussion_router",
    "routers.credentials_router",
    "routers.settings_router",
    "routers.csl_styles_router",
    "routers.discussion_advanced_router",
    "routers.mcp_router",
    "routers.mcp_installer_router",
    "routers.knowledge_router",
    "routers.graph_router",
    "routers.evolution_router",
    "routers.feature_flags_router",
    "routers.pdf_backend_router",
    "routers.writing_router",
    "routers.evidence_router",
    "routers.diagnostics_router",
    "recovery_autopilot_router",
]

# MCP runtime: mcp 1.27.0 uses lazy/dynamic imports that PyInstaller static
# analysis misses. collect_all gathers submodules, data files (JSON schemas,
# py.typed markers), and any native extensions.
# fastmcp is NOT collected: it's a server-side SDK used only by external MCP
# servers (which run in their own Python environment, not inside this bundle).
# Ref: https://pyinstaller.org/en/latest/hooks.html#collect-all
_mcp_datas, _mcp_binaries, _mcp_hiddenimports = collect_all("mcp")

_OPTIONAL_RAG_EXCLUDES = []
_OPTIONAL_RAG_HIDDENIMPORTS = []
if os.environ.get("LITASSIST_BUNDLE_RAG", "").strip() != "1":
    # Default release (API-first): exclude heavy local-inference deps to keep
    # onedir at ~360MB. Users who need offline rerank/embedding install
    # torch + sentence-transformers into their Python env themselves and the
    # adapters fall back gracefully (is_available() returns False, callers
    # route to API or hybrid_score).
    _OPTIONAL_RAG_EXCLUDES = [
        "chromadb",
        "sentence_transformers",
        "torch",
        "tensorflow",
        "umap",
        "sklearn",
        "numba",
        "llvmlite",
    ]
else:
    # LITASSIST_BUNDLE_RAG=1: full release. Ship local_rerank/embedding
    # adapters as hidden imports so PyInstaller pulls torch +
    # sentence-transformers into the onedir. Roughly 3GB extra (cu126
    # CUDA runtime DLLs + cuDNN dominate). Use this only when targeting
    # offline / firewalled deployments.
    _OPTIONAL_RAG_HIDDENIMPORTS = [
        "local_rerank_adapter",
        "local_embedding_adapter",
    ]


a = Analysis(
    [str(REPO_ROOT / "start_desktop.py")],
    pathex=[
        str(REPO_ROOT),
        str(REPO_ROOT / "literature_assistant" / "core"),
    ],
    binaries=[] + _mcp_binaries,
    datas=datas + _mcp_datas,
    hiddenimports=hiddenimports + _mcp_hiddenimports + _OPTIONAL_RAG_HIDDENIMPORTS,
    hookspath=[],
    runtime_hooks=[str(REPO_ROOT / "packaging" / "pyinstaller" / "runtime_hook.py")],
    excludes=[
        "tests",
        "workspace_tests",
        "pytest",
    ] + _OPTIONAL_RAG_EXCLUDES,
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
    name="Scholar-AI",
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
    version=_VERSION_INFO_PATH,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Scholar-AI",
)
