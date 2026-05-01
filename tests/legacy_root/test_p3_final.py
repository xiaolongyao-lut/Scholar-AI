# test_p3_final.py

import asyncio
from layers.p2_logic_engine import LogicEngine
from layers.p3_triangulator import EvidenceTriangulator
from layers.p3_causal_engine import CausalEngine
from layers.p3_consistency_validator import ConsistencyValidator
from layers.p3_resolver import ConflictResolver
from layers.p3_exporter import KnowledgeGraphExporter
from layers.p3_dynamic_updater import DynamicUpdater

async def run_p3_pipeline():
    print(">>> 启动 P3 全流程深度集成验证...")
    
    # 1. 准备 P1/P2 的输出 (模拟)
    engine = LogicEngine()
    mock_chunks = [
        {"id": "D1", "text": "增加激光功率会显著提高熔深。", "metadata": {"year": 2022, "impact_factor": 5.0}},
        {"id": "D2", "text": "在高功率区间，熔深随功率增加而下降。", "metadata": {"year": 2024, "impact_factor": 10.0}}
    ]
    report = await engine.reason("激光功率与熔深", mock_chunks)
    
    # 2. P3 证据对照 (Evidence Triangulation)
    #    注意: report.steps[0].outputs 是 List[str] (摘要信息)，而非 Claim 对象
    #    需要从 mock_chunks 构造与 P2 语义对齐的 Claim 对象来驱动 triangulator
    from models.p2_logic_models import Claim, SourceMeta
    mock_claims = [
        Claim(
            claim_id="D1_c00", subject="激光功率", predicate="提高",
            object="熔深", evidence_text="增加激光功率会显著提高熔深。",
            source=SourceMeta(doc_id="D1", title="Doc1", year=2022, journal="WJ", impact_factor=5.0),
            confidence=0.88,
        ),
        Claim(
            claim_id="D2_c00", subject="激光功率", predicate="下降",
            object="熔深", evidence_text="在高功率区间，熔深随功率增加而下降。",
            source=SourceMeta(doc_id="D2", title="Doc2", year=2024, journal="WJ", impact_factor=10.0),
            confidence=0.80,
        ),
    ]
    triangulator = EvidenceTriangulator()
    evidence_sets = triangulator.triangulate(mock_claims)
    print(f"[P3] 证据对照完成: 处理了 {len(report.conflicts)} 个冲突")
    print(f"[P3] 证据对照产出: {len(evidence_sets)} 组")

    # 3. P3 冲突消解 (Conflict Resolution)
    resolver = ConflictResolver()
    resolutions = resolver.resolve(report.conflicts)
    print(f"[P3] 冲突消解完成: 生成 {len(resolutions)} 项建议")

    # 4. P3 动态更新与冲突消解集成 (Knowledge Fusion)
    updater = DynamicUpdater()
    # 模拟新旧知识融合场景
    new_claims_for_kb = [
        # 一个更高权威性（IF: 40）的同三元组声明，应替换现有声明
        Claim(
            claim_id="UPGRADE_001", subject="LaserPower", predicate="Increases", object="MeltDepth",
            confidence=0.99, evidence_text="Definitive study on power affects.",
            source=SourceMeta(doc_id="NAT2025", title="Nature Laser Study", year=2025, journal="Nature", impact_factor=40.0)
        )
    ]
    updated_kb = updater.update_knowledge_base(mock_claims, new_claims_for_kb)
    removed_count = (len(mock_claims) + len(new_claims_for_kb)) - len(updated_kb)
    print(f"[P3] 动态更新完成: 融合后知识点总数 {len(updated_kb)} (触发淘汰/消解: {removed_count})")

    # 5. P3 因果链路构建 (Causal DAG)
    causal_engine = CausalEngine()
    # 模拟提取到的三元组关系
    triplets = [("LaserPower", "Increases", "MeltDepth")]
    chains = causal_engine.extract_chains(triplets)
    validator = ConsistencyValidator()
    consistency_report = validator.validate(chains, report.conflicts)
    print(
        f"[P3] 一致性检验完成: {consistency_report.summary.overall_status} "
        f"({consistency_report.summary.pair_count} 对, 平均分 {consistency_report.summary.average_score})"
    )
    dag = causal_engine.build_inference_dag(chains)
    print(f"[P3] 因果图谱构建完成: {len(dag['nodes'])} 个节点")

    # 6. P3 知识导出 (Exporter) — 含实质性断言
    exporter = KnowledgeGraphExporter()

    # Cypher 导出
    cypher_out = exporter.export_to_cypher(dag)
    assert isinstance(cypher_out, list), "Cypher 导出应返回 list"
    assert len(cypher_out) >= 1, "Cypher 导出至少包含一条语句"
    merge_count = sum(1 for s in cypher_out if s.startswith("MERGE"))
    create_count = sum(1 for s in cypher_out if "CREATE" in s)
    assert merge_count >= 1, "Cypher 导出至少包含一条 MERGE 节点语句"
    assert create_count >= 1, "Cypher 导出至少包含一条 CREATE 边语句"
    print(f"[P3] Cypher 导出成功 (语句数: {len(cypher_out)}, MERGE={merge_count}, CREATE={create_count})")

    # TTL 导出
    ttl_out = exporter.export_to_ttl(dag)
    assert isinstance(ttl_out, str), "TTL 导出应返回 str"
    assert len(ttl_out) > 0, "TTL 导出不应为空"
    assert "@prefix welding:" in ttl_out, "TTL 导出必须包含 welding prefix"
    assert "xsd:float" in ttl_out, "TTL 导出中应包含 xsd:float 类型标注"
    print(f"[P3] RDF 导出成功 (TTL 长度: {len(ttl_out)})")

    # JSON-LD 导出
    import json
    jsonld_out = exporter.export_to_jsonld(dag)
    jsonld_data = json.loads(jsonld_out)
    assert "@context" in jsonld_data, "JSON-LD 必须包含 @context"
    assert "@graph" in jsonld_data, "JSON-LD 必须包含 @graph"
    assert len(jsonld_data["@graph"]) >= 1, "JSON-LD @graph 至少包含一条关系"
    for entry in jsonld_data["@graph"]:
        assert entry["@type"] == "CausalRelation", "JSON-LD 每条关系的 @type 应为 CausalRelation"
    print(f"[P3] JSON-LD 导出成功 (关系数: {len(jsonld_data['@graph'])})")

    with open("p3_final_inference.ttl", "w", encoding="utf-8") as f:
        f.write(ttl_out)

    print("\n[SUCCESS] P3 全流程跑通。交付物已生成在 p3_final_inference.ttl")

if __name__ == "__main__":
    asyncio.run(run_p3_pipeline())
