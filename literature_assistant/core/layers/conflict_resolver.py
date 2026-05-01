import re
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
import numpy as np

logger = logging.getLogger("ConflictResolver")

@dataclass
class ConflictValue:
    source_id: str
    value: Any
    confidence: float
    param_name: str

@dataclass
class ResolutionResult:
    parameter: str
    consensus_value: Any
    confidence_score: float
    decision: str # auto_accept | needs_review | undecidable
    supporting_sources: List[str]
    explanation: str

class ConflictResolver:
    """
    P2: 自动冲突修复器。
    通过聚类与加权投票机制，将多篇文献中的数值冲突转化为单一共识结论。
    """

    def resolve(self, parameter: str, conflicts: List[ConflictValue]) -> ResolutionResult:
        if not conflicts:
            return None
        
        if len(conflicts) == 1:
            return ResolutionResult(
                parameter=parameter,
                consensus_value=conflicts[0].value,
                confidence_score=conflicts[0].confidence,
                decision="auto_accept",
                supporting_sources=[conflicts[0].source_id],
                explanation="单一来源，直接采用。"
            )

        # 1. 检测参数类型
        is_numeric, numeric_vals = self._extract_numbers(conflicts)
        
        if is_numeric:
            return self._solve_numeric_conflict(parameter, conflicts, numeric_vals)
        else:
            return self._solve_categorical_conflict(parameter, conflicts)

    def _extract_numbers(self, conflicts: List[ConflictValue]) -> Tuple[bool, List[float]]:
        nums = []
        for c in conflicts:
            match = re.search(r"[-+]?\d*\.\d+|\d+", str(c.value))
            if match:
                nums.append(float(match.group()))
            else:
                return False, []
        return True, nums

    def _solve_numeric_conflict(self, parameter: str, conflicts: List[ConflictValue], nums: List[float]) -> ResolutionResult:
        # 简单聚类：相对距离驱动 (5% 容差)
        clusters = []
        vals_sorted = sorted(zip(nums, conflicts), key=lambda x: x[0])
        
        if not vals_sorted:
            return self._solve_categorical_conflict(parameter, conflicts)

        # 聚类逻辑 (单向贪婪聚类)
        current_cluster = [vals_sorted[0]]
        for i in range(1, len(vals_sorted)):
            prev_val = vals_sorted[i-1][0]
            curr_val = vals_sorted[i][0]
            # 相对误差 < 5% 视为同一群
            if abs(curr_val - prev_val) / (max(abs(prev_val), 1e-6)) < 0.05:
                current_cluster.append(vals_sorted[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [vals_sorted[i]]
        clusters.append(current_cluster)

        # 选出样本量最大的群进行加权投票
        main_cluster = max(clusters, key=len)
        weights = [item[1].confidence for item in main_cluster]
        values = [item[0] for item in main_cluster]
        
        weighted_avg = np.average(values, weights=weights)
        total_conf = np.mean(weights) * (len(main_cluster) / len(conflicts))
        
        # 决策
        decision = "needs_review"
        if total_conf > 0.85 and len(main_cluster) >= 2:
            decision = "auto_accept"
        elif total_conf < 0.6:
            decision = "undecidable"

        return ResolutionResult(
            parameter=parameter,
            consensus_value=round(weighted_avg, 2),
            confidence_score=round(total_conf, 2),
            decision=decision,
            supporting_sources=[item[1].source_id for item in main_cluster],
            explanation=f"基于 {len(main_cluster)} 篇文献的共识，加权均值为 {weighted_avg:.2f}。"
        )

    def _solve_categorical_conflict(self, parameter: str, conflicts: List[ConflictValue]) -> ResolutionResult:
        # 分类参数使用加权众数
        counts = {}
        for c in conflicts:
            counts[c.value] = counts.get(c.value, 0) + c.confidence
            
        best_val = max(counts, key=counts.get)
        total_weight = sum(counts.values())
        winning_weight = counts[best_val]
        
        conf_score = winning_weight / total_weight
        
        return ResolutionResult(
            parameter=parameter,
            consensus_value=best_val,
            confidence_score=round(conf_score, 2),
            decision="auto_accept" if conf_score > 0.7 else "needs_review",
            supporting_sources=[c.source_id for c in conflicts if c.value == best_val],
            explanation=f"分类共识：'{best_val}' 获得了最高加权票数。"
        )
