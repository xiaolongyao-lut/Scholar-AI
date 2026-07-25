from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def test_pyproject_declares_python_311_runtime_floor() -> None:
    """Project metadata must match runtime imports that use Python 3.11 APIs."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert data["project"]["requires-python"] == ">=3.11"
    assert data["tool"]["mypy"]["python_version"] == "3.11"
    assert data["tool"]["black"]["target-version"] == ["py311"]


def test_pyproject_reads_product_version_from_runtime_source() -> None:
    """Build metadata must resolve the product version from one module attribute."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert "version" not in data["project"]
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "literature_assistant.version.__version__"
    }


def test_package_exposes_current_four_part_product_version() -> None:
    """The public package must expose the current four-part product version."""

    from literature_assistant import __version__

    assert __version__ == "0.1.9.0"


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

    expected = "ScholarAI/0.1.9.0 compliant-open-access-client"
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
        "User-Agent": "ScholarAI/0.1.9.0 compliant-open-access-client"
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
        "User-Agent": "ScholarAI/0.1.9.0 compliant-open-access-client"
    }
