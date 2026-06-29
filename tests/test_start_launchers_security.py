from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import tomllib

import pytest

import start_desktop


def _prepare_frontend_root(tmp_path: Path) -> Path:
    """Create the minimum frontend tree needed by launcher build helpers."""
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir(parents=True)
    (frontend_root / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
    return tmp_path


def _install_subprocess_spy(monkeypatch: Any, module: Any) -> list[dict[str, Any]]:
    """Capture subprocess.run calls made by a launcher module."""
    calls: list[dict[str, Any]] = []

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _run)
    return calls


def test_pywebview_launcher_builds_frontend_without_shell(tmp_path: Path, monkeypatch: Any) -> None:
    """The pywebview launcher should invoke npm by argv, not through shell parsing."""
    root = _prepare_frontend_root(tmp_path)
    monkeypatch.setattr(start_desktop, "ROOT", root)
    monkeypatch.setattr(start_desktop, "FRONTEND_ROOT", root / "frontend")
    monkeypatch.setattr(
        start_desktop.shutil,
        "which",
        lambda name: "C:/node/npm.cmd" if name in {"npm.cmd", "npm"} else None,
    )
    calls = _install_subprocess_spy(monkeypatch, start_desktop)

    assert start_desktop._build_frontend() is True

    assert len(calls) == 1
    call = calls[0]
    assert call["args"] == ["C:/node/npm.cmd", "run", "build"]
    assert call["kwargs"]["cwd"] == str(tmp_path / "frontend")
    assert call["kwargs"].get("shell") is not True
    assert call["kwargs"]["text"] is True
    assert call["kwargs"]["encoding"] == "utf-8"
    assert call["kwargs"]["errors"] == "replace"
    assert call["kwargs"]["check"] is False


def test_native_folder_dialog_uses_pywebview_folder_dialog(monkeypatch: Any) -> None:
    """Native folder picker should return a selected directory path without browser file APIs."""
    calls: list[str] = []

    class FakeWindow:
        def create_file_dialog(self, dialog_kind: str) -> list[str]:
            calls.append(dialog_kind)
            return ["C:/Users/example/Documents/Papers"]

    fake_webview = SimpleNamespace(
        FOLDER_DIALOG="folder-dialog",
        windows=[FakeWindow()],
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    selected = start_desktop.NativeApi().folder_dialog()

    assert selected == "C:/Users/example/Documents/Papers"
    assert calls == ["folder-dialog"]


def test_frontend_build_current_requires_dist_newer_than_inputs(tmp_path: Path, monkeypatch: Any) -> None:
    """The desktop launcher should rebuild when source files are newer than dist."""
    frontend_root = tmp_path / "frontend"
    src_dir = frontend_root / "src"
    dist_dir = frontend_root / "dist"
    src_dir.mkdir(parents=True)
    dist_dir.mkdir(parents=True)
    source_file = src_dir / "App.tsx"
    dist_file = dist_dir / "index.html"
    source_file.write_text("new ui", encoding="utf-8")
    dist_file.write_text("old ui", encoding="utf-8")

    old_mtime = 1_700_000_000
    new_mtime = 1_700_000_100
    import os

    os.utime(dist_file, (old_mtime, old_mtime))
    os.utime(source_file, (new_mtime, new_mtime))
    os.utime(src_dir, (new_mtime, new_mtime))

    monkeypatch.setattr(start_desktop, "FRONTEND_ROOT", frontend_root)
    monkeypatch.setattr(start_desktop, "FRONTEND_DIST", dist_file)
    monkeypatch.setattr(start_desktop, "FRONTEND_BUILD_INPUTS", (src_dir,))

    assert start_desktop._frontend_build_is_current() is False

    fresh_mtime = 1_700_000_200
    os.utime(dist_file, (fresh_mtime, fresh_mtime))

    assert start_desktop._frontend_build_is_current() is True


def test_frontend_cache_version_tracks_built_index(tmp_path: Path, monkeypatch: Any) -> None:
    """The embedded browser cache marker should change when the built shell changes."""
    dist_file = tmp_path / "frontend" / "dist" / "index.html"
    dist_file.parent.mkdir(parents=True)
    dist_file.write_text("first", encoding="utf-8")
    monkeypatch.setattr(start_desktop, "FRONTEND_DIST", dist_file)

    first_version = start_desktop._frontend_cache_version()
    dist_file.write_text("second build", encoding="utf-8")
    second_version = start_desktop._frontend_cache_version()

    assert first_version != second_version


def test_desktop_initial_path_accepts_only_root_relative_spa_paths() -> None:
    """Desktop smoke helpers may deep-link only into the local SPA."""
    assert start_desktop._normalize_desktop_initial_path(None) == "/"
    assert start_desktop._normalize_desktop_initial_path(" /__desktop_acceptance/semantic-review?mode=graph ") == (
        "/__desktop_acceptance/semantic-review?mode=graph"
    )
    assert start_desktop._build_desktop_frontend_url(
        "http://127.0.0.1:8765",
        "/__desktop_acceptance/semantic-review",
    ) == "http://127.0.0.1:8765/__desktop_acceptance/semantic-review"

    for value in (
        "https://example.com/wiki",
        "//example.com/wiki",
        "wiki",
        "/../settings",
        "/wiki#fragment",
        "/wiki\\settings",
        "/wiki\nsettings",
    ):
        with pytest.raises(ValueError):
            start_desktop._normalize_desktop_initial_path(value)


def test_desktop_window_geometry_centers_inside_primary_work_area() -> None:
    """The source desktop window should start centered instead of drifting off-screen."""
    geometry = start_desktop._center_desktop_window(start_desktop.DesktopRect(0, 0, 1920, 1040))

    assert geometry.width == 1440
    assert geometry.height == 900
    assert geometry.x == 240
    assert geometry.y == 70


def test_desktop_window_geometry_shrinks_to_small_work_area() -> None:
    """Small screens should still receive a fully visible pywebview window."""
    geometry = start_desktop._center_desktop_window(start_desktop.DesktopRect(0, 0, 1280, 720))

    assert geometry.width == 1216
    assert geometry.height == 656
    assert geometry.x == 32
    assert geometry.y == 32


def test_desktop_rect_scale_converts_physical_pixels_to_webview_units() -> None:
    """DPI-aware Win32 pixels must be converted before passing geometry to pywebview."""
    logical = start_desktop._scale_desktop_rect(start_desktop.DesktopRect(0, 0, 2560, 1600), 1.5)

    assert logical == start_desktop.DesktopRect(0, 0, 1707, 1067)


def test_desktop_window_geometry_rejects_invalid_work_area() -> None:
    """Invalid monitor data should fail before pywebview sees impossible geometry."""
    with pytest.raises(ValueError):
        start_desktop._center_desktop_window(start_desktop.DesktopRect(0, 0, 0, 720))


def test_desktop_single_instance_mutex_name_is_repo_scoped(tmp_path: Path) -> None:
    """Concurrent desktop autostarts should only deduplicate the same checkout."""
    first_root = tmp_path / "checkout-a"
    second_root = tmp_path / "checkout-b"
    first_root.mkdir()
    second_root.mkdir()

    first_name = start_desktop._desktop_single_instance_mutex_name(first_root)
    second_name = start_desktop._desktop_single_instance_mutex_name(second_root)

    assert first_name.startswith("Local\\ScholarAI_Desktop_")
    assert first_name == start_desktop._desktop_single_instance_mutex_name(first_root)
    assert first_name != second_name
    assert len(first_name.rsplit("_", maxsplit=1)[-1]) == 16


def test_launcher_sources_do_not_use_shell_true() -> None:
    """Launcher source should not reintroduce shell=True for fixed build commands."""
    # start.py removed, only check start_desktop.py
    source_path = Path("start_desktop.py")
    if source_path.exists():
        source = source_path.read_text(encoding="utf-8")
        assert "shell=True" not in source
        assert 'input("按回车键退出' not in source


def test_windows_batch_launcher_starts_gui_python_and_exits() -> None:
    """Double-click startup should not keep a terminal attached to the desktop UI."""
    source = Path("start.bat").read_text(encoding="utf-8")

    assert ".venv-1\\Scripts\\pythonw.exe" in source
    assert 'start "" "%VENV_PYTHONW%" "%~dp0start_desktop.py"' in source
    assert "exit /b 0" in source
    assert '.venv-1\\Scripts\\python.exe" "%~dp0start_desktop.py' not in source


def test_frontend_index_has_no_external_font_links() -> None:
    """The packaged SPA shell should not depend on third-party font origins."""
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_frontend_csp_header_blocks_external_fonts() -> None:
    """The SPA shell CSP should constrain font loading to local/data sources."""
    import python_adapter_server

    csp = python_adapter_server._frontend_csp_header("testnonce")

    assert "font-src 'self' data:" in csp
    assert "fonts.googleapis.com" not in csp
    assert "'nonce-testnonce'" in csp


def test_embedded_desktop_port_bridge_prefers_current_descriptor(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Embedded pywebview startup must not overwrite its chosen free port with 8000."""
    import python_adapter_server

    api_port_path = tmp_path / "api-port.json"
    descriptor_path = tmp_path / "desktop-runtime.json"
    descriptor_path.write_text(
        json.dumps({"pid": os.getpid(), "port": 4861}),
        encoding="utf-8",
    )
    monkeypatch.setattr(python_adapter_server, "api_port_file_path", lambda: api_port_path)
    monkeypatch.setattr(python_adapter_server, "desktop_runtime_file_path", lambda: descriptor_path)
    monkeypatch.setattr(python_adapter_server.sys, "argv", ["start_desktop.py"])

    python_adapter_server._write_api_port_from_argv()

    payload = json.loads(api_port_path.read_text(encoding="utf-8"))
    assert payload["port"] == 4861
    assert payload["pid"] == os.getpid()


def test_api_port_bridge_ignores_stale_desktop_descriptor(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Bare uvicorn --port remains authoritative when a descriptor belongs to another PID."""
    import python_adapter_server

    api_port_path = tmp_path / "api-port.json"
    descriptor_path = tmp_path / "desktop-runtime.json"
    descriptor_path.write_text(
        json.dumps({"pid": os.getpid() + 1000, "port": 4861}),
        encoding="utf-8",
    )
    monkeypatch.setattr(python_adapter_server, "api_port_file_path", lambda: api_port_path)
    monkeypatch.setattr(python_adapter_server, "desktop_runtime_file_path", lambda: descriptor_path)
    monkeypatch.setattr(
        python_adapter_server.sys,
        "argv",
        ["uvicorn", "literature_assistant.core.python_adapter_server:app", "--port", "7654"],
    )

    python_adapter_server._write_api_port_from_argv()

    payload = json.loads(api_port_path.read_text(encoding="utf-8"))
    assert payload["port"] == 7654
    assert payload["pid"] == os.getpid()


def test_browser_cache_cleanup_is_versioned_and_profile_scoped(tmp_path: Path) -> None:
    """Launcher cache cleanup should not delete cache directories on every launch."""
    profile = tmp_path / "profile"
    cache = profile / "Default" / "Cache"
    code_cache = profile / "Default" / "Code Cache"
    cache.mkdir(parents=True)
    code_cache.mkdir(parents=True)
    (cache / "entry").write_text("cached", encoding="utf-8")
    (code_cache / "entry").write_text("compiled", encoding="utf-8")

    start_desktop._clear_stale_browser_cache(profile, "v1")

    assert not cache.exists()
    assert not code_cache.exists()
    assert (profile / start_desktop.BROWSER_CACHE_VERSION_FILE).read_text(encoding="utf-8") == "v1"

    cache.mkdir(parents=True)
    (cache / "entry").write_text("fresh", encoding="utf-8")
    start_desktop._clear_stale_browser_cache(profile, "v1")

    assert cache.exists()
    assert (cache / "entry").read_text(encoding="utf-8") == "fresh"


def test_sensitive_log_redaction_masks_common_secret_shapes() -> None:
    """Durable backend logs should not persist raw provider secrets."""
    import python_adapter_server

    api_key = "sk-" + "proj-" + "secret123456789"
    bearer_token = "abcdefgh" + "ijklmnop"
    redacted = python_adapter_server._redact_sensitive_log_text(
        f"OPENAI_API_KEY={api_key} Authorization: Bearer {bearer_token}"
    )

    assert api_key not in redacted
    assert bearer_token not in redacted
    assert redacted.count("***REDACTED***") >= 2


def test_pdf_viewer_fetches_raw_stream_endpoint_by_default() -> None:
    """PDF UI should avoid the memory-expensive base64 endpoint."""
    source = Path("frontend/src/components/PdfViewer/PdfViewer.tsx").read_text(encoding="utf-8")

    assert "arrayBuffer()" in source
    assert "/file_b64" not in source


def test_frontend_build_runs_openapi_sync_before_typecheck() -> None:
    """Backend contract changes should refresh generated frontend types before tsc."""
    import json

    package_json = json.loads(Path("frontend/package.json").read_text(encoding="utf-8"))
    scripts = package_json["scripts"]
    vite_config = Path("frontend/vite.config.ts").read_text(encoding="utf-8")

    assert scripts["prebuild"] == "npm run generate:openapi:if-needed"
    assert "generate:openapi:if-needed" in scripts
    assert "shell: process.platform === 'win32'" not in vite_config
    assert "litassist-openapi-sync" in vite_config


def test_python_dependency_specs_have_upper_bounds() -> None:
    """Primary pyproject dependencies should not float across major versions."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = list(pyproject["project"]["dependencies"])
    dependencies.extend(pyproject["project"]["optional-dependencies"]["rag"])
    dependencies.extend(pyproject["project"]["optional-dependencies"]["desktop"])

    assert dependencies
    for spec in dependencies:
        assert "<" in spec, spec


def test_coverage_gate_targets_active_runtime_surface() -> None:
    """Coverage config should exclude local historical scripts and enforce >80%."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    coverage = pyproject["tool"]["coverage"]

    assert coverage["report"]["fail_under"] == 80
    omit = "\n".join(coverage["run"]["omit"])
    assert "literature_assistant/core/__head_eval_runtime.py" in omit
    assert "literature_assistant/core/recovery_*.py" in omit
    assert "literature_assistant/core/modules/*" in omit


def test_runtime_env_ignores_repo_dotenv_by_default(monkeypatch: Any) -> None:
    """Repo-local .env must require an explicit compatibility opt-in."""
    import runtime_env

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)
    monkeypatch.delenv("LITASSIST_ENABLE_REPO_DOTENV", raising=False)
    monkeypatch.delenv("RUNTIME_ENV_ENABLE_DOTENV", raising=False)
    monkeypatch.delenv("LITASSIST_LOCAL_ENV_FILE", raising=False)

    repo_env_path = Path(runtime_env.__file__).resolve().with_name(".env")

    assert repo_env_path not in runtime_env._dotenv_paths()


def test_runtime_env_allows_temporary_cwd_dotenv(tmp_path: Path, monkeypatch: Any) -> None:
    """Temp dotenv fixtures outside source roots remain supported."""
    import runtime_env

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)
    monkeypatch.delenv("LITASSIST_ENABLE_REPO_DOTENV", raising=False)
    monkeypatch.delenv("RUNTIME_ENV_ENABLE_DOTENV", raising=False)
    monkeypatch.delenv("LITASSIST_LOCAL_ENV_FILE", raising=False)
    (tmp_path / ".env").write_text("TEMP_ONLY_KEY=value\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert (tmp_path / ".env").resolve() in runtime_env._dotenv_paths()


def test_runtime_env_blocks_repo_subdir_dotenv_by_default(tmp_path: Path, monkeypatch: Any) -> None:
    """Source-tree dotenv files should require explicit path selection."""
    import runtime_env

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)
    monkeypatch.delenv("LITASSIST_ENABLE_REPO_DOTENV", raising=False)
    monkeypatch.delenv("RUNTIME_ENV_ENABLE_DOTENV", raising=False)
    monkeypatch.delenv("LITASSIST_LOCAL_ENV_FILE", raising=False)
    fake_core = tmp_path / "repo" / "literature_assistant" / "core"
    fake_core.mkdir(parents=True)
    fake_runtime_env = fake_core / "runtime_env.py"
    fake_runtime_env.write_text("", encoding="utf-8")
    repo_subdir = tmp_path / "repo" / "frontend"
    repo_subdir.mkdir(parents=True)
    repo_dotenv = repo_subdir / ".env"
    repo_dotenv.write_text("SHOULD_NOT_LOAD=1\n", encoding="utf-8")
    monkeypatch.setattr(runtime_env, "__file__", str(fake_runtime_env))
    monkeypatch.chdir(repo_subdir)

    assert repo_dotenv.resolve() not in runtime_env._dotenv_paths()


def test_export_docx_temp_cleanup_removes_only_expected_temp_dirs(tmp_path: Path) -> None:
    """DOCX export cleanup should remove generated temp dirs and refuse others."""
    from routers.export_router import _cleanup_export_tmp_dir

    unsafe = tmp_path / "export_docx_not_in_temp_root"
    unsafe.mkdir()
    _cleanup_export_tmp_dir(unsafe)
    assert unsafe.exists()

    generated = Path(tempfile.mkdtemp(prefix="export_docx_"))
    (generated / "payload.docx").write_text("docx", encoding="utf-8")
    _cleanup_export_tmp_dir(generated)
    assert not generated.exists()


def test_conflict_detector_does_not_load_bge_without_opt_in(monkeypatch: Any) -> None:
    """Optional BGE model loading should not trigger network/model setup by default."""
    from layers.p2_conflict_detector import ConflictDetector

    monkeypatch.delenv("LITASSIST_ENABLE_LOCAL_BGE", raising=False)

    detector = ConflictDetector()

    assert detector.embedding_model is None
