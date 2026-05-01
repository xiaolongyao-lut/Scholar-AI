# test_p2_logic.py

import asyncio
import json
import logging
from layers.p2_logic_engine import LogicEngine

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test_P2_Logic")

async def mock_llm_sim(prompt: str) -> str:
    """模拟 LLM 语义判定响应"""
    # 如果判定的是 TC4 vs 钛合金，返回高分
    if "TC4" in prompt and "Ti-6Al-4V" in prompt:
        return "0.95"
    return "0.1"

async def run_smoke_test():
    engine = LogicEngine(llm_client=mock_llm_sim)
    
    # 模拟检索数据 (包含两个直接矛盾的论点)
    mock_chunks = [
        {
            "id": "DOC-2022-001",
            "text": "激光功率增加会导致 TC4 钛合金的熔深增加，熔深约为 5mm。",
            "metadata": {
                "title": "Study A", "year": 2022, "journal": "Journal of Welding",
                "impact_factor": 2.5, "citation_count": 50
            }
        },
        {
            "id": "DOC-2024-015",
            "text": "在极高功率下，Ti-6Al-4V 的熔深反而减少，熔深降至 3mm 以下。",
            "metadata": {
                "title": "Study B", "year": 2024, "journal": "Nature Welding",
                "impact_factor": 35.0, "citation_count": 5
            }
        }
    ]

    print(">>> 启动 P2 逻辑推演冒烟测试...")
    report = await engine.reason(query="激光功率对熔深的影响", retrieved_chunks=mock_chunks)

    print("\n" + "="*60)
    print(f"推演结论: {report.final_conclusion}")
    print("="*60)
    
    print("\n检测到的冲突详情:")
    for cf in report.conflicts:
        print(f"- 类型: {cf.type.value}")
        print(f"- 严重级别: {cf.severity_level}")
        print(f"- 演变类型: {cf.evolution_type}")
        print(f"- 权威性评分: {cf.authority_score}")
        print(f"- 详细解释: {cf.interpretation}")
        print(f"- 权威性概括: {cf.authority_summary}")
        print("-" * 30)

    # 验证是否正确识别了 TC4 和 Ti-6Al-4V 的关联
    # 验证是否识别了 增加 vs 减少 的矛盾

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
