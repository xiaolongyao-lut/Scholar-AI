import logging
import numpy as np
from collections import defaultdict
from typing import List, Dict, Any, Tuple
from models.p2_logic_models import Claim
from pydantic import BaseModel

logger = logging.getLogger("P3_Triangulator")

class EvidenceSet(BaseModel):
    """三元组对照证据集"""
    triplet: Tuple[str, str, str]
    supporting_claims: List[Claim]
    total_strength: float
    avg_strength: float
    consensus_level: str  # STRONG | MODERATE | WEAK
    literature_summary: str

class EvidenceTriangulator:
    """
    P3 能力 1: 多源证据对照 (Evidence Triangulation)
    """

    def triangulate(self, claims: List[Claim]) -> List[EvidenceSet]:
        """
        对提取出的声明进行多源对齐与对照
        """
        if not claims:
            return []

        # 1. 按 (Subject, Predicate, Object) 聚类
        # 注意：此处应理想地使用 P2 的 canonical 对齐逻辑，此处简化演示
        triplets = defaultdict(list)
        for c in claims:
            key = (c.subject.strip().lower(), c.predicate.strip().lower(), c.object.strip().lower())
            triplets[key].append(c)

        # 2. 计算证据强度与共识度
        evidence_sets = []
        for (s, p, o), claims_list in triplets.items():
            strength_scores = []
            for c in claims_list:
                # 权重算法: IF(40%) + Citations(30%) + Recency(30%)
                recency_score = max(0, (c.source.year - 2015) / 10.0) # 2025 为 1.0
                citation_score = min(c.source.citation_count / 50.0, 1.0)
                
                score = (c.source.impact_factor * 0.4) + (citation_score * 0.3) + (recency_score * 0.3)
                strength_scores.append(score)

            total_strength = sum(strength_scores)
            avg_strength = total_strength / len(claims_list)
            
            # 共识判定
            if len(claims_list) >= 3:
                consensus = "STRONG"
            elif len(claims_list) >= 2:
                consensus = "MODERATE"
            else:
                consensus = "WEAK"

            titles = [f"{c.source.title} ({c.source.year})" for c in claims_list]
            
            evidence_sets.append(EvidenceSet(
                triplet=(s, p, o),
                supporting_claims=claims_list,
                total_strength=round(total_strength, 2),
                avg_strength=round(avg_strength, 2),
                consensus_level=consensus,
                literature_summary="; ".join(titles)
            ))

        return evidence_sets
