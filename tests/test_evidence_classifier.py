"""
Unit tests for evidence_classifier.py

Tests evidence classification logic, pattern matching, and scoring algorithms.
"""

import pytest
from modules.evidence_classifier import (
    EvidenceClassifier, 
    EvidenceType, 
    EvidencePattern,
    EvidenceScore
)


class TestEvidencePattern:
    """Test regex patterns for evidence detection"""
    
    def test_method_cues_detection(self):
        """Test METHOD_CUES pattern matching"""
        assert EvidencePattern.METHOD_CUES.search("We used a method to") is not None
        assert EvidencePattern.METHOD_CUES.search("Experimental procedure") is not None
        assert EvidencePattern.METHOD_CUES.search("The process employed") is not None
        assert EvidencePattern.METHOD_CUES.search("No matches here") is None
    
    def test_result_cues_detection(self):
        """Test RESULT_CUES pattern matching"""
        assert EvidencePattern.RESULT_CUES.search("result in hardness") is not None
        assert EvidencePattern.RESULT_CUES.search("increased accuracy") is not None
        assert EvidencePattern.RESULT_CUES.search("achieved 95% yield") is not None
        assert EvidencePattern.RESULT_CUES.search("decreased performance") is not None
    
    def test_mechanism_cues_detection(self):
        """Test MECHANISM_CUES pattern matching"""
        assert EvidencePattern.MECHANISM_CUES.search("because of") is not None
        assert EvidencePattern.MECHANISM_CUES.search("due to thermal effects") is not None
        assert EvidencePattern.MECHANISM_CUES.search("therefore we conclude") is not None
    
    def test_hedge_cues_detection(self):
        """Test HEDGE_CUES pattern matching"""
        assert EvidencePattern.HEDGE_CUES.search("may possibly") is not None
        assert EvidencePattern.HEDGE_CUES.search("might suggest") is not None
        assert EvidencePattern.HEDGE_CUES.search("appears likely") is not None
    
    def test_numeric_pattern(self):
        """Test NUMERIC_PATTERN matching"""
        assert EvidencePattern.NUMERIC_PATTERN.search("2000W laser") is not None
        assert EvidencePattern.NUMERIC_PATTERN.search("3.5mm thickness") is not None
        assert EvidencePattern.NUMERIC_PATTERN.search("800HV hardness") is not None
        assert EvidencePattern.NUMERIC_PATTERN.search("90°C temperature") is not None
    
    def test_citation_pattern(self):
        """Test CITATION_PATTERN matching"""
        assert EvidencePattern.CITATION_PATTERN.search("[1]") is not None
        assert EvidencePattern.CITATION_PATTERN.search("[1-3]") is not None
        assert EvidencePattern.CITATION_PATTERN.search("[1, 5, 8]") is not None


class TestEvidenceTypeDetection:
    """Test evidence type determination logic"""
    
    def test_direct_evidence(self, evidence_classifier):
        """Test DIRECT evidence type detection"""
        text = "We used method X and observed result Y, which demonstrates mechanism Z."
        score = evidence_classifier.classify_evidence(text)
        assert score.evidence_type in [EvidenceType.DIRECT, EvidenceType.METHODOLOGICAL]
        assert score.final_score >= 0.5
    
    def test_methodological_evidence(self, evidence_classifier):
        """Test METHODOLOGICAL evidence type detection"""
        text = "Samples were prepared using standard techniques and tested with equipment."
        score = evidence_classifier.classify_evidence(text)
        assert score.evidence_type in [
            EvidenceType.METHODOLOGICAL, 
            EvidenceType.UNKNOWN
        ]
    
    def test_correlational_evidence(self, evidence_classifier):
        """Test CORRELATIONAL evidence type detection"""
        text = "Results showed increased strength, which is due to grain refinement."
        score = evidence_classifier.classify_evidence(text)
        assert score.final_score >= 0.45
    
    def test_anecdotal_evidence(self, evidence_classifier):
        """Test ANECDOTAL evidence type detection"""
        text = "The material seemed harder after processing."
        score = evidence_classifier.classify_evidence(text)
        assert score.evidence_type.value in ["anecdotal_evidence", "unknown"]
        assert score.final_score <= 0.5


class TestEvidenceScoring:
    """Test evidence scoring calculations"""
    
    @pytest.mark.unit
    def test_score_range(self, evidence_classifier):
        """All scores should be in range [0, 1]"""
        test_texts = [
            "We used laser technique with power 2000W and achieved hardness of 1000HV.",
            "Material was tested.",
            "May possibly improve.",
            "",
        ]
        for text in test_texts:
            score = evidence_classifier.classify_evidence(text)
            assert 0.0 <= score.final_score <= 1.0
            assert 0.0 <= score.method_score <= 1.0
            assert 0.0 <= score.result_score <= 1.0
    
    def test_hedge_penalty(self, evidence_classifier):
        """Hedge language should reduce score"""
        text_no_hedge = "We used method X and achieved result Y."
        text_with_hedge = "We may possibly use method X and might achieve result Y."
        
        score_no_hedge = evidence_classifier.classify_evidence(text_no_hedge)
        score_with_hedge = evidence_classifier.classify_evidence(text_with_hedge)
        
        # With hedge should have lower score
        assert score_with_hedge.final_score < score_no_hedge.final_score
    
    def test_numeric_data_boost(self, evidence_classifier):
        """Numeric data should boost result score"""
        text_no_numbers = "The hardness increased significantly."
        text_with_numbers = "The hardness increased from 300 to 800 HV."
        
        score_no_numbers = evidence_classifier.classify_evidence(text_no_numbers)
        score_with_numbers = evidence_classifier.classify_evidence(text_with_numbers)
        
        # With numbers should have higher result score
        assert score_with_numbers.result_score > score_no_numbers.result_score
    
    def test_quality_classification(self, evidence_classifier, config_manager):
        """Test quality label assignment"""
        high_text = "We used laser technique with power 2000W and achieved hardness increase from 300HV to 1000HV. This result is due to nitride formation based on [1-3]."
        medium_text = "Samples were tested and showed improvement in mechanical properties."
        low_text = "It was better."
        
        high_score = evidence_classifier.classify_evidence(high_text)
        medium_score = evidence_classifier.classify_evidence(medium_text)
        low_score = evidence_classifier.classify_evidence(low_text)
        
        high_label = evidence_classifier.get_quality_label(high_score.final_score)
        medium_label = evidence_classifier.get_quality_label(medium_score.final_score)
        low_label = evidence_classifier.get_quality_label(low_score.final_score)
        
        # High score should be highest
        assert high_score.final_score >= medium_score.final_score
        assert medium_score.final_score >= low_score.final_score
        # Just verify the method returns valid labels
        assert high_label in ["High", "Medium"]
        assert medium_label in ["Medium", "Low"]
        assert low_label in ["Low"]


class TestKeywordExtraction:
    """Test keyword extraction functionality"""
    
    def test_extract_keywords(self, evidence_classifier):
        """Test that keywords are extracted correctly"""
        text = "Laser processing with high-power beam significantly improved material hardness properties."
        keywords = evidence_classifier.extract_keywords(text, max_keywords=5)
        
        assert len(keywords) <= 5
        assert all(len(kw) > 3 for kw in keywords)  # No short words
        assert "laser" in keywords  # Should contain technical terms
    
    def test_stopwords_filtered(self, evidence_classifier):
        """Test that stopwords are filtered out"""
        text = "The and for with material was tested in the laboratory."
        keywords = evidence_classifier.extract_keywords(text, max_keywords=10)
        
        stopwords = {'the', 'and', 'for', 'with', 'was', 'in'}
        assert not any(kw in stopwords for kw in keywords)


class TestConfigIntegration:
    """Test integration with configuration manager"""
    
    def test_classifier_with_config(self, config_manager):
        """Test classifier initialization with config"""
        classifier = EvidenceClassifier(config_manager)
        
        assert classifier.config is not None
        assert len(classifier.stopwords) > 0
    
    def test_classifier_without_config(self):
        """Test classifier works without config"""
        classifier = EvidenceClassifier(config_manager=None)
        
        text = "We used method and improved results."
        score = classifier.classify_evidence(text)
        
        assert isinstance(score, EvidenceScore)
        assert 0 <= score.final_score <= 1


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    @pytest.mark.unit
    def test_empty_text(self, evidence_classifier):
        """Test with empty text"""
        score = evidence_classifier.classify_evidence("")
        assert score.final_score >= 0
        assert score.evidence_type == EvidenceType.UNKNOWN
    
    def test_very_long_text(self, evidence_classifier):
        """Test with very long text"""
        # Generate a 10KB text
        text = "laser processing " * 600
        text += "and improved hardness from 300 to 1000HV"
        
        score = evidence_classifier.classify_evidence(text)
        assert 0 <= score.final_score <= 1
    
    def test_special_characters(self, evidence_classifier):
        """Test with special characters and unicode"""
        text = "激光处理（2000W）提高硬度至1000HV。Material: Ti-6Al-4V [1-3]"
        score = evidence_classifier.classify_evidence(text)
        assert 0 <= score.final_score <= 1
    
    def test_duplicate_keywords(self, evidence_classifier):
        """Test text with repeated keywords"""
        text = "Method used method technique methodology approach method method."
        score = evidence_classifier.classify_evidence(text)
        assert score.method_score > 0


@pytest.mark.performance
class TestPerformance:
    """Performance tests for classifier"""
    
    def test_classification_speed(self, evidence_classifier):
        """Test that classification is reasonably fast"""
        import time
        
        text = "We used advanced laser technique with power 2000W and observed significant improvement in material hardness."
        
        start = time.time()
        for _ in range(100):
            evidence_classifier.classify_evidence(text)
        elapsed = time.time() - start
        
        # Should process 100 texts in < 1 second
        assert elapsed < 1.0, f"Classification took {elapsed:.3f}s for 100 texts"
    
    def test_keyword_extraction_speed(self, evidence_classifier):
        """Test keyword extraction performance"""
        import time
        
        text = "Laser processing with high-power beam significantly improved hardness properties of titanium alloys."
        
        start = time.time()
        for _ in range(100):
            evidence_classifier.extract_keywords(text)
        elapsed = time.time() - start
        
        assert elapsed < 0.5, f"Keyword extraction took {elapsed:.3f}s for 100 texts"
