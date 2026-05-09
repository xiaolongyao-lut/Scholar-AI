from __future__ import annotations

import logging
from collections import defaultdict
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from layers.p3_causal_engine import CausalChain
from models.p2_logic_models import ClassifiedConflict

logger = logging.getLogger("P3_ConsistencyValidator")


class ValidationPairResult(BaseModel):
    """单对因果链的一致性检验结果。"""

    pair_id: str
    chain_a_index: int
    chain_b_index: int
    chain_a: CausalChain
    chain_b: CausalChain
    shared_nodes: List[str] = Field(default_factory=list)
    shared_relations: List[str] = Field(default_factory=list)
    shared_edges: List[Tuple[str, str, str]] = Field(default_factory=list)
    common_prefix_length: int = 0
    consistency_score: float
    issue: str
    recommendation: str
    polarity_penalty: float = 0.0
    conflict_penalty: float = 0.0
    length_penalty: float = 0.0


class ConsistencySummary(BaseModel):
    """一致性检验汇总。"""

    chain_count: int
    pair_count: int
    passed_pair_count: int
    review_pair_count: int
    flagged_pair_count: int
    average_score: float
    minimum_score: float
    maximum_score: float
    overall_status: str


class ConsistencyReport(BaseModel):
    """一致性检验报告。"""

    summary: ConsistencySummary
    pair_results: List[ValidationPairResult] = Field(default_factory=list)


class ConsistencyValidator:
    """
    P3 能力 3: 一致性检验（Consistency Validation）

    作用：
    - 检查不同因果链之间是否在结构上和语义上保持一致
    - 对潜在冲突给出可解释的分值和建议
    - 在 DAG 导出前提供轻量的逻辑预检
    """

    def __init__(
        self,
        consistency_threshold: float = 0.5,
        review_threshold: float = 0.75,
        max_polarity_penalty: float = 0.24,
        max_conflict_penalty: float = 0.30,
    ) -> None:
        self.consistency_threshold = consistency_threshold
        self.review_threshold = review_threshold
        self.max_polarity_penalty = max_polarity_penalty
        self.max_conflict_penalty = max_conflict_penalty

    def validate(
        self,
        chains: List[CausalChain],
        conflicts: Optional[List[ClassifiedConflict]] = None,
    ) -> ConsistencyReport:
        """
        对输入的因果链进行两两一致性检验。

        Args:
            chains: 因果链列表
            conflicts: 已知冲突列表，可选

        Returns:
            ConsistencyReport: 包含 pairwise 结果与汇总信息
        """
        conflicts = conflicts or []
        pair_results: List[ValidationPairResult] = []

        if not chains:
            summary = ConsistencySummary(
                chain_count=0,
                pair_count=0,
                passed_pair_count=0,
                review_pair_count=0,
                flagged_pair_count=0,
                average_score=0.0,
                minimum_score=0.0,
                maximum_score=0.0,
                overall_status="EMPTY",
            )
            return ConsistencyReport(summary=summary, pair_results=[])

        for chain_a_index, chain_b_index in combinations(range(len(chains)), 2):
            result = self._compare_pair(
                chain_a_index=chain_a_index,
                chain_a=chains[chain_a_index],
                chain_b_index=chain_b_index,
                chain_b=chains[chain_b_index],
                conflicts=conflicts,
            )
            pair_results.append(result)

        if not pair_results:
            summary = ConsistencySummary(
                chain_count=len(chains),
                pair_count=0,
                passed_pair_count=0,
                review_pair_count=0,
                flagged_pair_count=0,
                average_score=1.0,
                minimum_score=1.0,
                maximum_score=1.0,
                overall_status="PASS",
            )
            return ConsistencyReport(summary=summary, pair_results=[])

        scores = [result.consistency_score for result in pair_results]
        passed_pair_count = sum(
            1 for result in pair_results if result.consistency_score >= self.review_threshold
        )
        review_pair_count = sum(
            1
            for result in pair_results
            if self.consistency_threshold <= result.consistency_score < self.review_threshold
        )
        flagged_pair_count = sum(
            1 for result in pair_results if result.consistency_score < self.consistency_threshold
        )

        if flagged_pair_count > 0:
            overall_status = "FAIL"
        elif review_pair_count > 0:
            overall_status = "REVIEW"
        else:
            overall_status = "PASS"

        summary = ConsistencySummary(
            chain_count=len(chains),
            pair_count=len(pair_results),
            passed_pair_count=passed_pair_count,
            review_pair_count=review_pair_count,
            flagged_pair_count=flagged_pair_count,
            average_score=round(sum(scores) / len(scores), 3),
            minimum_score=round(min(scores), 3),
            maximum_score=round(max(scores), 3),
            overall_status=overall_status,
        )
        return ConsistencyReport(summary=summary, pair_results=pair_results)

    def _compare_pair(
        self,
        chain_a_index: int,
        chain_a: CausalChain,
        chain_b_index: int,
        chain_b: CausalChain,
        conflicts: List[ClassifiedConflict],
    ) -> ValidationPairResult:
        chain_a_nodes = list(chain_a.nodes)
        chain_b_nodes = list(chain_b.nodes)
        chain_a_relations = [self._normalize_text(relation) for relation in chain_a.relations]
        chain_b_relations = [self._normalize_text(relation) for relation in chain_b.relations]

        shared_nodes = self._ordered_intersection(chain_a_nodes, chain_b_nodes)
        shared_relations = self._ordered_intersection(chain_a_relations, chain_b_relations)
        shared_edges = self._ordered_intersection(
            self._chain_edges(chain_a),
            self._chain_edges(chain_b),
        )

        common_prefix_length = self._longest_common_prefix(chain_a_nodes, chain_b_nodes)
        node_overlap = self._overlap_ratio(chain_a_nodes, chain_b_nodes)
        edge_overlap = self._overlap_ratio(
            self._chain_edges(chain_a),
            self._chain_edges(chain_b),
        )
        relation_alignment = self._relation_alignment(chain_a_relations, chain_b_relations)
        terminal_match = 1.0 if self._normalize_text(chain_a_nodes[-1]) == self._normalize_text(chain_b_nodes[-1]) else 0.0

        structure_score = (
            0.35 * self._prefix_score(common_prefix_length, chain_a_nodes, chain_b_nodes)
            + 0.25 * node_overlap
            + 0.20 * edge_overlap
            + 0.10 * relation_alignment
            + 0.10 * terminal_match
        )

        polarity_penalty = self._relation_polarity_penalty(chain_a_relations, chain_b_relations)
        conflict_penalty = self._conflict_penalty(chain_a, chain_b, conflicts)
        length_penalty = self._length_penalty(chain_a_nodes, chain_b_nodes)
        total_penalty = min(
            self.max_polarity_penalty + self.max_conflict_penalty + 0.15,
            polarity_penalty + conflict_penalty + length_penalty,
        )
        consistency_score = round(max(0.0, min(1.0, structure_score - total_penalty)), 3)

        issue, recommendation = self._classify_result(
            consistency_score=consistency_score,
            has_conflict_penalty=conflict_penalty > 0.0,
            terminal_match=bool(terminal_match),
        )

        return ValidationPairResult(
            pair_id=f"chain_{chain_a_index}__chain_{chain_b_index}",
            chain_a_index=chain_a_index,
            chain_b_index=chain_b_index,
            chain_a=chain_a,
            chain_b=chain_b,
            shared_nodes=shared_nodes,
            shared_relations=shared_relations,
            shared_edges=shared_edges,
            common_prefix_length=common_prefix_length,
            consistency_score=consistency_score,
            issue=issue,
            recommendation=recommendation,
            polarity_penalty=round(polarity_penalty, 3),
            conflict_penalty=round(conflict_penalty, 3),
            length_penalty=round(length_penalty, 3),
        )

    def _classify_result(
        self,
        consistency_score: float,
        has_conflict_penalty: bool,
        terminal_match: bool,
    ) -> Tuple[str, str]:
        if consistency_score >= self.review_threshold:
            return (
                "CONSISTENT_PATHS",
                "两条因果链结构高度一致，可继续纳入推演 DAG。",
            )

        if consistency_score >= self.consistency_threshold:
            if terminal_match:
                return (
                    "PARTIAL_ALIGNMENT",
                    "两条因果链大体一致，但中间环节仍建议补充条件说明。",
                )
            return (
                "DIVERGENT_PATHS",
                "两条因果链存在分歧，建议补充边界条件或中介机制。",
            )

        if has_conflict_penalty:
            return (
                "CONFLICTING_PATHS",
                "检测到冲突链路，建议结合原始证据进行人工审查。",
            )
        return (
            "CONFLICTING_PATHS",
            "因果链差异过大，建议人工复核后再进入 DAG 导出。",
        )

    def _normalize_text(self, value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    def _chain_edges(self, chain: CausalChain) -> List[Tuple[str, str, str]]:
        edges: List[Tuple[str, str, str]] = []
        for index in range(max(0, len(chain.nodes) - 1)):
            source = self._normalize_text(chain.nodes[index])
            relation = self._normalize_text(chain.relations[index]) if index < len(chain.relations) else ""
            target = self._normalize_text(chain.nodes[index + 1])
            edges.append((source, relation, target))
        return edges

    def _ordered_intersection(self, left: List[Any], right: List[Any]) -> List[Any]:
        right_set = set(right)
        seen: set[Any] = set()
        result: List[Any] = []
        for item in left:
            if item in right_set and item not in seen:
                result.append(item)
                seen.add(item)
        return result

    def _overlap_ratio(self, left: List[Any], right: List[Any]) -> float:
        left_set = set(left)
        right_set = set(right)
        union_size = len(left_set | right_set)
        if union_size == 0:
            return 1.0
        return len(left_set & right_set) / union_size

    def _longest_common_prefix(self, left: List[str], right: List[str]) -> int:
        prefix_length = 0
        for left_item, right_item in zip(left, right):
            if self._normalize_text(left_item) != self._normalize_text(right_item):
                break
            prefix_length += 1
        return prefix_length

    def _prefix_score(self, prefix_length: int, left: List[str], right: List[str]) -> float:
        if not left or not right:
            return 0.0
        denominator = min(len(left), len(right))
        if denominator <= 0:
            return 0.0
        return prefix_length / denominator

    def _relation_alignment(self, left_relations: List[str], right_relations: List[str]) -> float:
        comparable_count = min(len(left_relations), len(right_relations))
        if comparable_count == 0:
            return 1.0
        matches = sum(
            1
            for left_relation, right_relation in zip(left_relations, right_relations)
            if left_relation == right_relation
        )
        return matches / comparable_count

    def _relation_polarity_penalty(self, left_relations: List[str], right_relations: List[str]) -> float:
        comparable_count = min(len(left_relations), len(right_relations))
        if comparable_count == 0:
            return 0.0

        penalty = 0.0
        for left_relation, right_relation in zip(left_relations, right_relations):
            left_polarity = self._relation_polarity(left_relation)
            right_polarity = self._relation_polarity(right_relation)
            if left_polarity and right_polarity and left_polarity != right_polarity:
                penalty += 0.12

        return min(penalty, self.max_polarity_penalty)

    def _relation_polarity(self, relation: str) -> int:
        positive_markers = (
            "increase",
            "improve",
            "enhance",
            "promote",
            "raise",
            "boost",
            "accelerate",
            "increase in",
            "higher",
            "stronger",
        )
        negative_markers = (
            "decrease",
            "reduce",
            "lower",
            "suppress",
            "inhibit",
            "diminish",
            "decline",
            "weaken",
            "drop",
            "reduce in",
        )
        normalized = self._normalize_text(relation)
        if normalized.startswith("not ") or normalized.startswith("no "):
            return -1
        if any(marker in normalized for marker in positive_markers):
            return 1
        if any(marker in normalized for marker in negative_markers):
            return -1
        return 0

    def _length_penalty(self, left: List[str], right: List[str]) -> float:
        if not left or not right:
            return 0.0
        difference = abs(len(left) - len(right))
        return min(0.15, difference * 0.03)

    def _conflict_penalty(
        self,
        chain_a: CausalChain,
        chain_b: CausalChain,
        conflicts: List[ClassifiedConflict],
    ) -> float:
        if not conflicts:
            return 0.0

        chain_a_triplets = set(self._chain_edges(chain_a))
        chain_b_triplets = set(self._chain_edges(chain_b))
        penalty = 0.0

        grouped_conflicts: Dict[Tuple[str, str], set[str]] = defaultdict(set)
        for conflict in conflicts:
            for claim in conflict.claims_involved:
                grouped_conflicts[
                    (
                        self._normalize_text(claim.subject),
                        self._normalize_text(claim.predicate),
                    )
                ].add(self._normalize_text(claim.object))

        for (subject, predicate), objects in grouped_conflicts.items():
            if len(objects) < 2:
                continue

            chain_a_objects = {target for (source, relation, target) in chain_a_triplets if source == subject and relation == predicate}
            chain_b_objects = {target for (source, relation, target) in chain_b_triplets if source == subject and relation == predicate}

            if chain_a_objects and chain_b_objects and chain_a_objects != chain_b_objects:
                penalty += 0.18

        return min(penalty, self.max_conflict_penalty)
