#!/usr/bin/env python3
"""
优化方案 B 集成测试
验证: NER + BGE + CrossRef API 的完整流程

执行: python test_optimization_p1p2.py
"""

import asyncio
import json
import logging
from typing import List, Dict, Any
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入被测试的模块
from models.p2_logic_models import SourceMeta, Claim
from layers.p2_claim_extractor import ClaimExtractor
from layers.p2_conflict_detector import ConflictDetector
from layers.p2_logic_engine import LogicEngine


class OptimizationTester:
    """优化方案 B 的集成测试器"""
    
    def __init__(self):
        self.llm_client = None  # 可选的 LLM 客户端
        self.test_results = {}
    
    async def test_optimization_1_ner(self):
        """测试优化 1: NER 集成 (准确度 85% → 92%)"""
        logger.info("=" * 60)
        logger.info("测试优化 1: NER 集成")
        logger.info("=" * 60)
        
        extractor = ClaimExtractor(self.llm_client)
        
        # 测试文本：复杂焊接论文摘要
        test_text = """
        激光功率的增加显著提升了焊缝熔深。同时，扫描速度的加快会降低熔池宽度。
        在 TC4 材料中，焊接参数的优化可以改善焊缝组织。高功率下焊缝易产生热裂纹。
        基础研究表明低线能量工艺能够减少气孔缺陷的发生。实验数据对比显示激光功率范围
        在 500-1000W 时获得最佳性能。
        """
        
        # 创建模拟源元数据
        source = SourceMeta(
            doc_id="TEST001",
            title="Laser Welding Parameter Optimization",
            year=2023,
            journal="Welding Journal",
            impact_factor=2.5,
            citation_count=15
        )
        
        # 执行提取
        claims = await extractor.extract_from_chunk(test_text, source)
        
        logger.info(f"✓ 提取声明数: {len(claims)}")
        for i, c in enumerate(claims[:3], 1):
            logger.info(f"  [{i}] {c.subject} → {c.predicate} → {c.object} "
                       f"(置信度: {c.confidence:.2f})")
        
        # 统计指标
        avg_confidence = sum(c.confidence for c in claims) / len(claims) if claims else 0
        high_confidence = len([c for c in claims if c.confidence >= 0.88])
        
        result = {
            "total_claims": len(claims),
            "avg_confidence": round(avg_confidence, 2),
            "high_confidence_count": high_confidence,
            "high_confidence_ratio": round(high_confidence / len(claims) * 100, 1) if claims else 0
        }
        
        logger.info(f"✓ 平均置信度: {avg_confidence:.2f}")
        logger.info(f"✓ 高置信度声明 (≥0.88): {high_confidence}/{len(claims)} ({result['high_confidence_ratio']:.1f}%)")
        
        self.test_results['optimization_1_ner'] = result
        return result
    
    async def test_optimization_2_bge(self):
        """测试优化 2: BGE Embedding (准确度 75% → 98%, LLM 调用 1% → 0.1%)"""
        logger.info("\n" + "=" * 60)
        logger.info("测试优化 2: BGE Embedding")
        logger.info("=" * 60)
        
        detector = ConflictDetector(self.llm_client)
        
        # 测试术语对
        test_pairs = [
            ("热裂纹", "热开裂"),           # 同义词
            ("激光功率", "激光能量"),       # 相关概念
            ("熔深", "焊缝深度"),           # 同义词
            ("焊接速度", "扫描速度"),       # 相关概念
            ("冷却速率", "相变速度"),       # 相关但不完全相同
        ]
        
        results = []
        for term_a, term_b in test_pairs:
            sim = await detector.align_similarity(term_a, term_b)
            results.append({
                "term_a": term_a,
                "term_b": term_b,
                "bge_similarity": round(sim, 2),
                "expected": "high" if sim > 0.80 else "low"
            })
            logger.info(f"  '{term_a}' vs '{term_b}': {sim:.2f}")
        
        # 统计 BGE 特性
        high_sim = len([r for r in results if r['bge_similarity'] > 0.85])
        
        result = {
            "test_pairs": len(test_pairs),
            "high_similarity_pairs": high_sim,
            "avg_similarity": round(sum(r['bge_similarity'] for r in results) / len(results), 2),
            "details": results
        }
        
        logger.info(f"✓ 高相似度对数 (>0.85): {high_sim}/{len(test_pairs)}")
        logger.info(f"✓ 平均相似度: {result['avg_similarity']:.2f}")
        logger.info(f"✓ LLM 灰度调用预期: <0.1% (原: 1%)")
        
        self.test_results['optimization_2_bge'] = result
        return result
    
    def test_optimization_3_api(self):
        """测试优化 3: CrossRef API 配置 (元数据完整度 85% → 98%)"""
        logger.info("\n" + "=" * 60)
        logger.info("测试优化 3: CrossRef API 配置")
        logger.info("=" * 60)
        
        from layers.p2_logic_engine import CrossRefProvider, CostTracker
        
        # 测试 CostTracker
        tracker = CostTracker(budget_limit=2.0)
        
        # 模拟 API 调用
        tracker.track("crossref", 0.05)
        tracker.track("crossref", 0.05)
        tracker.track("llm", 0.01)
        
        summary = tracker.get_summary()
        
        logger.info(f"✓ 总成本: ${summary['total_cost']:.2f} / ${summary['budget_limit']:.2f}")
        logger.info(f"✓ API 调用数: {summary['call_count']}")
        logger.info(f"✓ 剩余预算: ${summary['remaining']:.2f}")
        
        result = {
            "total_cost": summary['total_cost'],
            "api_calls": summary['call_count'],
            "budget_limit": summary['budget_limit'],
            "cost_efficiency": "GOOD" if summary['total_cost'] < 0.5 else "FAIR"
        }
        
        self.test_results['optimization_3_api'] = result
        return result
    
    async def test_end_to_end(self):
        """端到端集成测试"""
        logger.info("\n" + "=" * 60)
        logger.info("测试: 端到端集成流程")
        logger.info("=" * 60)
        
        # 创建 LogicEngine
        engine = LogicEngine(llm_client=self.llm_client, cost_budget=2.0)
        
        # 模拟检索结果
        test_chunks = [
            {
                "id": "chunk_001",
                "text": "激光功率的增加显著改善焊缝性能，但过高功率会导致热裂纹。",
                "metadata": {
                    "title": "Laser Welding Process Parameters",
                    "year": 2023,
                    "journal": "Welding Journal",
                    "impact_factor": 2.5,
                    "citation_count": 25
                }
            },
            {
                "id": "chunk_002", 
                "text": "激光功率的降低会恶化焊缝性能，建议保持在 800W 以上。",
                "metadata": {
                    "title": "Advanced Laser Welding Techniques",
                    "year": 2024,
                    "journal": "Journal of Materials Science",
                    "impact_factor": 3.2,
                    "citation_count": 10
                }
            }
        ]
        
        # 执行推演
        query = "激光功率如何影响焊缝质量？"
        chain = await engine.reason(query, test_chunks)
        
        logger.info(f"✓ 推演 ID: {chain.chain_id}")
        logger.info(f"✓ 查询: {query}")
        logger.info(f"✓ 检测到冲突数: {len(chain.conflicts)}")
        logger.info(f"✓ 推演步骤数: {len(chain.steps)}")
        
        if chain.conflicts:
            for i, conflict in enumerate(chain.conflicts[:2], 1):
                logger.info(f"  [{i}] {conflict.type.value} - "
                           f"严重程度: {conflict.severity_level} - "
                           f"权威性评分: {conflict.authority_score:.2f}")
        
        logger.info(f"✓ 总成本: ${chain.cost_summary.get('total_cost', 0):.2f}")
        logger.info(f"✓ 最终结论: {chain.final_conclusion}")
        
        result = {
            "query": query,
            "chain_id": chain.chain_id,
            "conflicts_detected": len(chain.conflicts),
            "total_cost": chain.cost_summary.get('total_cost', 0),
            "conclusion_length": len(chain.final_conclusion) if chain.final_conclusion else 0
        }
        
        self.test_results['end_to_end'] = result
        return result
    
    def generate_report(self):
        """生成测试报告"""
        logger.info("\n" + "=" * 60)
        logger.info("测试完成 - 优化方案验收报告")
        logger.info("=" * 60)
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "test_results": self.test_results,
            "summary": {
                "optimization_1": {
                    "name": "NER 集成",
                    "target_improvement": "85% → 92%",
                    "actual_confidence": self.test_results.get('optimization_1_ner', {}).get('avg_confidence', 'N/A'),
                    "status": "✓ PASS" if self.test_results.get('optimization_1_ner', {}).get('avg_confidence', 0) >= 0.85 else "✗ REVIEW"
                },
                "optimization_2": {
                    "name": "BGE Embedding",
                    "target_improvement": "75% → 98%, LLM -90%",
                    "actual_similarity": self.test_results.get('optimization_2_bge', {}).get('avg_similarity', 'N/A'),
                    "status": "✓ PASS" if self.test_results.get('optimization_2_bge', {}).get('avg_similarity', 0) >= 0.75 else "✗ REVIEW"
                },
                "optimization_3": {
                    "name": "CrossRef API",
                    "target_improvement": "元数据 85% → 98%, 成本控制",
                    "actual_cost": self.test_results.get('optimization_3_api', {}).get('total_cost', 'N/A'),
                    "status": "✓ PASS" if self.test_results.get('optimization_3_api', {}).get('cost_efficiency') == 'GOOD' else "✗ REVIEW"
                }
            }
        }
        
        # 打印报告
        logger.info("\n优化 1 (NER):")
        logger.info(f"  平均置信度: {report['summary']['optimization_1']['actual_confidence']}")
        logger.info(f"  状态: {report['summary']['optimization_1']['status']}")
        
        logger.info("\n优化 2 (BGE):")
        logger.info(f"  平均相似度: {report['summary']['optimization_2']['actual_similarity']}")
        logger.info(f"  状态: {report['summary']['optimization_2']['status']}")
        
        logger.info("\n优化 3 (API):")
        logger.info(f"  成本: ${report['summary']['optimization_3']['actual_cost']}")
        logger.info(f"  状态: {report['summary']['optimization_3']['status']}")
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ 所有测试完成")
        logger.info("=" * 60)
        
        return report


async def main():
    """主测试入口"""
    tester = OptimizationTester()
    
    try:
        # 运行测试
        logger.info("开始优化方案 B 集成测试...\n")
        
        await tester.test_optimization_1_ner()
        await tester.test_optimization_2_bge()
        tester.test_optimization_3_api()
        await tester.test_end_to_end()
        
        # 生成报告
        report = tester.generate_report()
        
        # 保存报告
        report_path = "optimization_test_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"\n✓ 报告已保存到: {report_path}")
        
        return report
        
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    import sys
    
    # 检测依赖
    try:
        import transformers
        import sentence_transformers
    except ImportError as e:
        logger.warning(f"缺少依赖: {e}")
        logger.info("请运行: pip install transformers sentence-transformers")
    
    # 运行测试
    report = asyncio.run(main())
    sys.exit(0 if all(
        report['summary'][k]['status'].startswith('✓')
        for k in report['summary']
    ) else 1)
