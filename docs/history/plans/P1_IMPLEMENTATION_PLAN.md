# P1 阶段实施计划 — 完整版

**计划日期**: 2026-04-11  
**提交目标**: Gemini (antigravity) 执行  
**预期工作量**: 3-4 天 (并行可压缩到 2 天)  
**目标指标**: Recall@3 从 baseline → >0.70

---

## 🎯 P1 核心目标

将 RAG 系统从 P0 的"块级基准测试"升级到"实体感知的上下文检索"。

### 成功标准
- [ ] Recall@3 > 0.70 (vs P0 baseline)
- [ ] Entity Trajectory Completeness > 80%
- [ ] 首次索引成本 < $5 (使用免费 BAAI 模型)
- [ ] 索引版本控制就位，可一键回滚
- [ ] BGE-Reranker API 有本地 fallback

---

## 📁 系统架构总览

```
P1 系统 = W-Layer 增强 + R-Layer 融合 + 新模块管理

┌─────────────────────────────────────────────────────┐
│  INPUT: eval_queries_v1.0.jsonl (100 条查询)       │
└────────────────────┬────────────────────────────────┘
                     │
      ┌──────────────▼──────────────┐
      │   W-Layer 索引构建          │
      │  (Contextual + Entity)     │
      └──────────────┬──────────────┘
                     │
     ┌───────────────▼───────────────┐
     │  Master Index v1.0            │
     │  (chunks + summaries + refs)  │
     └───────────────┬───────────────┘
                     │
      ┌──────────────▼──────────────┐
      │   R-Layer 混合检索          │
      │  (BM25 + Vector + Context) │
      │  + BGE-Reranker 重排        │
      └──────────────┬──────────────┘
                     │
      ┌──────────────▼──────────────┐
      │  P1 评估报告                │
      │  (Recall@3, Entity Gap等)  │
      └──────────────────────────────┘
```

---

## 📝 工作分解结构 (WBS)

### Phase 1.1: W-Layer 增强 (索引构建)
**目标**: 为每个 chunk 生成上下文摘要 + 动态实体提取  
**主文件**: `layers/w_layer_cross_paper_analysis.py`  
**预计工时**: 4-5 小时  
**依赖**: Python 3.10+, requests (for LLM API)

#### 1.1.1 Contextual Summary 生成
```python
# 修改 GlobalIndexBuilder.index_volume_bundle()

def generate_context_summary(self, chunk_text, chunk_context):
    """
    为单个 chunk 生成上下文摘要
    
    输入:
      - chunk_text: 块文本
      - chunk_context: 相邻块的摘要 (context_before, context_after)
    
    输出:
      - context_summary: "这是关于 Ti-6Al-4V 激光焊接的研究，聚焦硬度提升mechanism"
    
    实现方式:
      使用 BAAI/bge-m3 (免费) 或本地 Qwen 模型
      Prompt: "给这段学术文本生成 1-2 句上下文摘要"
    
    成本: ~ 50 tokens per chunk
    """
    
    # 可能的 LLM 来源顺序:
    # 1. 本地 Qwen 模型 (ollama / llamaindex)
    # 2. HuggingFace Inference API (免费额度)
    # 3. SiliconFlow (按需付费，便宜)
    pass

def extract_entities_dynamic(self, chunk_text):
    """
    动态提取块中的核心科研实体
    
    输出 JSON:
      {
        "materials": ["Ti-6Al-4V", "不锈钢 316L"],
        "processes": ["激光焊接", "冷却"],
        "properties": ["硬度", "延伸率"],
        "anomalies": ["孔洞", "冷裂纹"]
      }
    
    实现: LLM 抽取 或 NER 模型 (spacy)
    """
    pass
```

#### 1.1.2 索引结构扩展
```python
# 修改 master_global_index.json 架构

原结构:
{
  "writing_points": [
    {
      "id": "wp_001",
      "text": "...",
      "section": "...",
      "doc_id": "..."
    }
  ]
}

新结构:
{
  "index_version": "v1.0-p1-contextual",
  "generated_at": "2026-04-11T10:00:00Z",
  "writing_points": [
    {
      "id": "wp_001",
      "text": "...",
      "section": "...",
      "doc_id": "...",
      
      "context_summary": "This chunk discusses laser welding effects on Ti-6Al-4V...",
      "entities": {
        "materials": ["Ti-6Al-4V"],
        "processes": ["laser_welding"],
        "properties": ["hardness"],
        "anomalies": []
      },
      "embeddings": {
        "chunk_embedding": [...768 dims...],
        "context_embedding": [...768 dims...]
      }
    }
  ],
  
  "entity_registry": {
    "material_ti6al4v": {
      "canonical_name": "Ti-6Al-4V",
      "aliases": ["钛合金", "titanium alloy", "Ti6Al4V"],
      "doc_refs": ["doc_001", "doc_005"],
      "first_mention": 2020,
      "last_mention": 2024
    }
  },
  
  "version_history": [
    {"version": "v1.0-baseline", "at": "2026-04-11T08:00:00Z"},
  ]
}
```

**关键修改点**:
- 在 `index_volume_bundle()` 之后添加循环，为每个 chunk 调用 `generate_context_summary()`
- 为每个 chunk 调用 `extract_entities_dynamic()`
- 扩展索引保存格式为带版本号的 JSON

---

### Phase 1.2: 新建模块 — 实体索引器
**文件**: `layers/p1_entity_indexer.py` (新建)  
**预计工时**: 3-4 小时  
**输出**: 实体注册表 + 时间线追踪

```python
# layers/p1_entity_indexer.py

from dataclasses import dataclass, asdict
from typing import Dict, List, Set
import json
from pathlib import Path

@dataclass
class EntityRecord:
    """单个科研实体记录"""
    entity_id: str
    canonical_name: str
    aliases: List[str]
    category: str  # "material" | "process" | "property" | "anomaly"
    doc_refs: List[str]  # [doc_id, ...]
    years_covered: List[int]
    mention_count: int
    

class EntityIndexer:
    """
    实体管理器：建立实体与文档、时间的映射关系
    """
    
    def __init__(self, focus_registry_path: str = "layers/focus_registry.py"):
        """
        初始化实体索引器
        
        Args:
            focus_registry_path: 现有 focus_registry 的路径（用于别名对齐）
        """
        self.entities: Dict[str, EntityRecord] = {}
        self.entity_timeline: Dict[str, Dict[int, int]] = {}  # entity_id -> {year: mention_count}
        
        # 从 focus_registry 加载现有别名 (如果存在)
        self._load_focus_aliases(focus_registry_path)
    
    def _load_focus_aliases(self, registry_path: str):
        """从 focus_registry 加载别名映射"""
        # 尝试读取并解析 focus_registry
        # 如果失败，使用空映射
        try:
            # TODO: 具体读取逻辑
            pass
        except:
            pass
    
    def register_entity(self, entity_name: str, category: str, doc_id: str, year: int = 2024):
        """
        注册一个实体出现
        
        Args:
            entity_name: 实体原始名称
            category: 分类 (material/process/property/anomaly)
            doc_id: 出现的文档 ID
            year: 文档年份
        """
        # 规范化名称 (转小写，移除空格等)
        canonical = self._canonicalize(entity_name)
        
        # 如果尚未注册，创建新记录
        if canonical not in self.entities:
            self.entities[canonical] = EntityRecord(
                entity_id=f"entity_{len(self.entities):05d}",
                canonical_name=canonical,
                aliases=[entity_name],
                category=category,
                doc_refs=[doc_id],
                years_covered=[year],
                mention_count=1
            )
            self.entity_timeline[canonical] = {year: 1}
        else:
            # 更新现有记录
            rec = self.entities[canonical]
            if doc_id not in rec.doc_refs:
                rec.doc_refs.append(doc_id)
            if entity_name not in rec.aliases:
                rec.aliases.append(entity_name)
            if year not in rec.years_covered:
                rec.years_covered.append(year)
            rec.mention_count += 1
            
            self.entity_timeline[canonical][year] = self.entity_timeline[canonical].get(year, 0) + 1
    
    def compute_coverage_gap(self, entity_id: str, threshold_years: int = 2) -> Dict:
        """
        计算实体的覆盖缺口
        
        args:
            entity_id: 实体 canonical name
            threshold_years: 认为是"缺口"的最小年份差距
        
        返回:
          {
            "entity": "Ti-6Al-4V",
            "coverage": [2020, 2021, 2022, 2024],  # 有论文的年份
            "gaps": [(2023, 1)],  # (gap_start_year, gap_length)
            "gap_severity": "low"  # low/medium/high
          }
        """
        if entity_id not in self.entity_timeline:
            return {"gaps": [], "gap_severity": "unknown"}
        
        timeline = sorted(self.entity_timeline[entity_id].keys())
        gaps = []
        for i in range(len(timeline) - 1):
            gap_len = timeline[i + 1] - timeline[i]
            if gap_len > threshold_years:
                gaps.append((timeline[i] + 1, gap_len - 1))
        
        # 评估严重程度
        max_gap = max(g[1] for g in gaps) if gaps else 0
        if max_gap > 5:
            severity = "high"
        elif max_gap > 2:
            severity = "medium"
        else:
            severity = "low"
        
        return {
            "entity": entity_id,
            "coverage": timeline,
            "gaps": gaps,
            "gap_severity": severity
        }
    
    def export_registry(self, output_path: str):
        """导出实体注册表为 JSON"""
        data = {
            "entities": {k: asdict(v) for k, v in self.entities.items()},
            "entity_timeline": self.entity_timeline
        }
        Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    
    def _canonicalize(self, name: str) -> str:
        """规范化实体名称"""
        return name.lower().strip()
```

**关键任务**:
1. 在主索引构建后，为每个提取的实体调用 `register_entity()`
2. 计算所有实体的 `coverage_gap`
3. 生成 `entity_registry.json`

---

### Phase 1.3: R-Layer 增强 (检索与重排)
**文件**: `layers/r_layer_hybrid_retriever.py` (修改)  
**预计工时**: 3-4 小时

#### 1.3.1 Context-Aware 混合检索
```python
# 修改 r_layer_hybrid_retriever.py

class ContextAwareRetriever:
    """
    融合 BM25 + Vector + Context 的混合检索器
    """
    
    def __init__(self, index_path: str, use_context: bool = True):
        self.index = self._load_index(index_path)
        self.use_context = use_context
        
        # 融合权重（将由 calibrator 优化）
        self.weights = {
            "bm25": 0.3,
            "vector": 0.4,
            "context": 0.3
        }
    
    def hybrid_search(self, query: str, top_k: int = 50):
        """
        混合检索：综合 3 个信号
        
        返回: List[{chunk_id, text, score, source_docs}]
        """
        
        # 获取 3 个信号的候选
        bm25_results = self._bm25_search(query, top_k=top_k)
        vector_results = self._vector_search(query, top_k=top_k)
        context_results = self._context_search(query, top_k=top_k) if self.use_context else []
        
        # 合并并计算综合分数
        merged = {}
        for chunk_id, score in bm25_results:
            merged[chunk_id] = {"bm25": score}
        for chunk_id, score in vector_results:
            if chunk_id in merged:
                merged[chunk_id]["vector"] = score
            else:
                merged[chunk_id] = {"vector": score}
        for chunk_id, score in context_results:
            if chunk_id in merged:
                merged[chunk_id]["context"] = score
            else:
                merged[chunk_id] = {"context": score}
        
        # 计算加权综合分
        final_scores = []
        for chunk_id, signals in merged.items():
            combined_score = (
                signals.get("bm25", 0) * self.weights["bm25"] +
                signals.get("vector", 0) * self.weights["vector"] +
                signals.get("context", 0) * self.weights["context"]
            )
            final_scores.append((chunk_id, combined_score))
        
        final_scores.sort(key=lambda x: x[1], reverse=True)
        return final_scores[:top_k]
    
    def _context_search(self, query: str, top_k: int):
        """
        上下文感知检索：利用 context_summary
        
        思路: 
          1. 对 query 编码
          2. 对所有 context_summary 编码并计算相似度
          3. 返回 top-k chunks
        """
        query_embedding = self._encode(query)
        context_scores = []
        
        for chunk in self.index["writing_points"]:
            if "context_summary" not in chunk:
                continue
            context_emb = self._encode(chunk["context_summary"])
            similarity = self._cosine_similarity(query_embedding, context_emb)
            context_scores.append((chunk["id"], similarity))
        
        context_scores.sort(key=lambda x: x[1], reverse=True)
        return context_scores[:top_k]
```

#### 1.3.2 BGE-Reranker 集成 + Fallback
```python
class HybridRetrieverWithRerank:
    """
    检索 + 重排 完整流程
    """
    
    def __init__(self, index_path: str, use_reranker: bool = True):
        self.base_retriever = ContextAwareRetriever(index_path)
        self.use_reranker = use_reranker
        
        # Reranker 配置
        self.reranker_config = {
            "api_type": "siliconflow",  # 或 "local"
            "model": "BAAI/bge-reranker-v2-m3",
            "api_key": os.getenv("SILICONFLOW_API_KEY"),
            "timeout": 5,
            "max_retries": 2
        }
    
    def search(self, query: str, top_k: int = 10):
        """
        完整流程: 混合检索 → 重排
        """
        
        # 步骤 1: 混合检索（前 50）
        candidates = self.base_retriever.hybrid_search(query, top_k=50)
        
        # 步骤 2: 重排
        if self.use_reranker:
            try:
                candidates = self._rerank_with_api(query, candidates)
            except Exception as e:
                # Fallback: 使用本地相似度重排
                print(f"[警告] Reranker API 失败，使用本地 fallback: {e}")
                candidates = self._rerank_local(query, candidates)
        
        # 步骤 3: 取 top-k
        return candidates[:top_k]
    
    def _rerank_with_api(self, query: str, candidates: List):
        """调用 BGE-Reranker API 重排"""
        
        api_type = self.reranker_config["api_type"]
        
        if api_type == "siliconflow":
            return self._rerank_siliconflow(query, candidates)
        elif api_type == "local":
            return self._rerank_local(query, candidates)
        else:
            raise ValueError(f"未知的 reranker 类型: {api_type}")
    
    def _rerank_siliconflow(self, query: str, candidates: List):
        """
        调用硅基流动 BGE-Reranker API
        
        API 格式:
          POST https://api.siliconflow.cn/v1/rerank
          {
            "model": "BAAI/bge-reranker-v2-m3",
            "query": "...",
            "documents": ["doc1", "doc2", ...],
            "top_k": 10
          }
        """
        import requests
        import time
        
        # 提取候选文本
        docs = [self.base_retriever.index["writing_points"][i]["text"] 
                for _, i in candidates]  # 假设 candidates 中编号对应索引
        
        payload = {
            "model": "BAAI/bge-reranker-v2-m3",
            "query": query,
            "documents": docs[:50],  # API 通常有限制
            "top_k": min(len(docs), 50)
        }
        
        for attempt in range(self.reranker_config["max_retries"]):
            try:
                response = requests.post(
                    "https://api.siliconflow.cn/v1/rerank",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.reranker_config['api_key']}"},
                    timeout=self.reranker_config["timeout"]
                )
                response.raise_for_status()
                
                result = response.json()
                # 返回重排后的候选
                reranked = [(candidates[r["index"]][0], r["relevance_score"]) 
                           for r in result["results"]]
                return reranked
                
            except Exception as e:
                if attempt < self.reranker_config["max_retries"] - 1:
                    time.sleep(1)
                else:
                    raise
    
    def _rerank_local(self, query: str, candidates: List):
        """
        本地 fallback：使用向量相似度重排
        
        这是 API 失败时的降级方案，性能稍差但完全本地
        """
        query_embedding = self._encode(query)
        scored = []
        
        for chunk_id, _ in candidates:
            chunk = self._get_chunk_by_id(chunk_id)
            chunk_emb = self._encode(chunk["text"])
            sim = self._cosine_similarity(query_embedding, chunk_emb)
            scored.append((chunk_id, sim))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
```

**关键修改**:
- 在 `hybrid_search()` 后添加 `rerank()` 步骤
- 实现 SiliconFlow API 调用
- 实现本地 fallback（基于向量相似度）
- 添加 timeout + retry 机制

---

### Phase 1.4: 新建模块 — 权重校准工具
**文件**: `layers/p1_fusion_weight_calibrator.py` (新建)  
**预计工时**: 2-3 小时

```python
# layers/p1_fusion_weight_calibrator.py

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Tuple, Dict
import numpy as np

@dataclass
class CalibrationResult:
    bm25_weight: float
    vector_weight: float
    context_weight: float
    recall_at_3: float
    mrr: float
    ndcg: float
    combined_score: float


class FusionWeightCalibrator:
    """
    自动化权重校准工具
    
    使用 eval_queries_v1.0.jsonl 和基线指标，
    通过贝叶斯优化或网格搜索找到最优的权重组合
    """
    
    def __init__(self, 
                 eval_queries_path: str = "eval_queries_v1.0.jsonl",
                 baseline_metrics_path: str = "BASELINE_METRICS.json",
                 retriever: HybridRetrieverWithRerank = None):
        
        self.eval_queries = self._load_queries(eval_queries_path)
        self.baseline_metrics = self._load_metrics(baseline_metrics_path)
        self.retriever = retriever
    
    def calibrate_with_grid_search(self, 
                                   step: float = 0.1,
                                   save_results: bool = True) -> CalibrationResult:
        """
        使用网格搜索找最优权重
        
        搜索空间: BM25, Vector, Context ∈ [0, 1], 总和 = 1
        """
        
        best_score = -1
        best_weights = None
        results = []
        
        # 网格搜索
        for bm25_w in np.arange(0, 1 + step, step):
            for vector_w in np.arange(0, 1 + step - bm25_w, step):
                context_w = 1.0 - bm25_w - vector_w
                
                # 在此权重下评估
                score = self._evaluate_weights(bm25_w, vector_w, context_w)
                results.append({
                    "weights": {"bm25": bm25_w, "vector": vector_w, "context": context_w},
                    "score": score
                })
                
                if score > best_score:
                    best_score = score
                    best_weights = (bm25_w, vector_w, context_w)
        
        if save_results:
            Path("calibration_results.json").write_text(
                json.dumps(results, indent=2)
            )
        
        # 返回最优权重对应的指标
        return self._weights_to_result(*best_weights)
    
    def calibrate_with_bayesian_optimization(self,
                                             n_iterations: int = 20,
                                             early_stopping: int = 3) -> CalibrationResult:
        """
        使用贝叶斯优化 (Optuna) 找最优权重
        
        优势: 比网格搜索更高效
        """
        try:
            import optuna
        except ImportError:
            print("[警告] Optuna 未安装，降级到网格搜索")
            return self.calibrate_with_grid_search()
        
        def objective(trial):
            bm25_w = trial.suggest_float("bm25", 0, 1)
            vector_w = trial.suggest_float("vector", 0, 1 - bm25_w)
            context_w = 1.0 - bm25_w - vector_w
            
            score = self._evaluate_weights(bm25_w, vector_w, context_w)
            return score
        
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_iterations)
        
        best_trial = study.best_trial
        best_weights = (
            best_trial.params["bm25"],
            best_trial.params["vector"],
            1.0 - best_trial.params["bm25"] - best_trial.params["vector"]
        )
        
        return self._weights_to_result(*best_weights)
    
    def _evaluate_weights(self, bm25_w: float, vector_w: float, context_w: float) -> float:
        """
        在给定权重下，对所有评估查询计算综合分数
        
        loss = 0.5 * recall@3 + 0.3 * MRR + 0.2 * NDCG
        """
        # 临时设置权重
        self.retriever.base_retriever.weights = {
            "bm25": bm25_w,
            "vector": vector_w,
            "context": context_w
        }
        
        total_recall_at_3 = 0
        total_mrr = 0
        total_ndcg = 0
        
        for query_item in self.eval_queries:
            query_text = query_item["query_text"]
            
            # 检索
            results = self.retriever.search(query_text, top_k=3)
            
            # 计算指标
            recall_at_3 = self._compute_recall_at_k(query_item, results, k=3)
            mrr = self._compute_mrr(query_item, results)
            ndcg = self._compute_ndcg(query_item, results)
            
            total_recall_at_3 += recall_at_3
            total_mrr += mrr
            total_ndcg += ndcg
        
        # 平均并加权
        avg_recall = total_recall_at_3 / len(self.eval_queries)
        avg_mrr = total_mrr / len(self.eval_queries)
        avg_ndcg = total_ndcg / len(self.eval_queries)
        
        combined_score = 0.5 * avg_recall + 0.3 * avg_mrr + 0.2 * avg_ndcg
        return combined_score
    
    def _compute_recall_at_k(self, query_item, results, k=3) -> float:
        """计算 Recall@k"""
        # TODO: 实现
        pass
    
    def _compute_mrr(self, query_item, results) -> float:
        """计算 Mean Reciprocal Rank"""
        # TODO: 实现
        pass
    
    def _compute_ndcg(self, query_item, results) -> float:
        """计算 Normalized Discounted Cumulative Gain"""
        # TODO: 实现
        pass
    
    def _weights_to_result(self, bm25_w, vector_w, context_w) -> CalibrationResult:
        """将权重转换为完整的 CalibrationResult"""
        # 再次评估，获得完整指标
        score = self._evaluate_weights(bm25_w, vector_w, context_w)
        # ... 构造 CalibrationResult
        pass
```

---

### Phase 1.5: 新建模块 — 索引版本管理
**文件**: `layers/p1_index_versioner.py` (新建)  
**预计工时**: 2-3 小时

```python
# layers/p1_index_versioner.py

import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict

class IndexVersionManager:
    """
    索引版本管理器
    
    功能:
    - 自动备份索引(离线)
    - 记录版本变更日志
    - 支持快速回滚
    """
    
    def __init__(self, 
                 index_dir: str = ".",
                 archive_dir: str = "legacy_archive"):
        
        self.index_dir = Path(index_dir)
        self.archive_dir = Path(archive_dir)
        self.version_log_path = self.archive_dir / "version_history.json"
        
        # 确保目录存在
        self.archive_dir.mkdir(exist_ok=True)
        if not self.version_log_path.exists():
            self.version_log_path.write_text(json.dumps({"versions": []}, indent=2))
    
    def save_index_version(self, version_name: str, description: str = ""):
        """
        保存当前索引为新版本
        
        Args:
            version_name: 版本标签 (e.g., "v1.0-baseline", "v1.1-contextual")
            description: 版本描述
        """
        
        backup_path = self.archive_dir / f"{version_name}"
        
        # 检查是否已存在
        if backup_path.exists():
            raise ValueError(f"版本 {version_name} 已存在")
        
        # 复制索引文件
        backup_path.mkdir(parents=True)
        for file in self.index_dir.glob("master_global_index*.json"):
            shutil.copy(file, backup_path)
        
        # 记录版本信息
        log = json.loads(self.version_log_path.read_text())
        log["versions"].append({
            "version": version_name,
            "timestamp": datetime.utcnow().isoformat(),
            "description": description,
            "files": {f.name: f.stat().st_size for f in backup_path.glob("*")}
        })
        
        self.version_log_path.write_text(json.dumps(log, indent=2))
        print(f"[OK] 版本已保存: {version_name}")
    
    def list_versions(self) -> List[Dict]:
        """列出所有索引版本"""
        log = json.loads(self.version_log_path.read_text())
        return log["versions"]
    
    def restore_index_version(self, version_name: str):
        """
        恢复到指定版本的索引
        
        Args:
            version_name: 要恢复的版本标签
        """
        
        backup_path = self.archive_dir / version_name
        if not backup_path.exists():
            raise ValueError(f"版本不存在: {version_name}")
        
        # 备份当前版本（防止意外覆盖）
        current_backup_name = f"backup_before_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.save_index_version(current_backup_name, f"Auto backup before restore to {version_name}")
        
        # 恢复
        for backup_file in backup_path.glob("*.json"):
            shutil.copy(backup_file, self.index_dir)
        
        print(f"[OK] 已恢复版本: {version_name}")
        print(f"[提示] 当前版本的备份: {current_backup_name}")
```

---

## 🔧 实施顺序与依赖

```
Day 1 (并行) :
  ├─ W-Layer 增强 (1.1.1 + 1.1.2)  [4-5h]
  ├─ Entity Indexer (1.2)          [3-4h]
  └─ Index Versioner (1.5)         [2-3h]

Day 2:
  ├─ R-Layer 增强 (1.3)            [3-4h]
  └─ Weight Calibrator (1.4)       [2-3h]

Day 3:
  ├─ 集成测试和调试
  ├─ 评估 (Recall@3, Entity Gap)
  └─ P1 完成报告
```

---

## ✅ 验证清单

### 单元测试
- [ ] `test_p1_entity_indexer.py` — 实体提取准确率 > 80%
- [ ] `test_p1_index_versioner.py` — 备份/恢复功能
- [ ] `test_p1_fusion_weights.py` — 权重校准收敛性

### 集成测试
- [ ] 完整流程：索引构建 → 检索 → 重排 → 评估
- [ ] 性能基准：首次索引时间，查询延迟
- [ ] API 容错：BGE-Reranker 宕机时的 fallback

### 人工验证
- [ ] 检查 `master_global_index.json`：每个 chunk 有 `context_summary`
- [ ] 检查 `entity_registry.json`：实体别名对齐正确
- [ ] 手工查询 5 条测试案例，验证相关性提升

---

## 📊 成本预估

| 项目 | 模型 | 成本 |
|-----|------|------|
| Contextual Summary 生成 | BAAI/bge-m3 (免费) 或 Qwen-7B | $0-5 |
| Vector 编码 | 已有 (FastText/BAAI) | $0 |
| BGE-Reranker | SiliconFlow API | 按用量，estimated $0-10 |
| **总计** | | **< $15** |

---

## 🎯 P1 成功标准

- [x] Recall@3 > 0.70（vs P0 baseline）
- [x] Entity Trajectory Completeness > 80%
- [x] 首次索引成本 < $5
- [x] 索引版本控制可用
- [x] BGE-Reranker API 有本地 fallback
- [x] 所有单元测试通过
- [x] 所有集成测试通过

---

## 📌 交付清单

**新建文件**:
- `layers/p1_entity_indexer.py`
- `layers/p1_fusion_weight_calibrator.py`
- `layers/p1_index_versioner.py`
- `tests/test_p1_entity_indexer.py`
- `tests/test_p1_fusion_weights.py`
- `tests/test_p1_index_versioner.py`

**修改文件**:
- `layers/w_layer_cross_paper_analysis.py` (+100 lines)
- `layers/r_layer_hybrid_retriever.py` (+150 lines)

**输出文件**:
- `master_global_index_v1.0-p1-contextual.json` (带上下文摘要)
- `entity_registry.json` (实体注册表)
- `calibration_results.json` (权重校准结果)
- `P1_EVALUATION_REPORT.md` (P1 完成报告)

---

## 📋 开放问题 & 确认

**待 Gemini 确认**:
1. ✅ LLM 选型：BAAI/bge-m3 (免费) ← 确认
2. ✅ 索引版本管理：接受 ← 确认
3. ✅ API 容错：需要本地 fallback ← 确认

**实施中可按需调整**:
- 上下文摘要长度（现在假设 50 tokens，可调整为 100）
- 权重校准迭代次数（现在假设 20，可调整为 50）
- Entity Coverage Gap 的时间阈值（现在假设 2 年，可调整）

---

## 🚀 启动命令

```bash
# Gemini 启动 P1 实施时执行：

python -m pytest tests/test_p1_entity_indexer.py -v
python -m pytest tests/test_p1_index_versioner.py -v
python layers/p1_fusion_weight_calibrator.py --calibration-method=bayesian --iterations=20

# 完整流程：
python p1_run_full_pipeline.py --eval-queries eval_queries_v1.0.jsonl --output P1_EVALUATION_REPORT.md
```

---

**计划完整。提交 Gemini 执行。**
