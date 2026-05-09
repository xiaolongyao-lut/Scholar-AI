"""
Configuration Manager for Evidence Scoring System
Handles loading, validation, and access to scoring configuration
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import re

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Container for scoring weights"""
    direct_evidence: float = 0.85
    methodological_evidence: float = 0.70
    correlational_evidence: float = 0.60
    theoretical_evidence: float = 0.50
    anecdotal_evidence: float = 0.30
    method_description: float = 0.15
    result_articulation: float = 0.25
    mechanism_explanation: float = 0.25
    background_context: float = 0.10
    hedge_factor: float = -0.10
    literature_grounding: float = 0.10
    current_work_emphasis: float = 0.15


@dataclass
class ScoringThresholds:
    """Container for scoring thresholds"""
    low_quality: float = 0.30
    medium_quality: float = 0.60
    high_quality: float = 0.85
    high_confidence: float = 0.90
    min_method_evidence: float = 0.20
    min_result_evidence: float = 0.25
    min_mechanism_evidence: float = 0.15


@dataclass
class ScoringMultipliers:
    """Container for scoring multipliers"""
    full_paper_advantage: float = 1.2
    abstract_only_penalty: float = 0.8
    recent_publication_boost: float = 1.1
    high_citation_boost: float = 1.15
    methodology_rigorous_boost: float = 1.2


class ConfigurationManager:
    """Manages scoring configuration loading and access"""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration manager"""
        self.config_path = config_path or self._get_default_config_path()
        self.config: Dict[str, Any] = {}
        self.weights = ScoringWeights()
        self.thresholds = ScoringThresholds()
        self.multipliers = ScoringMultipliers()
        self.goal_mapping: Dict[str, List[str]] = {}
        self._compiled_patterns: Dict[str, re.Pattern] = {}

        self.load_configuration()

    @staticmethod
    def _get_default_config_path() -> str:
        """Get default configuration path"""
        current_dir = Path(__file__).parent
        config_dir = current_dir.parent / "config"
        config_file = config_dir / "scoring_rules.json"
        return str(config_file)

    def load_configuration(self) -> None:
        """Load configuration from JSON file"""
        try:
            if not Path(self.config_path).exists():
                logger.warning(f"Configuration file not found: {self.config_path}")
                logger.info("Using default configuration values")
                return

            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
                logger.info(f"Loaded configuration from {self.config_path}")

            self._apply_configuration()

        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            logger.info("Using default configuration values")

    def _apply_configuration(self) -> None:
        """Apply loaded configuration to internal objects"""
        if 'weights' in self.config:
            for key, value in self.config['weights'].items():
                if hasattr(self.weights, key):
                    setattr(self.weights, key, value)

        if 'thresholds' in self.config:
            for key, value in self.config['thresholds'].items():
                if hasattr(self.thresholds, key):
                    setattr(self.thresholds, key, value)

        if 'multipliers' in self.config:
            for key, value in self.config['multipliers'].items():
                if hasattr(self.multipliers, key):
                    setattr(self.multipliers, key, value)

        if 'goal_mapping' in self.config:
            self.goal_mapping = self.config['goal_mapping']

    def get_weight(self, evidence_type: str) -> float:
        """Get weight for specific evidence type"""
        return getattr(self.weights, evidence_type, 0.5)

    def get_threshold(self, threshold_type: str) -> float:
        """Get threshold value"""
        return getattr(self.thresholds, threshold_type, 0.5)

    def get_multiplier(self, multiplier_type: str) -> float:
        """Get multiplier value"""
        return getattr(self.multipliers, multiplier_type, 1.0)

    def get_goal_keywords(self, goal: str) -> List[str]:
        """Get keywords for a specific goal"""
        return self.goal_mapping.get(goal, [])

    def compile_pattern(self, pattern_str: str) -> re.Pattern:
        """Compile and cache regex pattern"""
        if pattern_str not in self._compiled_patterns:
            try:
                self._compiled_patterns[pattern_str] = re.compile(
                    pattern_str,
                    re.IGNORECASE | re.MULTILINE
                )
            except re.error as e:
                logger.error(f"Failed to compile pattern '{pattern_str}': {e}")
                # Return a pattern that never matches
                self._compiled_patterns[pattern_str] = re.compile(r'(?!.*)')

        return self._compiled_patterns[pattern_str]

    def get_classification_quality(self, score: float) -> str:
        """Classify quality based on score"""
        if score >= self.thresholds.high_quality:
            return "High"
        elif score >= self.thresholds.medium_quality:
            return "Medium"
        else:
            return "Low"

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary format"""
        return {
            'weights': self.weights.__dict__,
            'thresholds': self.thresholds.__dict__,
            'multipliers': self.multipliers.__dict__,
            'goal_mapping': self.goal_mapping
        }

    def __repr__(self) -> str:
        return f"ConfigurationManager(config_path='{self.config_path}')"


# Global configuration instance
_config_instance: Optional[ConfigurationManager] = None


def get_configuration() -> ConfigurationManager:
    """Get or create global configuration instance (lazy loading)"""
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigurationManager()
    return _config_instance


def set_configuration_path(path: str) -> None:
    """Set custom configuration path and reload"""
    global _config_instance
    _config_instance = ConfigurationManager(config_path=path)
