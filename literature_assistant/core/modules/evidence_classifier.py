"""
Evidence Classifier Module
Classifies text snippets based on evidence quality and type
"""

import re
import logging
from collections import Counter
from typing import Dict, List, Tuple, Optional, Set
from modules.classifier_interface import EvidenceType, EvidenceScore, ClassifierInterface
from modules.classifier_registry import register_classifier

logger = logging.getLogger(__name__)


class EvidencePattern:
    """Pattern matching for evidence classification"""

    # Compiled regex patterns
    METHOD_CUES = re.compile(
        r'\b(method|methods|experimental|procedure|performed|used|employed|technique|process|approach)\b',
        re.IGNORECASE
    )
    
    RESULT_CUES = re.compile(
        r'\b(result|results|outcome|outcomes|performance|increased|increases|increase|decreased|decreases|decrease|reduced|reduces|reduce|improved|improves|improve|enhanced|enhances|enhance|achieved|achieves|achieve|yielded|yielding|yield|accuracy|hardness|strength|efficiency|rigidity|ductility|toughness)\b',
        re.IGNORECASE
    )
    
    MECHANISM_CUES = re.compile(
        r'\b(because|due to|result in|promote|suppress|mechanism|attribute|therefore|thus|consequently)\b',
        re.IGNORECASE
    )
    
    BACKGROUND_CUES = re.compile(
        r'\b(challenge|however|traditionally|previous|recent|introduction|background|conventionally)\b',
        re.IGNORECASE
    )
    
    HEDGE_CUES = re.compile(
        r'\b(may|might|could|suggest|likely|appears|potentially|indicates|seems|possibly)\b',
        re.IGNORECASE
    )
    
    CITATION_PATTERN = re.compile(
        r'\[\s*(?:\d+[\s,–\-]*)+\s*\]|\b\d{1,3}\b(?=\s*(?:,|\.|\)|]))',
        re.MULTILINE
    )
    
    NUMERIC_PATTERN = re.compile(
        r'\b\d+(?:\.\d+)?(?:\s*(?:%|wt\.%|at\.%|μm|µm|mm|nm|kW|W|Hz|MPa|HV|J/mm|L/min|°C|K|min|s|epoch))?\b',
        re.IGNORECASE
    )





@register_classifier("default")
class EvidenceClassifier(ClassifierInterface):
    """Classifies text evidence and assigns quality scores"""

    def __init__(self, config_manager=None):
        """Initialize classifier with optional configuration"""
        self.config = config_manager
        self.stopwords: Set[str] = self._load_stopwords()

    @staticmethod
    def _load_stopwords() -> Set[str]:
        """Load common English stopwords"""
        return {
            'the', 'and', 'for', 'with', 'that', 'this', 'from', 'were', 'was',
            'are', 'into', 'under', 'than', 'when', 'where', 'while', 'been',
            'their', 'which', 'be', 'to', 'of', 'a', 'in', 'is', 'on', 'it'
        }

    def classify_evidence(self, text: str) -> EvidenceScore:
        """Classify evidence type and compute quality score"""
        text_lower = text.lower()

        # Detect evidence presence
        has_method = bool(EvidencePattern.METHOD_CUES.search(text_lower))
        has_result = bool(EvidencePattern.RESULT_CUES.search(text_lower))
        has_mechanism = bool(EvidencePattern.MECHANISM_CUES.search(text_lower))
        has_background = bool(EvidencePattern.BACKGROUND_CUES.search(text_lower))
        has_numeric = bool(EvidencePattern.NUMERIC_PATTERN.search(text))
        has_citations = bool(EvidencePattern.CITATION_PATTERN.search(text))
        hedge_count = len(EvidencePattern.HEDGE_CUES.findall(text_lower))

        # Determine evidence type based on combination
        evidence_type = self._determine_evidence_type(
            has_method, has_result, has_mechanism, has_background
        )

        # Compute component scores
        method_score = 0.5 if has_method else 0.0
        result_score = 0.5 if has_result else 0.0
        mechanism_score = 0.7 if has_mechanism else 0.0
        background_score = 0.3 if has_background else 0.0
        
        # Numeric data bonus
        if has_numeric:
            result_score = min(result_score + 0.2, 1.0)
            method_score = min(method_score + 0.15, 1.0)
        
        # Citation bonus
        if has_citations:
            mechanism_score = min(mechanism_score + 0.15, 1.0)

        # Hedge penalty
        hedge_penalty = min(hedge_count * 0.1, 0.4)

        # Base score by type
        base_scores = {
            EvidenceType.DIRECT: 0.85,
            EvidenceType.METHODOLOGICAL: 0.70,
            EvidenceType.CORRELATIONAL: 0.60,
            EvidenceType.THEORETICAL: 0.50,
            EvidenceType.ANECDOTAL: 0.30,
            EvidenceType.UNKNOWN: 0.20
        }
        base_score = base_scores.get(evidence_type, 0.20)

        # Compute final score with adjusted weights
        final_score = (
            base_score * 0.4 +
            method_score * 0.2 +
            result_score * 0.25 +
            mechanism_score * 0.15 +
            background_score * 0.05 +
            (0.1 if has_numeric else 0) -
            hedge_penalty
        )
        final_score = max(0.0, min(final_score, 1.0))

        # Confidence based on evidence richness
        confidence = (
            sum([
                has_method, has_result, has_mechanism,
                has_background, has_numeric, has_citations
            ]) / 6.0
        )

        return EvidenceScore(
            evidence_type=evidence_type,
            base_score=base_score,
            method_score=method_score,
            result_score=result_score,
            mechanism_score=mechanism_score,
            background_score=background_score,
            hedge_penalty=hedge_penalty,
            final_score=final_score,
            confidence=confidence,
            details={
                'has_method': has_method,
                'has_result': has_result,
                'has_mechanism': has_mechanism,
                'has_background': has_background,
                'has_numeric': has_numeric,
                'has_citations': has_citations,
                'hedge_count': hedge_count
            }
        )

    @staticmethod
    def _determine_evidence_type(
        has_method: bool,
        has_result: bool,
        has_mechanism: bool,
        has_background: bool
    ) -> EvidenceType:
        """Determine evidence type based on features"""
        evidence_count = sum([has_method, has_result, has_mechanism, has_background])

        if has_method and has_result and has_mechanism:
            return EvidenceType.DIRECT
        elif evidence_count >= 3:
            if has_method:
                return EvidenceType.METHODOLOGICAL
            else:
                return EvidenceType.THEORETICAL
        elif has_method and has_result:
            return EvidenceType.METHODOLOGICAL
        elif has_result and has_mechanism:
            return EvidenceType.CORRELATIONAL
        elif evidence_count == 1:
            if has_method:
                return EvidenceType.METHODOLOGICAL
            else:
                return EvidenceType.ANECDOTAL
        else:
            return EvidenceType.UNKNOWN

    def extract_keywords(self, text: str, max_keywords: int = 5) -> List[str]:
        """Extract key technical terms from evidence"""
        # Remove stopwords and short terms
        words = re.findall(r'\b\w+\b', text.lower())
        keywords = [
            w for w in words
            if len(w) > 3 and w not in self.stopwords
        ]

        # Count word frequency and return top keywords
        word_freq = Counter(keywords)
        return [kw for kw, _ in word_freq.most_common(max_keywords)]

    def get_quality_label(self, score: float) -> str:
        """Convert score to quality label"""
        if score >= 0.85:
            return "High"
        elif score >= 0.60:
            return "Medium"
        else:
            return "Low"
