"""
Pytest configuration and shared fixtures
"""

import json
import os
import pytest
import sys
import importlib
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "literature_assistant" / "core"
EVALUATION_SCRIPTS = ROOT / "workspace_tests" / "evaluation_scripts"
EXPERIMENT_MY_PROJECT_SRC = ROOT / "workspace_references" / "experiments" / "my-project" / "src"
_PYTEST_RUNTIME_ROOT = ROOT / "workspace_artifacts" / "runtime_state" / f"pytest_{os.getpid()}"
_PYTEST_USER_ROOT = ROOT / "workspace_artifacts" / "pytest" / f"pytest_{os.getpid()}"
os.environ.setdefault("RUNTIME_ENV_DISABLE_DOTENV", "1")
os.environ.setdefault("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", str(_PYTEST_RUNTIME_ROOT))
os.environ.setdefault("LITERATURE_ASSISTANT_USER_ROOT", str(_PYTEST_USER_ROOT))
os.environ.setdefault("LITASSIST_DISABLE_FILE_LOG", "1")
os.environ.setdefault("LITASSIST_DISABLE_ROUTE_DUMP", "1")
os.environ.setdefault("LITASSIST_API_CAPABILITY_AUTH", "0")
os.environ.setdefault("LITASSIST_CREDENTIAL_SECRET_BACKEND", "plaintext_file")
for import_root in (EXPERIMENT_MY_PROJECT_SRC, EVALUATION_SCRIPTS, CORE):
    import_root_text = str(import_root)
    if import_root.is_dir():
        while import_root_text in sys.path:
            sys.path.remove(import_root_text)
        sys.path.insert(0, import_root_text)

from modules.configuration_manager import ConfigurationManager
from modules.evidence_classifier import EvidenceClassifier


@pytest.fixture(autouse=True)
def _stable_provider_endpoint_dns_for_tests(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep mocked remote-provider tests independent from ambient DNS results.

    Args:
        monkeypatch: Pytest patch helper for the current test.
        request: Current test metadata used to avoid masking policy-unit tests.
    """

    if request.node.path.name == "test_provider_endpoint_policy.py":
        return

    try:
        import provider_endpoint_policy
    except Exception:
        return

    monkeypatch.setattr(
        provider_endpoint_policy,
        "resolve_host",
        lambda host: ["104.18.6.192"],
    )


@pytest.fixture(autouse=True)
def _evolution_capture_inline(monkeypatch):
    """Opt §1: force evolution capture to run inline during tests.

    Production code dispatches capture writes to a daemon thread so request
    latency is not gated by candidate persistence. Tests assert the row
    landed in the store right after the call returns, so they need
    deterministic synchronous behavior. Per-test opt-out is available by
    re-deleting the env var in the test body.
    """

    monkeypatch.setenv("EVOLUTION_BACKGROUND_CAPTURE_DISABLED", "1")
    yield


@pytest.fixture(autouse=True)
def _isolate_writing_resource_persistence(monkeypatch, tmp_path):
    """Keep backend resource tests from writing into the real workspace.

    Why:
        API tests create projects through the same FastAPI app used by the
        desktop process. Without per-test resource paths, fixture projects leak
        into the developer/user project selector and can be persisted in the
        default workspace database.
    """

    resource_db_path = tmp_path / "writing_resources_state.sqlite3"
    resource_snapshot_path = tmp_path / "writing_resources_state.json"
    workspace_artifacts_root = tmp_path / "workspace_artifacts"
    projects_root = workspace_artifacts_root / "projects"
    monkeypatch.setenv("WRITING_RESOURCE_DB_PATH", str(resource_db_path))
    monkeypatch.setenv("WRITING_RESOURCE_STORE_PATH", str(resource_snapshot_path))
    monkeypatch.setenv("LITERATURE_ASSISTANT_USER_ROOT", str(workspace_artifacts_root))

    def _test_project_data_path(project_id: str, *parts: str) -> Path:
        safe_id = "".join(c for c in str(project_id) if c.isalnum() or c in "_-")
        if not safe_id:
            safe_id = "_default"
        return projects_root.joinpath(safe_id, *parts)

    for module_name in ("project_paths", "literature_assistant.core.project_paths"):
        try:
            project_paths_module = importlib.import_module(module_name)
        except Exception:
            continue
        monkeypatch.setattr(project_paths_module, "WORKSPACE_ARTIFACTS_ROOT", workspace_artifacts_root, raising=False)

    try:
        from routers import resources_router as rr

        monkeypatch.setattr(rr, "_PROJECTS_DATA_ROOT", projects_root, raising=False)
        monkeypatch.setattr(rr, "project_data_path", _test_project_data_path, raising=False)
    except Exception:
        pass

    try:
        import writing_resources

        writing_resources._get_writing_resource_store_singleton.cache_clear()
    except Exception:
        pass

    yield

    try:
        import writing_resources

        writing_resources._get_writing_resource_store_singleton.cache_clear()
    except Exception:
        pass


@pytest.fixture
def sample_config_dict() -> Dict[str, Any]:
    """Sample configuration dictionary"""
    return {
        "version": "1.0",
        "weights": {
            "direct_evidence": 0.85,
            "methodological_evidence": 0.70,
            "correlational_evidence": 0.60,
            "theoretical_evidence": 0.50,
            "anecdotal_evidence": 0.30,
            "method_description": 0.15,
            "result_articulation": 0.25,
        },
        "thresholds": {
            "low_quality": 0.30,
            "medium_quality": 0.60,
            "high_quality": 0.85,
        },
        "goal_mapping": {
            "工艺参数": ["parameter", "power", "speed"],
            "熔池流动": ["flow", "molten", "convection"],
        },
    }


@pytest.fixture
def tmp_config_file(tmp_path, sample_config_dict) -> Path:
    """Create a temporary config file"""
    config_path = tmp_path / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(sample_config_dict, f)
    return config_path


@pytest.fixture
def config_manager(tmp_config_file) -> ConfigurationManager:
    """ConfigurationManager instance with test config"""
    return ConfigurationManager(str(tmp_config_file))


@pytest.fixture
def evidence_classifier(config_manager) -> EvidenceClassifier:
    """EvidenceClassifier instance"""
    return EvidenceClassifier(config_manager)


@pytest.fixture
def sample_evidence_texts() -> Dict[str, str]:
    """Sample evidence texts for testing"""
    return {
        "high_quality_direct": (
            "We used laser ablation technique (power: 2000W, frequency: 10Hz) "
            "and observed a significant increase in hardness from 300HV to 800HV. "
            "This result is due to the formation of hard nitride phases."
        ),
        "medium_quality_methodological": (
            "Specimens were prepared using standard metallographic techniques. "
            "Hardness was measured using nanoindentation."
        ),
        "low_quality_anecdotal": (
            "The material seemed harder after processing."
        ),
        "empty": "",
        "too_short": "Was tested.",
        "with_hedges": (
            "The treatment may possibly indicate a potential improvement "
            "in possible mechanical properties."
        ),
        "no_domain_keywords": (
            "The computer system processed the data and generated results. "
            "This approach could be useful for future applications."
        ),
    }


@pytest.fixture
def sample_extraction_data() -> Dict[str, Any]:
    """Sample paper extraction data"""
    return {
        "paper_id": "test_paper_001",
        "source_pdf": "/path/to/paper.pdf",
        "chunks": [
            {
                "chunk_id": "c0001",
                "page": 1,
                "text": "We used laser processing with power 2000W and observed hardness increase.",
            },
            {
                "chunk_id": "c0002",
                "page": 2,
                "text": "The molten pool dynamics were affected by laser beam oscillation.",
            },
            {
                "chunk_id": "c0003",
                "page": 3,
                "text": "Short text.",
            },
        ],
    }


@pytest.fixture(scope="session", autouse=True)
def setup_test_logging():
    """Configure logging for tests"""
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    yield
    logging.shutdown()
