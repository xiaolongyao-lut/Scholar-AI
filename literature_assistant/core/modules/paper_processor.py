"""
Paper Processor Module
Aggregates evidence across all chunks of a single academic paper
"""

import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field

from modules.configuration_manager import get_configuration
from modules.classifier_interface import ClassifierInterface, EvidenceScore
from modules.classifier_registry import ClassifierRegistry
from modules.scoring_interface import ScoringInterface
from modules.scoring_registry import ScoringRegistry

logger = logging.getLogger(__name__)


@dataclass
class PaperGoalResult:
    """Results for a specific research goal within a paper"""
    goal: str
    max_score: float = 0.0
    average_score: float = 0.0
    hits_count: int = 0
    best_claim: str = ""
    best_chunk_id: str = ""
    best_page: int = 0
    evidence_types: List[str] = field(default_factory=list)
    quality_label: str = "Low"


@dataclass
class PaperProcessReport:
    """Complete report for a processed paper"""
    paper_id: str
    source_pdf: str
    total_chunks: int
    goal_results: Dict[str, PaperGoalResult]
    overall_score: float = 0.0
    overall_confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class PaperProcessor:
    """Processes extracted paper data to evaluate research goals"""

    def __init__(
        self, 
        config=None, 
        classifier: Optional[ClassifierInterface] = None,
        scorer: Optional[ScoringInterface] = None
    ):
        """
        Initialize with configuration, classifier, and scorer
        
        Args:
            config: Configuration manager instance
            classifier: Optional classifier implementation (injected)
            scorer: Optional scoring engine implementation (injected)
        """
        self.config = config or get_configuration()
        
        # Resolve classifier
        if classifier:
            self.classifier = classifier
        else:
            logger.debug("No classifier injected, falling back to default from registry")
            self.classifier = ClassifierRegistry.create("default", config_manager=self.config)

        # Resolve scorer
        if scorer:
            self.scorer = scorer
        else:
            logger.debug("No scorer injected, falling back to default from registry")
            # Ensure default scorer is loaded
            import modules.default_scorer 
            self.scorer = ScoringRegistry.create("default")

    def process_json_file(self, file_path: str, paper_id: Optional[str] = None) -> PaperProcessReport:
        """
        Process a full_extract.json file
        
        Args:
            file_path: Path to the JSON file
            paper_id: Optional identifier for the paper
            
        Returns:
            PaperProcessReport containing scoring results
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        pid = paper_id or path.parent.name
        return self.process_data(data, pid)

    def process_data(self, data: Dict[str, Any], paper_id: str) -> PaperProcessReport:
        """
        Process extraction data dictionary
        
        Args:
            data: Extracted chunks data
            paper_id: Identifier for the paper
            
        Returns:
            PaperProcessReport
        """
        chunks = data.get("chunks", [])
        source_pdf = data.get("source_pdf", "unknown")
        
        # Determine goals from config or provided in data
        goals = list(self.config.goal_mapping.keys())
        goal_results: Dict[str, PaperGoalResult] = {
            goal: PaperGoalResult(goal=goal) for goal in goals
        }

        # Per-goal trackers for score calculation
        goal_scores: Dict[str, List[float]] = {goal: [] for goal in goals}

        for chunk in chunks:
            text = chunk.get("text", "")
            if not text or len(text) < 40:
                continue

            chunk_id = chunk.get("chunk_id", "c0000")
            page = chunk.get("page", 0)

            for goal in goals:
                keywords = self.config.get_goal_keywords(goal)
                if not keywords:
                    continue

                # Quick relevance check
                # Note: In a production system, this could be more sophisticated (e.g. embeddings)
                if not any(kw.lower() in text.lower() for kw in keywords):
                    continue

                # Evaluate evidence quality
                score_result = self.classifier.classify_evidence(text)
                
                # Update goal stats
                res = goal_results[goal]
                res.hits_count += 1
                res.evidence_types.append(score_result.evidence_type.value)
                goal_scores[goal].append(score_result.final_score)

                # Keep track of best claim
                if score_result.final_score > res.max_score:
                    res.max_score = score_result.final_score
                    res.best_claim = text[:500].strip() # Truncate for report
                    res.best_chunk_id = chunk_id
                    res.best_page = page
                    res.quality_label = self.config.get_classification_quality(score_result.final_score)

        # Finalize goal statistics via external scorer
        for goal, scores in goal_scores.items():
            res = goal_results[goal]
            metrics = self.scorer.calculate_goal_score(goal, scores, res.evidence_types)
            
            res.average_score = metrics.get("average_score", 0.0)
            if "max_score" in metrics:
                res.max_score = metrics["max_score"]
            if "quality_label" in metrics:
                res.quality_label = metrics["quality_label"]
                
            # Deduplicate evidence types
            res.evidence_types = sorted(set(res.evidence_types))

        # Finalize paper statistics via external scorer
        overall_metrics = self.scorer.calculate_overall_report(
            goal_results, 
            len(chunks),
            goals
        )
        
        overall_score = overall_metrics.get("overall_score", 0.0)
        overall_confidence = overall_metrics.get("overall_confidence", 0.0)

        return PaperProcessReport(
            paper_id=paper_id,
            source_pdf=source_pdf,
            total_chunks=len(chunks),
            goal_results=goal_results,
            overall_score=overall_score,
            overall_confidence=overall_confidence,
            metadata={
                "processed_goals": goals,
                "hit_distribution": {g: r.hits_count for g, r in goal_results.items()},
                "scorer": self.scorer.__class__.__name__
            }
        )
