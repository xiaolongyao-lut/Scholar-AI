import asyncio
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from models.p2_logic_models import (
    Claim, ClassifiedConflict, ReasoningChain, ReasoningStep, 
    SourceMeta, ConflictResult
)
from layers.p2_claim_extractor import ClaimExtractor
from layers.p2_conflict_detector import ConflictDetector

logger = logging.getLogger("P2_LogicEngine")


def json_friendly_dict(d: Dict) -> str:
    """将字典转为 JSON 字符串（用于日志）"""
    import json
    return json.dumps(d, ensure_ascii=False)

class CrossRefProvider:
    """
    优化 3 (新增): CrossRef 元数据提供器
    用于在高级冲突时查询权威元数据，提升权威性评估准确度
    """
    
    BASE_URL = "https://api.crossref.org/works"
    COST_PER_QUERY = 0.05  # CrossRef 免费 API，但计算成本
    
    @staticmethod
    def enrich_metadata(doi: str) -> Optional[Dict]:
        """
        查询 CrossRef 获取权威元数据
        """
        try:
            response = requests.get(
                f"{CrossRefProvider.BASE_URL}/{doi}?mailto=researcher@example.com",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()['message']
                return {
                    "authors": [f"{a.get('given', '')} {a.get('family', '')}" 
                               for a in data.get('author', [])[:5]],
                    "corresponding_author": data.get('author', [{}])[0].get('family'),
                    "publisher": data.get('publisher', 'Unknown'),
                    "citation_count": data.get('is-referenced-by-count', 0),
                    "published_date": data.get('published', {}).get('date-parts', [[2024]])[0],
                    "update_date": datetime.now().isoformat()
                }
        except Exception as e:
            logger.warning(f"CrossRef 查询失败 (DOI: {doi}): {e}")
        return None


class CostTracker:
    """成本跟踪与预算管理"""
    
    def __init__(self, budget_limit: float = 2.0):
        self.budget_limit = budget_limit
        self.total_cost = 0.0
        self.calls = []
    
    def track(self, service: str, cost: float):
        """记录一次 API 调用"""
        self.total_cost += cost
        self.calls.append({"service": service, "cost": cost, "time": datetime.now()})
        
        if self.total_cost > self.budget_limit:
            logger.warning(f"成本预警: 已花费 ${self.total_cost:.2f}，接近上限 ${self.budget_limit:.2f}")
    
    def get_summary(self) -> Dict:
        """获取成本统计"""
        return {
            "total_cost": round(self.total_cost, 2),
            "call_count": len(self.calls),
            "budget_limit": self.budget_limit,
            "remaining": round(self.budget_limit - self.total_cost, 2)
        }


class LogicEngine:
    """
    P2 核心组件：逻辑推演引擎
    对齐计划：权威性评估 + 推演链合成 + API 富化
    优化: 添加分级调用策略，仅在高级冲突时激活 API
    """

    def __init__(self, llm_client: Optional[Any] = None, cost_budget: float = 2.0):
        self.extractor = ClaimExtractor(llm_client)
        self.detector = ConflictDetector(llm_client)
        self.llm_client = llm_client
        self.cost_tracker = CostTracker(budget_limit=cost_budget)

    async def reason(self, query: str, retrieved_chunks: List[Dict[str, Any]]) -> ReasoningChain:
        """
        全流程推演入口 (改进版: 包含成本跟踪)
        """
        chain = ReasoningChain(
            chain_id=f"RE-{asyncio.get_event_loop().time():.0f}",
            query=query,
            steps=[]
        )

        # 1. 声明提取
        extraction_step = ReasoningStep(
            step_id=1, type="EXTRACTION", description="从检索到的片段中提取结构化声明"
        )
        all_claims = []
        for chunk in retrieved_chunks:
            source = self._parse_source_meta(chunk)
            claims = await self.extractor.extract_from_chunk(chunk.get('text', ''), source)
            all_claims.extend(claims)
        
        extraction_step.outputs = [f"识别到 {len(all_claims)} 条声明（平均置信度 {sum(c.confidence for c in all_claims)/len(all_claims) if all_claims else 0:.2f}）"]
        chain.steps.append(extraction_step)

        # 2. 冲突检测与分类分级
        conflict_step = ReasoningStep(
            step_id=2, type="CONFLICT", description="执行跨文逻辑审计与冲突检测"
        )
        conflicts = await self._detect_all_conflicts(all_claims)
        chain.conflicts = conflicts
        conflict_step.outputs = [f"检测到 {len(conflicts)} 处逻辑分歧"]
        chain.steps.append(conflict_step)

        # 3. 最终综合与权威性评估
        chain.final_conclusion = self._synthesize_conclusion(all_claims, conflicts)
        chain.overall_confidence = 0.85 # 示例值
        
        # 优化 3: 添加成本报告
        chain.cost_summary = self.cost_tracker.get_summary()
        logger.info(f"推演完成 - {json_friendly_dict(chain.cost_summary)}")

        return chain

    def _parse_source_meta(self, chunk: Dict[str, Any]) -> SourceMeta:
        """
        从片段元数据中提取 SourceMeta (P2 决策 3)
        """
        meta = chunk.get('metadata', {})
        return SourceMeta(
            doc_id=chunk.get('id', 'unknown'),
            title=meta.get('title', 'Untitled Document'),
            year=meta.get('year', 2024),
            journal=meta.get('journal', 'General Welding Research'),
            impact_factor=meta.get('impact_factor', 1.0),
            citation_count=meta.get('citation_count', 0)
        )

    async def _detect_all_conflicts(self, claims: List[Claim]) -> List[ClassifiedConflict]:
        """
        深度冲突审核 (N^2 简化版)
        """
        results = []
        # 按 Subject 分组以降低计算复杂度
        from collections import defaultdict
        buckets = defaultdict(list)
        for c in claims:
            buckets[c.subject.lower()].append(c)

        for subject, sub_claims in buckets.items():
            if len(sub_claims) < 2: continue
            
            for i in range(len(sub_claims)):
                for j in range(i + 1, len(sub_claims)):
                    res = await self.detector.detect_conflict(sub_claims[i], sub_claims[j])
                    if res:
                        results.append(self._classify_conflict(res))
        return results

    def _classify_conflict(self, res: ConflictResult) -> ClassifiedConflict:
        """
        对冲突执行权威性评估与解读 (P2 决策 2) + 优化 3 (API 富化)
        
        分级调用策略:
          低级冲突 (severity < 3): 使用本地数据
          高级冲突 (severity >= 3): 调用 CrossRef API 获取权威元数据
        """
        claims = res.claims_involved
        
        # 优化 3: 分级调用 CrossRef API
        if res.severity_level >= 3 and self.cost_tracker.total_cost < 1.8:
            # 高级冲突且在预算内，调用 API 获取最新元数据
            for c in claims:
                if c.source.doi:
                    self.cost_tracker.track('crossref', CrossRefProvider.COST_PER_QUERY)
                    enriched = CrossRefProvider.enrich_metadata(c.source.doi)
                    if enriched:
                        c.source.citation_count = enriched.get('citation_count', c.source.citation_count)
                        logger.info(f"API 富化: {c.source.doc_id} 被引数更新为 {c.source.citation_count}")
        
        # 计算权威性得分 (IF * 0.4 + Citations * 0.3 + Year * 0.3)
        auth_score = 0.0
        details = []
        for c in claims:
            s = c.source
            # 改进的权威性评分算法
            if_score = s.impact_factor * 0.4
            citations_score = min(s.citation_count / 50.0, 5.0) * 0.3  # 标准化被引数
            year_score = (2024 - min(s.year, 2024)) / 10.0 * 0.3  # 时间权重
            
            score = if_score + citations_score + year_score
            auth_score += score
            details.append(f"{s.title}(Y:{s.year}, IF:{s.impact_factor}, Cite:{s.citation_count})")

        # 时间演变判定
        years = sorted([c.source.year for c in claims])
        evolution = "STABLE"
        if len(years) >= 2 and years[-1] - years[0] > 2:
            evolution = "EVOLUTION"

        # 生成分类结果
        classified = ClassifiedConflict(
            conflict_id=f"CF-{hash(res.explanation)%10000}",
            type=res.conflict_type,
            severity_level=res.severity_level,
            claims_involved=claims,
            evolution_type=evolution,
            interpretation=f"在以下证据中检测到{res.conflict_type.value}: {res.explanation}",
            authority_score=round(auth_score / len(claims), 2),
            authority_summary=f"对比证据: {'; '.join(details)}",
            resolution_path=["建议核实最近 2 年的相关综述", "在相同条件下对比量化偏差", f"检测成本: ${self.cost_tracker.total_cost:.2f}"]
        )
        
        return classified

    def _synthesize_conclusion(self, claims: List[Claim], conflicts: List[ClassifiedConflict]) -> str:
        """核心结论合成逻辑"""
        if not conflicts:
            return "各文献论点一致，结论稳健。"
        
        high_severity = [c for c in conflicts if c.severity_level >= 3]
        if high_severity:
            return f"注意: 检测到 {len(high_severity)} 处严重学术分歧，论证链存在结构性风险。"
        
        return "论证过程伴随中低度分歧，结论在特定条件下成立。"
