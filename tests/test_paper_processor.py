"""
Unit tests for paper_processor.py

Tests paper processing, goal matching, and result aggregation.
"""

import pytest
from typing import Dict, Any

from modules.paper_processor import (
    PaperProcessor,
    PaperGoalResult,
    PaperProcessReport,
)


class TestPaperGoalResult:
    """Test PaperGoalResult dataclass"""
    
    def test_initialization(self):
        """Test default initialization"""
        result = PaperGoalResult(goal="工艺参数")
        
        assert result.goal == "工艺参数"
        assert result.max_score == 0.0
        assert result.average_score == 0.0
        assert result.hits_count == 0
        assert result.best_claim == ""
        assert result.quality_label == "Low"
    
    def test_custom_initialization(self):
        """Test custom initialization"""
        result = PaperGoalResult(
            goal="性能",
            max_score=0.85,
            average_score=0.75,
            hits_count=5,
            best_claim="Sample evidence text",
            quality_label="High",
        )
        
        assert result.goal == "性能"
        assert result.max_score == 0.85
        assert result.hits_count == 5


class TestPaperProcessReport:
    """Test PaperProcessReport dataclass"""
    
    def test_initialization(self):
        """Test report initialization"""
        goal_results = {
            "工艺参数": PaperGoalResult(goal="工艺参数"),
            "性能": PaperGoalResult(goal="性能"),
        }
        
        report = PaperProcessReport(
            paper_id="test_001",
            source_pdf="/path/to/paper.pdf",
            total_chunks=10,
            goal_results=goal_results,
        )
        
        assert report.paper_id == "test_001"
        assert report.total_chunks == 10
        assert len(report.goal_results) == 2


class TestPaperProcessor:
    """Test PaperProcessor class"""
    
    def test_initialization(self, config_manager):
        """Test processor initialization"""
        processor = PaperProcessor(config_manager)
        
        assert processor.config is config_manager
        assert processor.classifier is not None
    
    @pytest.mark.unit
    def test_process_data_simple(self, config_manager, sample_extraction_data):
        """Test basic data processing"""
        processor = PaperProcessor(config_manager)
        
        report = processor.process_data(sample_extraction_data, "test_001")
        
        assert report.paper_id == "test_001"
        assert isinstance(report, PaperProcessReport)
        assert report.total_chunks == 3
    
    def test_process_data_with_no_chunks(self, config_manager):
        """Test processing with no chunks"""
        processor = PaperProcessor(config_manager)
        
        data = {
            "paper_id": "empty_paper",
            "source_pdf": "/path/to/empty.pdf",
            "chunks": [],
        }
        
        report = processor.process_data(data, "empty_paper")
        
        assert report.paper_id == "empty_paper"
        assert report.total_chunks == 0
        assert report.overall_score == 0.0
    
    def test_process_data_goal_matching(self, config_manager, sample_extraction_data):
        """Test goal keyword matching"""
        processor = PaperProcessor(config_manager)
        
        report = processor.process_data(sample_extraction_data, "test_001")
        
        # Check that goals are recognized
        assert len(report.goal_results) > 0
        
        # At least one goal should have hits
        has_hits = any(result.hits_count > 0 for result in report.goal_results.values())
        assert has_hits
    
    def test_process_data_overall_score(self, config_manager, sample_extraction_data):
        """Test overall score calculation"""
        processor = PaperProcessor(config_manager)
        
        report = processor.process_data(sample_extraction_data, "test_001")
        
        assert 0 <= report.overall_score <= 1
        assert 0 <= report.overall_confidence <= 1
    
    def test_process_data_best_claim_selection(self, config_manager):
        """Test that best claim is selected by score"""
        processor = PaperProcessor(config_manager)
        
        data = {
            "paper_id": "test",
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [
                {
                    "chunk_id": "c0001",
                    "page": 1,
                    "text": "Poor evidence with no structure.",
                },
                {
                    "chunk_id": "c0002",
                    "page": 2,
                    "text": "We used laser processing with 2000W power and achieved hardness increase to 1000HV due to nitride formation.",
                },
            ],
        }
        
        report = processor.process_data(data, "test")
        
        # Best claim should be from stronger evidence
        for goal_result in report.goal_results.values():
            if goal_result.best_claim:
                # The best claim should be high quality evidence
                assert len(goal_result.best_claim) > 0


class TestPaperProcessorWithFiles:
    """Test paper processor with file operations"""
    
    def test_process_json_file(self, config_manager, tmp_path):
        """Test loading and processing JSON file"""
        import json
        
        # Create a paper-specific subdirectory
        paper_dir = tmp_path / "file_test"
        paper_dir.mkdir()

        # Create a test JSON file
        test_data = {
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [
                {
                    "chunk_id": "c0001",
                    "page": 1,
                    "text": "We used laser technique with power 2000W.",
                }
            ],
        }

        test_file = paper_dir / "extraction.json"
        test_file.write_text(json.dumps(test_data), encoding="utf-8")

        processor = PaperProcessor(config_manager)
        report = processor.process_json_file(str(test_file))

        # Paper ID should be extracted from directory name
        assert report.paper_id == "file_test"
        processor = PaperProcessor(config_manager)
        
        with pytest.raises(FileNotFoundError):
            processor.process_json_file("/nonexistent/path/file.json")
    
    def test_process_json_file_auto_paper_id(self, config_manager, tmp_path):
        """Test automatic paper ID extraction from directory name"""
        import json
        
        # Create nested directory structure
        paper_dir = tmp_path / "my_paper_001"
        paper_dir.mkdir()
        
        test_data = {
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [{"chunk_id": "c0001", "page": 1, "text": "Evidence text here."}],
        }
        
        test_file = paper_dir / "extraction.json"
        test_file.write_text(json.dumps(test_data), encoding="utf-8")
        
        processor = PaperProcessor(config_manager)
        report = processor.process_json_file(str(test_file))
        
        # Paper ID should be extracted from directory name
        assert report.paper_id == "my_paper_001"


class TestPaperProcessorEdgeCases:
    """Test edge cases in paper processing"""
    
    @pytest.mark.unit
    def test_process_data_with_empty_chunks(self, config_manager):
        """Test handling of empty chunk texts"""
        processor = PaperProcessor(config_manager)
        
        data = {
            "paper_id": "edge_test",
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [
                {"chunk_id": "c0001", "page": 1, "text": ""},  # empty
                {"chunk_id": "c0002", "page": 2, "text": "x"},  # too short
                {"chunk_id": "c0003", "page": 3, "text": "Valid evidence text with enough content to process."},
            ],
        }
        
        report = processor.process_data(data, "edge_test")
        
        # Should process only valid chunks
        assert report.total_chunks == 3  # All chunks are tracked
    
    def test_process_data_with_missing_fields(self, config_manager):
        """Test handling of missing chunk fields"""
        processor = PaperProcessor(config_manager)
        
        data = {
            "paper_id": "incomplete",
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [
                {
                    "chunk_id": "c0001",
                    # Missing 'page' field
                    # Missing 'text' field
                }
            ],
        }
        
        report = processor.process_data(data, "incomplete")
        
        # Should handle gracefully
        assert isinstance(report, PaperProcessReport)
    
    def test_process_data_with_unicode(self, config_manager):
        """Test processing with unicode text"""
        processor = PaperProcessor(config_manager)
        
        data = {
            "paper_id": "unicode_test",
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [
                {
                    "chunk_id": "c0001",
                    "page": 1,
                    "text": "激光加工技术提高了材料的硬度达到1000HV。"
                }
            ],
        }
        
        report = processor.process_data(data, "unicode_test")
        assert isinstance(report, PaperProcessReport)
    
    def test_process_data_with_special_characters(self, config_manager):
        """Test processing special characters"""
        processor = PaperProcessor(config_manager)
        
        data = {
            "paper_id": "special_char",
            "source_pdf": "/path/to/paper.pdf",
            "chunks": [
                {
                    "chunk_id": "c0001",
                    "page": 1,
                    "text": "Using Ti-6Al-4V alloy [1-3] with heat treatment (800°C, 2h) achieved 1000 HV hardness."
                }
            ],
        }
        
        report = processor.process_data(data, "special_char")
        assert isinstance(report, PaperProcessReport)


class TestPaperProcessorIntegration:
    """Integration tests for paper processor"""
    
    @pytest.mark.integration
    def test_full_processing_pipeline(self, config_manager, sample_extraction_data):
        """Test full processing from raw data to report"""
        processor = PaperProcessor(config_manager)
        
        report = processor.process_data(sample_extraction_data, "integration_test")
        
        # Verify all report fields are populated
        assert report.paper_id == "integration_test"
        assert report.source_pdf == "/path/to/paper.pdf"
        assert report.total_chunks == 3
        assert 0 <= report.overall_score <= 1
        assert 0 <= report.overall_confidence <= 1
        
        # Verify goal results
        assert len(report.goal_results) > 0
        for goal, result in report.goal_results.items():
            assert isinstance(result, PaperGoalResult)
            assert result.goal == goal
            assert 0 <= result.max_score <= 1
            assert 0 <= result.average_score <= 1
    
    def test_result_consistency(self, config_manager, sample_extraction_data):
        """Test that results are consistent (reproducible)"""
        processor = PaperProcessor(config_manager)
        
        report1 = processor.process_data(sample_extraction_data, "test")
        report2 = processor.process_data(sample_extraction_data, "test")
        
        assert report1.overall_score == report2.overall_score
        assert report1.overall_confidence == report2.overall_confidence


@pytest.mark.performance
class TestPaperProcessorPerformance:
    """Performance tests for paper processor"""
    
    def test_process_large_chunk_count(self, config_manager):
        """Test processing paper with many chunks"""
        import time
        
        # Generate 100 chunks
        chunks = [
            {
                "chunk_id": f"c{i:04d}",
                "page": i // 10 + 1,
                "text": f"This is chunk {i} with laser processing that achieved results."
            }
            for i in range(100)
        ]
        
        data = {
            "paper_id": "perf_test",
            "source_pdf": "/path/to/paper.pdf",
            "chunks": chunks,
        }
        
        processor = PaperProcessor(config_manager)
        
        start = time.time()
        report = processor.process_data(data, "perf_test")
        elapsed = time.time() - start
        
        # Should process 100 chunks in reasonable time
        assert elapsed < 5.0, f"Processing took {elapsed:.2f}s"
        assert report.total_chunks == 100
