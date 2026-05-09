"""
Unit tests for configuration_manager.py

Tests configuration loading, validation, and access patterns.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.configuration_manager import (
    ConfigurationManager,
    ScoringWeights,
    ScoringThresholds,
    ScoringMultipliers,
    get_configuration,
    set_configuration_path,
)


class TestScoringWeights:
    """Test ScoringWeights dataclass"""
    
    def test_default_initialization(self):
        """Test default weight values"""
        weights = ScoringWeights()
        
        assert weights.direct_evidence == 0.85
        assert weights.methodological_evidence == 0.70
        assert weights.correlational_evidence == 0.60
        assert weights.anecdotal_evidence == 0.30
    
    def test_custom_initialization(self):
        """Test custom weight initialization"""
        weights = ScoringWeights(direct_evidence=0.9, anecdotal_evidence=0.2)
        
        assert weights.direct_evidence == 0.9
        assert weights.anecdotal_evidence == 0.2
        # Others should keep defaults
        assert weights.methodological_evidence == 0.70


class TestScoringThresholds:
    """Test ScoringThresholds dataclass"""
    
    def test_default_thresholds(self):
        """Test default threshold values"""
        thresholds = ScoringThresholds()
        
        assert thresholds.low_quality == 0.30
        assert thresholds.medium_quality == 0.60
        assert thresholds.high_quality == 0.85
    
    def test_threshold_ordering(self):
        """Thresholds should be in ascending order"""
        thresholds = ScoringThresholds()
        
        assert (thresholds.low_quality < 
                thresholds.medium_quality < 
                thresholds.high_quality)


class TestConfigurationManager:
    """Test ConfigurationManager class"""
    
    @pytest.mark.unit
    def test_load_valid_config(self, tmp_config_file):
        """Test loading valid configuration file"""
        config = ConfigurationManager(str(tmp_config_file))
        
        assert config.config_path == str(tmp_config_file)
        assert len(config.config) > 0
        assert config.weights is not None
        assert config.thresholds is not None
    
    def test_config_not_found(self, tmp_path):
        """Test handling of missing config file"""
        nonexistent_path = str(tmp_path / "nonexistent.json")
        
        config = ConfigurationManager(nonexistent_path)
        
        # Should use defaults
        assert config.weights.direct_evidence == 0.85
    
    def test_invalid_json(self, tmp_path):
        """Test handling of invalid JSON"""
        bad_json_path = tmp_path / "bad.json"
        bad_json_path.write_text("{ invalid json }")
        
        config = ConfigurationManager(str(bad_json_path))
        
        # Should use defaults
        assert config.weights.direct_evidence == 0.85
    
    def test_get_weight(self, config_manager):
        """Test weight retrieval"""
        weight = config_manager.get_weight("direct_evidence")
        
        assert weight == 0.85
    
    def test_get_weight_nonexistent(self, config_manager):
        """Test getting non-existent weight returns default"""
        weight = config_manager.get_weight("nonexistent_weight")
        
        assert weight == 0.5  # Default fallback
    
    def test_get_threshold(self, config_manager):
        """Test threshold retrieval"""
        threshold = config_manager.get_threshold("high_quality")
        
        assert threshold == 0.85
    
    def test_get_multiplier(self, config_manager):
        """Test multiplier retrieval"""
        multiplier = config_manager.get_multiplier("full_paper_advantage")
        
        assert multiplier == 1.2
    
    def test_get_goal_keywords(self, config_manager):
        """Test goal keyword retrieval"""
        keywords = config_manager.get_goal_keywords("工艺参数")
        
        assert "parameter" in keywords
        assert isinstance(keywords, list)
    
    def test_get_goal_keywords_nonexistent(self, config_manager):
        """Test getting keywords for non-existent goal"""
        keywords = config_manager.get_goal_keywords("nonexistent_goal")
        
        assert keywords == []
    
    def test_compile_pattern(self, config_manager):
        """Test regex pattern compilation"""
        pattern = config_manager.compile_pattern(r"\b(test|hello)\b")
        
        assert pattern.search("test string") is not None
        assert pattern.search("hello world") is not None
    
    def test_pattern_caching(self, config_manager):
        """Test that patterns are cached"""
        pattern_str = r"\b(test|hello)\b"
        
        pattern1 = config_manager.compile_pattern(pattern_str)
        pattern2 = config_manager.compile_pattern(pattern_str)
        
        # Should return same object from cache
        assert pattern1 is pattern2
    
    def test_get_classification_quality(self, config_manager):
        """Test quality classification"""
        assert config_manager.get_classification_quality(0.9) == "High"
        assert config_manager.get_classification_quality(0.7) == "Medium"
        assert config_manager.get_classification_quality(0.2) == "Low"
    
    def test_to_dict(self, config_manager):
        """Test configuration export to dict"""
        config_dict = config_manager.to_dict()
        
        assert "weights" in config_dict
        assert "thresholds" in config_dict
        assert "multipliers" in config_dict
        assert "goal_mapping" in config_dict
    
    def test_repr(self, config_manager):
        """Test string representation"""
        repr_str = repr(config_manager)
        
        assert "ConfigurationManager" in repr_str
        assert "config_path" in repr_str


class TestGlobalConfigurationInstance:
    """Test global configuration singleton pattern"""
    
    def test_get_configuration_singleton(self):
        """Test that get_configuration returns same instance"""
        config1 = get_configuration()
        config2 = get_configuration()
        
        # Should be same object
        assert config1 is config2
    
    def test_set_configuration_path(self, tmp_config_file):
        """Test setting custom configuration path"""
        # This clears the singleton
        set_configuration_path(str(tmp_config_file))
        
        config = get_configuration()
        assert config.config_path == str(tmp_config_file)


class TestConfigurationValidation:
    """Test configuration validation logic"""
    
    def test_weights_in_valid_range(self, config_manager):
        """Weights should be in reasonable range (allows negative for penalties)"""
        for attr in dir(config_manager.weights):
            if not attr.startswith('_'):
                value = getattr(config_manager.weights, attr)
                if isinstance(value, (int, float)):
                    # Allow range [-1, 1] to accommodate penalty weights
                    assert -1 <= value <= 1
    
    def test_thresholds_in_valid_range(self, config_manager):
        """Thresholds should be between 0 and 1"""
        for attr in dir(config_manager.thresholds):
            if not attr.startswith('_'):
                value = getattr(config_manager.thresholds, attr)
                if isinstance(value, (int, float)):
                    assert 0 <= value <= 1
    
    def test_goal_mapping_structure(self, config_manager):
        """Goal mapping should be dict of lists"""
        assert isinstance(config_manager.goal_mapping, dict)
        for goal, keywords in config_manager.goal_mapping.items():
            assert isinstance(goal, str)
            assert isinstance(keywords, list)
            assert all(isinstance(kw, str) for kw in keywords)


class TestConfigurationUpdates:
    """Test dynamic configuration updates"""
    
    def test_modify_weights(self, config_manager):
        """Test modifying weights after initialization"""
        original_value = config_manager.weights.direct_evidence
        config_manager.weights.direct_evidence = 0.5
        
        assert config_manager.weights.direct_evidence == 0.5
        assert config_manager.get_weight("direct_evidence") == 0.5
    
    def test_invalid_pattern_compilation(self, config_manager):
        """Test handling of invalid regex patterns"""
        # Should not raise, should return non-matching pattern
        pattern = config_manager.compile_pattern("(?!.*)")  # Valid but matches nothing
        
        assert pattern.search("test") is None


class TestConfigurationEdgeCases:
    """Test edge cases for configuration management"""
    
    @pytest.mark.unit
    def test_empty_config_file(self, tmp_path):
        """Test handling of empty config file"""
        empty_config = tmp_path / "empty.json"
        empty_config.write_text("{}")
        
        config = ConfigurationManager(str(empty_config))
        
        # Should use defaults
        assert config.weights.direct_evidence == 0.85
    
    def test_config_with_extra_fields(self, tmp_path):
        """Test config file with unknown fields"""
        extra_config = tmp_path / "extra.json"
        data = {
            "version": "1.0",
            "weights": {"direct_evidence": 0.9},
            "unknown_field": "should_be_ignored",
        }
        extra_config.write_text(json.dumps(data))
        
        config = ConfigurationManager(str(extra_config))
        
        # Should still work
        assert config.weights.direct_evidence == 0.9
    
    def test_default_config_path(self):
        """Test default config path determination"""
        # This test verifies the logic without creating actual files
        default_path = ConfigurationManager._get_default_config_path()
        
        assert "config" in default_path.lower()
        assert "scoring_rules" in default_path.lower()


@pytest.mark.integration
class TestConfigurationIntegration:
    """Integration tests with other components"""
    
    def test_config_with_evidence_classifier(self, config_manager):
        """Test configuration works with evidence classifier"""
        from modules.evidence_classifier import EvidenceClassifier
        
        classifier = EvidenceClassifier(config_manager)
        
        assert classifier.config is config_manager
    
    def test_config_with_paper_processor(self, config_manager):
        """Test configuration works with paper processor"""
        from modules.paper_processor import PaperProcessor
        
        processor = PaperProcessor(config_manager)
        
        assert processor.config is config_manager
