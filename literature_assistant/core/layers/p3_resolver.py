import logging
from typing import List, Dict, Any, Optional
from models.p2_logic_models import Claim, ClassifiedConflict
from pydantic import BaseModel

logger = logging.getLogger("P3_ConflictResolver")

class Resolution(BaseModel):
    """消解方案模型"""
    conflict_id: str
    type: str  # TEMPORAL_EVOLUTION | CONDITIONAL_DIFFERENCE | EVIDENTIARY_HIERARCHY
    primary_claim: Optional[Claim] = None
    explanation: str
    recommendation: str

class ConflictResolver:
    """
    P3 能力 4: 冲突消解 (Conflict Resolution)
    """

    def resolve(self, conflicts: List[ClassifiedConflict]) -> List[Resolution]:
        """
        对已识别的冲突执行消解算法
        """
        resolutions = []
        for conflict in conflicts:
            # 策略优先级：1. 时间演变 -> 2. 证据权重 -> 3. 条件差异
            
            # A. 时间演变判定
            years = sorted([c.source.year for c in conflict.claims_involved])
            if years[-1] - years[0] >= 3:
                newest_claim = next(c for c in conflict.claims_involved if c.source.year == years[-1])
                resolutions.append(Resolution(
                    conflict_id=conflict.conflict_id,
                    type="TEMPORAL_EVOLUTION",
                    primary_claim=newest_claim,
                    explanation=f"检测到明显的研究观点演变 (跨度 {years[-1]-years[0]} 年)。",
                    recommendation=f"建议优先采信 {years[-1]} 年的最新研究结论。"
                ))
                continue

            # B. 证据权重判定 (Authority)
            # 使用 P2 已计算的 authority_score (虽然 P3 也有自己的计算逻辑，此处保持一致性)
            best_claim = max(conflict.claims_involved, 
                             key=lambda c: (c.source.impact_factor * 0.4 + c.source.citation_count * 0.3))
            
            resolutions.append(Resolution(
                conflict_id=conflict.conflict_id,
                type="EVIDENTIARY_HIERARCHY",
                primary_claim=best_claim,
                explanation=f"基于来源权威性的判定结论。",
                recommendation=f"文献 '{best_claim.source.title}' (IF:{best_claim.source.impact_factor}) 具有更高可信度。"
            ))

        return resolutions
