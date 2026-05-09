# -*- coding: utf-8 -*-
"""
Classifier Interface Module
Defines the standard data structures and interfaces for evidence classifiers.
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable


class EvidenceType(Enum):
    """Evidence type classifications"""
    DIRECT = "direct_evidence"
    METHODOLOGICAL = "methodological_evidence"
    CORRELATIONAL = "correlational_evidence"
    THEORETICAL = "theoretical_evidence"
    ANECDOTAL = "anecdotal_evidence"
    UNKNOWN = "unknown"


@dataclass
class EvidenceScore:
    """Container for evidence scoring results"""
    evidence_type: EvidenceType
    base_score: float
    method_score: float = 0.0
    result_score: float = 0.0
    mechanism_score: float = 0.0
    background_score: float = 0.0
    hedge_penalty: float = 0.0
    final_score: float = 0.0
    confidence: float = 0.0
    details: Dict = field(default_factory=dict)


@runtime_checkable
class ClassifierInterface(Protocol):
    """Protocol defining the interface for all evidence classifiers"""
    
    def classify_evidence(self, text: str) -> EvidenceScore:
        """
        Classify text evidence and compute quality scores.
        
        Args:
            text: Text snippet to analyze
            
        Returns:
            EvidenceScore containing classification results
        """
        ...
    
    def get_quality_label(self, score: float) -> str:
        """
        Convert a numerical score to a human-readable quality label.
        
        Args:
            score: Numerical quality score (0.0 to 1.0)
            
        Returns:
            String label (e.g., "High", "Medium", "Low")
        """
        ...
