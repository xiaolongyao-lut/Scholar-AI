# test_p3_final.py

import asyncio
import json
from layers.p2_logic_engine import LogicEngine
from layers.p3_triangulator import EvidenceTriangulator
from layers.p3_causal_engine import CausalEngine
from layers.p3_resolver import ConflictResolver
from layers.p3_exporter import KnowledgeGraphExporter

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
    triangulator = EvidenceTriangulator()
    evidence_sets = triangulator.triangulate(report.steps[0].outputs) # 此处简化
    print(f"[P3] 证据对照完成: 处理了 {len(report.conflicts)} 个冲突")

    # 3. P3 冲突消解 (Conflict Resolution)
    resolver = ConflictResolver()
    resolutions = resolver.resolve(report.conflicts)
    print(f"[P3] 冲突消解完成: 生成 {len(resolutions)} 项建议")

    # 4. P3 因果链路构建 (Causal DAG)
    causal_engine = CausalEngine()
    # 模拟提取到的三元组关系
    triplets = [("LaserPower", "Increases", "MeltDepth"), ("MeltDepth", "Affects", "CoolingRate")]
    chains = causal_engine.extract_chains(triplets)
    dag = causal_engine.build_inference_dag(chains)
    print(f"[P3] 因果图谱构建完成: {len(dag['nodes'])} 个节点")

    # 5. P3 知识导出 (Exporter)
    exporter = KnowledgeGraphExporter()
    ttl_out = exporter.export_to_ttl(dag)
    print(f"[P3] RDF 导出成功 (TTL 长度: {len(ttl_out)})")
    
    # 保存结果
    with open("p3_final_inference.ttl", "w", encoding="utf-8") as f:
        f.write(ttl_out)
    
    print("\n✅ P3 全流程跑通。交付物已生成在 p3_final_inference.ttl")

if __name__ == "__main__":
    asyncio.run(run_p3_pipeline())
