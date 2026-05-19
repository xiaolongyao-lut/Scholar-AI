# layers/p1_fusion_weight_calibrator.py

import json
import asyncio
import logging
import numpy as np
import sys
import os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, List, Dict, Tuple

# 动态添加路径以处理导入
sys.path.append(os.getcwd())

logger = logging.getLogger("P1_WeightCalibrator")

@dataclass
class CalibrationResult:
    bm25_weight: float
    vector_weight: float
    context_weight: float
    recall_at_3: float
    mrr: float
    combined_score: float

class FusionWeightCalibrator:
    """
    P1 WBS 1.4: 自动化权重校准工具
    """
    
    def __init__(self, 
                 eval_queries_path: str = "eval_queries_v1.0.jsonl",
                 retriever: Any = None):
        self.eval_queries_path = Path(eval_queries_path)
        self.retriever = retriever or self._create_default_retriever()
        self.eval_queries = self._load_queries()

    def _create_default_retriever(self) -> Any:
        """Resolve the retriever lazily to avoid circular imports during startup."""
        from layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank

        return HybridRetrieverWithRerank(use_reranker=False)

    def _load_queries(self) -> List[Dict]:
        queries = []
        if not self.eval_queries_path.exists():
            return []
        with open(self.eval_queries_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    data = json.loads(line)
                    if 'query' in data:
                        queries.append(data)
                except:
                    continue
        return queries

    async def calibrate_grid(self, step: float = 0.2) -> CalibrationResult:
        """网格搜索最优权重"""
        best_score = -1.0
        best_result = None
        
        # 准备模拟数据源 (用于测试管道)
        mock_raw_data = {
            "claim_index": [
                {"claim": "example research on laser power", "text": "full text info", "context_summary": "P1 System Context"}
            ]
        }

        # 网格搜索空间
        for bm25_w in np.arange(0, 1.01, step):
            for vector_w in np.arange(0, 1.01 - bm25_w, step):
                context_w = 1.0 - bm25_w - vector_w
                
                score, metrics = await self._evaluate(bm25_w, vector_w, context_w, mock_raw_data)
                
                if score > best_score:
                    best_score = score
                    best_result = CalibrationResult(
                        bm25_weight=round(float(bm25_w), 2),
                        vector_weight=round(float(vector_w), 2),
                        context_weight=round(float(context_w), 2),
                        recall_at_3=metrics['recall_at_3'],
                        mrr=metrics['mrr'],
                        combined_score=round(score, 4)
                    )
                    
        return best_result

    async def _evaluate(self, bw, vw, cw, raw_data) -> Tuple[float, Dict]:
        """评估单组权重"""
        self.retriever.base_retriever.weights = {
            "bm25": bw, "vector": vw, "context": cw
        }
        
        hit_count = 0
        total_mrr = 0.0
        
        for q in self.eval_queries:
            query_text = q.get('query', '')
            results = await self.retriever.search(raw_data, query_text, top_k=3)
            # 模拟判定命中逻辑
            if results:
                hit_count += 1
                total_mrr += 1.0
                
        count = len(self.eval_queries) or 1
        metrics = {
            'recall_at_3': round(hit_count / count, 4),
            'mrr': round(total_mrr / count, 4)
        }
        combined = 0.7 * metrics['recall_at_3'] + 0.3 * metrics['mrr']
        return combined, metrics

async def main():
    calibrator = FusionWeightCalibrator()
    print("Starting Calibration...")
    best = await calibrator.calibrate_grid(step=0.2)
    print("Found Best Weights:", best)
    
    # 保存结果
    with open("calibration_results.json", "w") as f:
        json.dump(asdict(best), f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
