"""
Pytest configuration and shared fixtures
"""

import json
import pytest
import sys
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "literature_assistant" / "core"
EVALUATION_SCRIPTS = ROOT / "workspace_tests" / "evaluation_scripts"
EXPERIMENT_MY_PROJECT_SRC = ROOT / "workspace_references" / "experiments" / "my-project" / "src"
for import_root in (EXPERIMENT_MY_PROJECT_SRC, EVALUATION_SCRIPTS, CORE):
    import_root_text = str(import_root)
    if import_root.is_dir():
        while import_root_text in sys.path:
            sys.path.remove(import_root_text)
        sys.path.insert(0, import_root_text)

from modules.configuration_manager import ConfigurationManager
from modules.evidence_classifier import EvidenceClassifier


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
