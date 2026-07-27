from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path, PureWindowsPath

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
MCP_PYPROJECT_PATH = REPO_ROOT / "agent_mcp_server" / "pyproject.toml"
RAG_INTEGRATION_CONFIG_PATH = (
    REPO_ROOT / "literature_assistant" / "core" / "config" / "rag_integration_config.yaml"
)


def _create_minimal_distribution_source(tmp_path: Path) -> Path:
    """Create a small source tree that exercises the real package metadata."""

    source_root = tmp_path / "source"
    source_root.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "MANIFEST.in"):
        source = REPO_ROOT / name
        if source.is_file():
            shutil.copy2(source, source_root / name)

    package_root = source_root / "literature_assistant"
    for relative_path in (
        Path("__init__.py"),
        Path("version.py"),
        Path("core/__init__.py"),
        Path("core/skills/__init__.py"),
    ):
        source = REPO_ROOT / "literature_assistant" / relative_path
        destination = package_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    importers_root = package_root / "core/skills/importers"
    importers_root.mkdir(parents=True, exist_ok=True)
    (importers_root / "__init__.py").write_text("", encoding="utf-8")
    (importers_root / "ui_ux_pro_max_wrapper.py").write_text(
        '"""Public importer wrapper sentinel."""\n',
        encoding="utf-8",
    )
    private_source = (
        importers_root
        / "ui-ux-pro-max"
        / "cli"
        / "assets"
        / "scripts"
        / "private_impl.py"
    )
    private_source.parent.mkdir(parents=True)
    private_source.write_text("PRIVATE_IMPORTER_SENTINEL = True\n", encoding="utf-8")

    test_source = source_root / "tests/test_package_boundary_sentinel.py"
    test_source.parent.mkdir()
    test_source.write_text("TEST_SENTINEL = True\n", encoding="utf-8")
    return source_root


def _build_distribution_members(source_root: Path) -> tuple[set[str], set[str]]:
    """Build wheel and sdist archives and return their normalized members."""

    output_dir = source_root.parent / "dist"
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(output_dir),
        ),
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    wheel_path = next(output_dir.glob("*.whl"))
    sdist_path = next(output_dir.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel_path) as archive:
        wheel_members = {name.replace("\\", "/") for name in archive.namelist()}
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        sdist_members = {name.replace("\\", "/") for name in archive.getnames()}
    return wheel_members, sdist_members


def test_built_distributions_enforce_the_public_package_boundary(tmp_path: Path) -> None:
    """Published archives must omit private importer sources and test modules."""

    source_root = _create_minimal_distribution_source(tmp_path)
    wheel_members, sdist_members = _build_distribution_members(source_root)
    wrapper_suffix = (
        "literature_assistant/core/skills/importers/ui_ux_pro_max_wrapper.py"
    )

    assert any(member.endswith(wrapper_suffix) for member in wheel_members)
    assert any(member.endswith(wrapper_suffix) for member in sdist_members)

    forbidden_members = sorted(
        member
        for member in wheel_members | sdist_members
        if "/ui-ux-pro-max/" in f"/{member}/"
        or "/tests/" in f"/{member}/"
    )
    assert forbidden_members == []


def test_pyproject_declares_python_311_runtime_floor() -> None:
    """Project metadata must match runtime imports that use Python 3.11 APIs."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert data["project"]["requires-python"] == ">=3.11"
    assert data["tool"]["mypy"]["python_version"] == "3.11"
    assert data["tool"]["black"]["target-version"] == ["py311"]


def test_mypy_excludes_ignored_local_resource_importers() -> None:
    """Ignored importer resources must not contaminate tracked-source discovery."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    mypy_config = data["tool"]["mypy"]
    excluded_patterns = mypy_config["exclude"]
    ignored_importer = (
        "literature_assistant/core/skills/importers/"
        "ui-ux-pro-max/src/ui-ux-pro-max/data/_sync_all.py"
    )

    assert mypy_config.get("exclude_gitignore") is not True
    assert any(re.search(pattern, ignored_importer) for pattern in excluded_patterns)


def test_mypy_checks_internal_imports_and_resolves_local_mcp_source() -> None:
    """The configured gate must type-check Scholar AI while narrowing third-party gaps."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    mypy_config = data["tool"]["mypy"]
    approved_missing_import_modules = {
        "PyPDF2",
        "fitz",
        "graphrag",
        "graphrag.*",
        "networkx",
        "openai",
        "pandas",
        "pdfplumber",
        "psutil",
        "scipy",
        "scipy.*",
        "sentence_transformers",
        "torch",
        "transformers",
        "umap",
        "webview",
    }
    required_clean_checkout_optional_modules = {
        "openai",
        "webview",
    }

    assert mypy_config["ignore_missing_imports"] is False
    assert mypy_config["disallow_untyped_defs"] is True
    assert mypy_config["disallow_incomplete_defs"] is True
    assert mypy_config["disallow_untyped_calls"] is True
    assert mypy_config["explicit_package_bases"] is True
    assert "agent_mcp_server/src" in mypy_config["files"]
    assert "agent_mcp_server/src" in mypy_config["mypy_path"]

    ignored_modules: set[str] = set()
    for override in mypy_config.get("overrides", []):
        if override.get("ignore_missing_imports") is True:
            ignored_modules.update(override["module"])
    assert ignored_modules
    assert required_clean_checkout_optional_modules <= ignored_modules
    assert ignored_modules <= approved_missing_import_modules


def test_gateb_pool_export_uses_a_tracked_runtime_boundary() -> None:
    """Published evaluation code must not import an ignored workspace-only module."""

    exporter_path = (
        PYPROJECT_PATH.parent
        / "literature_assistant"
        / "core"
        / "gateb_phase_b_pool_export.py"
    )
    tree = ast.parse(exporter_path.read_text(encoding="utf-8"), filename=str(exporter_path))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "eval_retrieval_runtime" not in imported_modules
    assert "literature_assistant.core.__head_eval_runtime" in imported_modules


def test_type_check_dependencies_cover_the_local_and_ci_gate() -> None:
    """Local and CI environments must install mypy and required runtime stubs."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dev_dependencies = {
        re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].lower()
        for requirement in data["project"]["optional-dependencies"]["dev"]
    }
    ci_dependencies = {
        line.split("=", 1)[0].strip().lower()
        for line in (PYPROJECT_PATH.parent / "requirements-ci.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_type_packages = {
        "mypy",
        "types-pyyaml",
        "types-requests",
        "types-python-dateutil",
    }

    assert required_type_packages <= dev_dependencies
    assert required_type_packages <= ci_dependencies


def test_release_secret_scanner_dependency_is_declared_locally_and_in_ci() -> None:
    """Documented release scans must work after supported dev or CI setup."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dev_requirements = {
        requirement.name.lower(): requirement
        for raw_requirement in data["project"]["optional-dependencies"]["dev"]
        if (requirement := Requirement(raw_requirement))
    }
    ci_requirements = {
        requirement.name.lower(): requirement
        for line in (REPO_ROOT / "requirements-ci.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        if (requirement := Requirement(line.strip()))
    }

    assert "detect-secrets" in dev_requirements
    assert "detect-secrets" in ci_requirements
    ci_specifiers = tuple(ci_requirements["detect-secrets"].specifier)
    assert len(ci_specifiers) == 1
    assert ci_specifiers[0].operator == "=="
    assert Version(ci_specifiers[0].version) in dev_requirements["detect-secrets"].specifier


def test_root_and_standalone_mcp_dependency_ranges_match() -> None:
    """CI must reject an MCP wheel that resolves an unvalidated SDK range."""

    expected = Requirement("mcp>=1.13.0,<2.0.0")
    requirements: list[Requirement] = []
    for metadata_path in (PYPROJECT_PATH, MCP_PYPROJECT_PATH):
        data = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        matches = [
            Requirement(raw_requirement)
            for raw_requirement in data["project"]["dependencies"]
            if Requirement(raw_requirement).name.lower() == "mcp"
        ]
        assert len(matches) == 1, f"expected one MCP dependency in {metadata_path}"
        requirements.append(matches[0])

    assert requirements == [expected, expected]


def test_httpcore_transport_dependency_is_declared_locally_and_in_ci() -> None:
    """The pinned OCR transport must not rely on an undeclared transitive package."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    runtime_requirements = {
        requirement.name.lower(): requirement
        for raw_requirement in data["project"]["dependencies"]
        if (requirement := Requirement(raw_requirement))
    }
    ci_requirements = {
        requirement.name.lower(): requirement
        for line in (REPO_ROOT / "requirements-ci.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        if (requirement := Requirement(line.strip()))
    }

    assert "httpcore" in runtime_requirements
    assert "httpcore" in ci_requirements
    ci_specifiers = tuple(ci_requirements["httpcore"].specifier)
    assert len(ci_specifiers) == 1
    assert ci_specifiers[0].operator == "=="
    assert Version(ci_specifiers[0].version) in runtime_requirements["httpcore"].specifier


def test_no_isolation_build_backend_is_declared_locally_and_in_ci() -> None:
    """No-isolation builds require CI to preinstall a compatible backend."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    build_requirements = {
        requirement.name.lower(): requirement
        for raw_requirement in data["build-system"]["requires"]
        if (requirement := Requirement(raw_requirement))
    }
    dev_requirements = {
        requirement.name.lower(): requirement
        for raw_requirement in data["project"]["optional-dependencies"]["dev"]
        if (requirement := Requirement(raw_requirement))
    }
    ci_requirements = {
        requirement.name.lower(): requirement
        for line in (REPO_ROOT / "requirements-ci.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        if (requirement := Requirement(line.strip()))
    }

    assert "setuptools" in build_requirements
    assert "setuptools" in dev_requirements
    assert "setuptools" in ci_requirements

    ci_specifiers = tuple(ci_requirements["setuptools"].specifier)
    assert len(ci_specifiers) == 1
    assert ci_specifiers[0].operator == "=="
    assert not ci_specifiers[0].version.endswith(".*")

    ci_version = Version(ci_specifiers[0].version)
    assert ci_version in build_requirements["setuptools"].specifier
    assert ci_version in dev_requirements["setuptools"].specifier


def test_pyproject_reads_product_version_from_runtime_source() -> None:
    """Build metadata must resolve the product version from one module attribute."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert "version" not in data["project"]
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "literature_assistant.version.__version__"
    }


def test_rag_integration_runtime_paths_are_portable_and_local_only() -> None:
    """Published RAG defaults must stay clone-safe and outside tracked source."""

    data = yaml.safe_load(RAG_INTEGRATION_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    configured_paths = {
        "graphrag.index_path": data["graphrag"]["index_path"],
        "autorag.data_path": data["autorag"]["data_path"],
        "autorag.output_dir": data["autorag"]["output_dir"],
    }

    for field_name, raw_path in configured_paths.items():
        assert isinstance(raw_path, str) and raw_path.strip(), field_name
        assert not Path(raw_path).is_absolute(), field_name
        assert not PureWindowsPath(raw_path).is_absolute(), field_name
        normalized = raw_path.strip().replace("\\", "/").removeprefix("./")
        assert normalized.startswith("workspace_artifacts/"), field_name


def test_package_exposes_current_four_part_product_version() -> None:
    """The public package must expose the current four-part product version."""

    from literature_assistant import __version__

    assert __version__ == "0.1.9.3"


@pytest.mark.asyncio
async def test_public_api_surfaces_share_product_version() -> None:
    """OpenAPI and health metadata must use the canonical product version."""

    from literature_assistant import __version__
    from literature_assistant.core.python_adapter_server import app, health_check

    assert app.version == __version__
    assert app.openapi()["info"]["version"] == __version__
    assert (await health_check())["version"] == __version__


def test_parse_version_returns_four_numeric_parts() -> None:
    """A valid product version must parse into its four policy fields."""

    from literature_assistant.version import parse_version

    assert parse_version("12.3.45.6") == (12, 3, 45, 6)


@pytest.mark.parametrize(
    "invalid_version",
    (
        "",
        "0.1.9",
        "0.1.9.0.0",
        "v0.1.9.0",
        "00.1.9.0",
        "0.01.9.0",
        "0.1.-9.0",
        "0.1.9.0 ",
        "\u0660.1.9.0",
    ),
)
def test_parse_version_rejects_noncanonical_values(invalid_version: str) -> None:
    """Product versions must use exactly four canonical ASCII integer fields."""

    from literature_assistant.version import parse_version

    with pytest.raises(ValueError, match="four numeric fields"):
        parse_version(invalid_version)


@pytest.mark.parametrize(
    ("change", "expected"),
    (
        ("bugfix", "0.1.8.5"),
        ("feature", "0.1.9.0"),
        ("major", "1.0.0.0"),
    ),
)
def test_bump_version_follows_four_part_policy(change: str, expected: str) -> None:
    """Each authorized change kind must update only its policy-owned fields."""

    from literature_assistant.version import bump_version

    assert bump_version("0.1.8.4", change) == expected


def test_bump_version_rejects_undefined_track_increment() -> None:
    """The reserved track field must not acquire an implicit bump operation."""

    from literature_assistant.version import bump_version

    with pytest.raises(ValueError, match="bugfix, feature, major"):
        bump_version("0.1.8.4", "track")  # type: ignore[arg-type]


def test_acquisition_clients_share_product_version_user_agent() -> None:
    """Outbound acquisition clients must identify the current product version."""

    from literature_assistant.core.acquisition import downloader
    from literature_assistant.core.acquisition.sources import arxiv
    from literature_assistant.version import SCHOLAR_AI_USER_AGENT

    expected = "ScholarAI/0.1.9.3 compliant-open-access-client"
    assert SCHOLAR_AI_USER_AGENT == expected
    assert downloader.SCHOLAR_AI_USER_AGENT == expected
    assert arxiv.SCHOLAR_AI_USER_AGENT == expected


@pytest.mark.asyncio
async def test_default_downloader_client_sends_product_version_user_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The downloader's owned HTTP client must send the versioned User-Agent."""

    from literature_assistant.core.acquisition import downloader
    from literature_assistant.core.acquisition.sources.arxiv import ARXIV_POLICY

    captured: dict[str, object] = {}

    class _RequestIntercepted(RuntimeError):
        pass

    class _CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def stream(self, *_args: object, **_kwargs: object) -> object:
            raise _RequestIntercepted("request intercepted after client construction")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(downloader.httpx, "AsyncClient", _CapturingClient)

    with pytest.raises(_RequestIntercepted, match="client construction"):
        await downloader.download_validated_pdf(
            source_url="https://arxiv.org/pdf/2401.00001.pdf",
            policy=ARXIV_POLICY,
            destination=tmp_path / "paper.pdf",
            project_root=tmp_path,
            resolver=lambda _host: ("93.184.216.34",),
        )

    assert captured["headers"] == {
        "User-Agent": "ScholarAI/0.1.9.3 compliant-open-access-client"
    }


@pytest.mark.asyncio
async def test_default_arxiv_client_sends_product_version_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arXiv adapter's owned HTTP client must send the versioned User-Agent."""

    from literature_assistant.core.acquisition.models import SearchQuery
    from literature_assistant.core.acquisition.sources import arxiv

    captured: dict[str, object] = {}

    class _CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def aclose(self) -> None:
            return None

    async def _empty_atom_feed(
        _adapter: arxiv.ArxivSourceAdapter,
        _client: object,
        _params: dict[str, str],
    ) -> bytes:
        return b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    monkeypatch.setattr(arxiv.httpx, "AsyncClient", _CapturingClient)
    monkeypatch.setattr(arxiv.ArxivSourceAdapter, "_request_atom", _empty_atom_feed)

    candidates = await arxiv.ArxivSourceAdapter().search(
        SearchQuery(
            project_id="project_version_user_agent",
            query="version metadata",
            sources=("arxiv",),
        ),
        run_id="run_version_user_agent",
    )

    assert candidates == ()
    assert captured["headers"] == {
        "User-Agent": "ScholarAI/0.1.9.3 compliant-open-access-client"
    }
