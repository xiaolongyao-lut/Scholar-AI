import logging
import asyncio
import json
from layers.robust_parser import RobustJSONParser
from layers.claim_cache import ClaimCache
from models.p2_logic_models import SourceMeta

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IntegrationTest")

async def test_robust_parser():
    print("\n--- Testing RobustJSONParser ---")
    parser = RobustJSONParser()
    
    # 场景 1: 带 Markdown 包裹的 JSON
    text1 = "```json\n{\"id\": 1, \"status\": \"ok\"}\n```"
    res1 = parser.parse(text1)
    print(f"Markdown Strip: {res1} (Expected id:1)")
    
    # 场景 2: 尾部逗号
    text2 = "{\"data\": [1, 2, 3,],}"
    res2 = parser.parse(text2)
    print(f"Trailing Comma: {res2} (Expected [1,2,3])")
    
    # 场景 3: 截断修复
    text3 = "{\"claims\": [{\"id\": 10, \"text\": \"Partial"
    res3 = parser.parse(text3)
    print(f"Truncated Repair: {res3} (Expected structure closed)")

async def test_claim_cache():
    print("\n--- Testing ClaimCache ---")
    cache = ClaimCache(db_path=".cache/test_claims.db")
    
    text = "Semantic content of a paper chunk."
    source = SourceMeta(
        doc_id="paper_v1", 
        chunk_index=0,
        title="Test Paper",
        year=2024,
        journal="Hardening Journal"
    )
    
    sig = cache.get_chunk_signature(text, source.__dict__)
    
    # 模拟保存
    test_claims = [{"claim_id": "c1", "subject": "Laser", "confidence": 0.9}]
    cache.save_claims(sig, test_claims, metadata={"doc_id": "paper_v1"})
    
    # 模拟二次查询
    cached = cache.get_claims(sig)
    print(f"Cache Hit: {cached is not None}")
    if cached:
        print(f"Cached Subject: {cached[0]['subject']}")
    
    cache.log_stats()

if __name__ == "__main__":
    asyncio.run(test_robust_parser())
    asyncio.run(test_claim_cache())
