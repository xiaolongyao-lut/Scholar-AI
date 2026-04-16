import logging
import datetime
from typing import List, Dict, Any, Tuple
from models.p2_logic_models import Claim, ClassifiedConflict, ConflictType
from layers.p3_resolver import ConflictResolver, Resolution

logger = logging.getLogger("P3_DynamicUpdater")

class DynamicUpdater:
    """
    P3 能力 7: 动态增量更新与知识淘汰
    """

    def __init__(self, stale_year: int = 5, resolver: ConflictResolver = None):
        self.stale_year = stale_year
        self.current_year = datetime.datetime.now().year
        self.resolver = resolver or ConflictResolver()

    def filter_stale_claims(self, claims: List[Claim]) -> List[Claim]:
        """
        根据年份淘汰过期知识
        """
        valid_claims = []
        for c in claims:
            if self.current_year - c.source.year > self.stale_year:
                logger.info(f"淘汰过期声明: {c.claim_id} ({c.source.year}年)")
                continue
            valid_claims.append(c)
        return valid_claims

    def _get_claim_key(self, c: Claim) -> Tuple[str, str, str]:
        """获取声明的逻辑键 (S, P, O)"""
        return (c.subject.strip().lower(), c.predicate.strip().lower(), c.object.strip().lower())

    def _detect_conflicts(self, base_claims: List[Claim], new_claims: List[Claim]) -> List[ClassifiedConflict]:
        """
        探测新旧证据间的逻辑冲突
        """
        conflicts = []
        # 构建基础库的索引: (Subject, Object) -> List[Claim]
        base_map: Dict[Tuple[str, str], List[Claim]] = {}
        for c in base_claims:
            key = (c.subject.strip().lower(), c.object.strip().lower())
            base_map.setdefault(key, []).append(c)

        # 检查新进入的声明
        for nc in new_claims:
            key = (nc.subject.strip().lower(), nc.object.strip().lower())
            if key in base_map:
                for bc in base_map[key]:
                    # 如果 Predicate 不同，构成直接冲突
                    if bc.predicate.strip().lower() != nc.predicate.strip().lower():
                        conflicts.append(ClassifiedConflict(
                            conflict_id=f"upd_conflict_{nc.claim_id}_{bc.claim_id}",
                            type=ConflictType.DIRECT_CONFLICT,
                            claims_involved=[bc, nc],
                            evolution_type="UNKNOWN",
                            interpretation="动态更新中发现新旧证据谓词不一致",
                            authority_summary="待评估"
                        ))
                    # 即使 Predicate 相同，如果来自不同来源，也可能需要择优或合并 (在此视为潜在演化)
                    else:
                        conflicts.append(ClassifiedConflict(
                            conflict_id=f"upd_update_{nc.claim_id}_{bc.claim_id}",
                            type=ConflictType.NO_CONFLICT, # 语义相同，但在更新流中视为权衡点
                            claims_involved=[bc, nc],
                            evolution_type="EVOLUTION",
                            interpretation="动态更新中发现针对同一关系的重叠声明",
                            authority_summary="待评估"
                        ))
        return conflicts

    def update_knowledge_base(self, existing_claims: List[Claim], new_claims: List[Claim]) -> List[Claim]:
        """
        增量更新逻辑：执行逻辑消解并合并
        """
        # 1. 过滤旧数据中的过期项
        active_claims = self.filter_stale_claims(existing_claims)
        
        # 2. 冲突检测与消解
        conflicts = self._detect_conflicts(active_claims, new_claims)
        if not conflicts:
            return active_claims + new_claims

        resolutions = self.resolver.resolve(conflicts)
        
        # 3. 根据建议执行择优过滤
        # 记录需要移除的 Claim ID
        to_remove_ids = set()
        for res in resolutions:
            # 如果消解建议了首选声明 (primary_claim)
            if res.primary_claim:
                # 找到被丢弃的声明 (在涉及该冲突的列表里但不是 primary 的那些)
                conflict_item = next((c for c in conflicts if c.conflict_id == res.conflict_id), None)
                if conflict_item:
                    for c in conflict_item.claims_involved:
                        if c.claim_id != res.primary_claim.claim_id:
                            to_remove_ids.add(c.claim_id)
                            logger.info(f"动态更新消解: [移除] {c.claim_id} [采信] {res.primary_claim.claim_id} 原因: {res.type}")

        # 4. 构建最终结果
        final_pool = []
        all_potential = active_claims + new_claims
        seen_ids = set()
        
        for c in all_potential:
            if c.claim_id in to_remove_ids:
                continue
            if c.claim_id not in seen_ids:
                final_pool.append(c)
                seen_ids.add(c.claim_id)

        return final_pool
