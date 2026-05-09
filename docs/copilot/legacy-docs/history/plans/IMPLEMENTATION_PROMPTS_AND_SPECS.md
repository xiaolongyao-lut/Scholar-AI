# 🎯 五大优化方向：Gemini提示词 + 技术规范

## 📋 快速导航
- **P0**: 检索权重自适应
- **P1**: 流水线并行化  
- **P2**: 冲突自动修复
- **P3**: 批处理自适应
- **P4**: 缓存双层加速

---

## P0: 混合检索权重智能自适应

### 📝 Gemini提示词

```text
我正在开发一个学术文献处理系统，需要你帮我优化混合检索的权重配置。

【当前情况】
- 系统进行三种混合检索：BM25关键词匹配、向量嵌入相似度、上下文相似度
- 当前使用硬编码权重：bm25=0.3, vector=0.4, context=0.3
- 问题：不同领域的论文（材料学、工艺参数、组织性能）对权重的需求不同

【目标】
1. 根据论文关注点(focus)自动选择最优权重配置
2. 缓存权重配置，减少重复计算
3. 提升检索精度20%以上

【技术背景】
- 已有p1_fusion_weight_calibrator.py实现grid search功能
- A层关注点提取器能识别论文主要领域
- R层混合检索在layers/r_layer_hybrid_retriever.py中

【需要你做的】
1. 设计自适应加权策略（根据focus关键词自动映射权重）
2. 给出权重缓存的数据结构设计
3. 提供grid search结果的缓存和应用流程
4. 建议如何验证权重改进的有效性

请提供清晰的实现思路、伪代码示例、以及可能的改进方向。
```

### 🔧 技术规范

```python
# 文件: layers/adaptive_weight_manager.py

class AdaptiveWeightManager:
    """
    自适应权重管理器
    职责：
      1. 根据论文focus识别领域类型
      2. 查询/生成最优权重配置
      3. 缓存权重以加速后续查询
    """
    
    def __init__(self, cache_path: str = ".cache/weights.json"):
        self.cache_path = cache_path
        self.weight_cache = {}  # domain_key -> weights
        self.calibrator = FusionWeightCalibrator()
        self._load_cache()
    
    def get_optimal_weights(self, focus_keywords: List[str]) -> Dict[str, float]:
        """
        获取最优权重配置
        
        Args:
            focus_keywords: 从A层提取的关键词，如["激光", "功率", "晶粒"]
        
        Returns:
            {"bm25": 0.25, "vector": 0.45, "context": 0.30}
        
        Flow:
          1. hash(focus_keywords) → domain_key
          2. 检查cache中是否存在
             - YES → 返回并更新访问时间
             - NO → 调用calibrator.grid_search()
          3. 保存到cache
          4. 返回权重
        """
        pass
    
    def _identify_domain(self, focus_keywords: List[str]) -> str:
        """
        根据关键词确定论文属于哪个领域
        
        示例:
          ["激光", "功率"] → "laser_processing"
          ["晶粒", "组织"] → "microstructure"
          ["应力", "应变"] → "mechanical_property"
        
        实现：关键词分类字典 or 简单匹配
        """
        pass
    
    def _calibrate_for_domain(self, domain: str, sample_size: int = 10):
        """
        为特定领域进行权重校准
        
        使用calibrator.grid_search()找最优权重
        返回值缓存
        """
        pass
    
    def _load_cache(self):
        """初始化启动时加载缓存"""
        pass
    
    def _save_cache(self):
        """定期保存缓存到disk"""
        pass

# 修改: layers/r_layer_hybrid_retriever.py
class HybridRetriever:
    def __init__(self, enable_adaptive_weights: bool = True):
        self.weight_manager = AdaptiveWeightManager() if enable_adaptive_weights else None
        self.default_weights = {"bm25": 0.3, "vector": 0.4, "context": 0.3}
    
    async def search(self, query: str, focus_keywords: List[str] = None) -> List[Dict]:
        """
        混合检索
        
        新增逻辑：
          if self.weight_manager and focus_keywords:
              weights = self.weight_manager.get_optimal_weights(focus_keywords)
          else:
              weights = self.default_weights
          
          return self._execute_hybrid_search(query, weights)
        """
        pass

# 缓存格式: .cache/weights.json
{
  "laser_processing": {
    "bm25": 0.25,
    "vector": 0.45,
    "context": 0.30,
    "last_updated": "2026-04-12",
    "sample_size": 12,
    "avg_precision": 0.78
  },
  "microstructure": {
    "bm25": 0.35,
    "vector": 0.35,
    "context": 0.30,
    ...
  }
}

# 验证方案：
# 1. 在10篇测试论文上对比精度 (P@5, Recall@20)
# 2. 硬编码权重 vs 自适应权重对比
# 3. 记录缓存命中率
```

### 📊 验收标准
- ✅ P@5 提升到0.78+ (从0.65)
- ✅ Recall@20 提升到0.85+ (从0.72)
- ✅ 缓存查询速度 <5ms
- ✅ grid search耗时可控 <30s

---

## P1: 端到端流水线并行化

### 📝 Gemini提示词

```text
我需要优化学术文献处理pipeline的性能，目标是将45秒降到31秒。

【当前pipeline】
```
提取(8s) → 关注点(10s) → 检索(12s) → 索引(5s) → 评分(7s) → 生成(3s)
总计：45s (串行)
```

【分析】
- 关注点提取(A层)依赖提取结果(E层)
- 但检索(R层)只需要A层的关键词，不需要等K/G/P
- 所以可以：提取(E) + 关注点(A) → [完成后] 检索(R) 同步执行

【目标】
改造为三级流水架构：
```
Level 1: E_extract + E_images (并行) = max(8s) = 8s
Level 2: A_focus || R_retrieval (并行) = max(10, 12) = 12s
Level 3: K_index + G_score || P_generate (并行) = max(12, 3) = 12s
总计：8 + 12 + 12 = 32s (-29%)
```

【需要你做的】
1. 分析integrated_pipeline.py的完整依赖关系
2. 找出所有可并行执行的任务对
3. 设计流控机制（缓冲区、backpressure）
4. 提供async/await的重构建议
5. 建议性能测试方案

请提供实现架构图、修改检查清单、以及并行检测代码。
```

### 🔧 技术规范

```python
# 文件: layers/pipeline_orchestrator.py

import asyncio
from typing import List, Dict, Any

class PipelineOrchestrator:
    """
    三级流水线协调器
    职责：
      1. 管理E、A、R、K、G、P层的执行顺序
      2. 实现Level 1/2/3的并行执行
      3. 处理backpressure和缓冲
    """
    
    def __init__(self, max_buffer_size: int = 100):
        self.max_buffer_size = max_buffer_size
        # Level 1result缓冲
        self.extraction_queue = asyncio.Queue(maxsize=max_buffer_size)
        # Level 2 result缓冲
        self.focus_queue = asyncio.Queue(maxsize=max_buffer_size)
        self.retrieval_queue = asyncio.Queue(maxsize=max_buffer_size)
    
    async def process_document(self, pdf_path: str) -> Dict[str, Any]:
        """
        三级流水处理单个文档
        
        Level 1 (Extraction): 并行提取文本和图表
        Level 2 (Analysis): 并行进行关注点提取和检索
        Level 3 (Refinement): 并行进行索引构建和结果生成
        """
        
        # Level 1: 并行执行E_extract_text + E_extract_images
        extraction_task = asyncio.create_task(
            self._extract_features(pdf_path)
        )
        
        # 等待E完成，获得提取结果
        extracted = await extraction_task  # 8s
        
        # Level 2: 并行执行A_focus + R_retrieval
        # A_focus依赖extracted，可立即开始
        focus_task = asyncio.create_task(
            self._extract_focus(extracted)
        )
        # R_retrieval也可立即开始（使用文本提取部分）
        retrieval_task = asyncio.create_task(
            self._hybrid_retrieve(extracted['text'])
        )
        
        focus_result = await focus_task      # 10s
        retrieval_result = await retrieval_task  # 12s
        
        # Level 3: 并行执行K_index + G_score 和 P_generate
        index_task = asyncio.create_task(
            self._build_index(focus_result, retrieval_result)
        )
        generate_task = asyncio.create_task(
            self._generate_presentation(focus_result, retrieval_result)
        )
        
        indexed = await index_task           # 5s
        generated = await generate_task      # 3s (并行执行，所以总耗时=max(5,3)=5s)
        
        # 最终结果聚合
        return self._aggregate_results(
            extracted, focus_result, retrieval_result, indexed, generated
        )
    
    async def _extract_features(self, pdf_path: str):
        """E层: 提取文本 + 图表（并行）"""
        text_task = asyncio.create_task(extract_text(pdf_path))
        images_task = asyncio.create_task(extract_images(pdf_path))
        
        text, images = await asyncio.gather(text_task, images_task)
        return {"text": text, "images": images}
    
    async def _extract_focus(self, extracted: Dict):
        """A层: 从提取结果生成关注点"""
        # 调用A层的async方法
        return await agent_coordinator.extract_focus_async(extracted['text'])
    
    async def _hybrid_retrieve(self, text: str, focus: List[str] = None):
        """R层: 混合检索"""
        return await hybrid_retriever.search_async(text)
    
    async def _build_index(self, focus, retrieval):
        """K层: 构建索引"""
        return await index_builder.build_async(focus, retrieval)
    
    async def _generate_presentation(self, focus, retrieval):
        """P层: 生成报告"""
        return await presentation_layer.generate_async(focus, retrieval)
    
    def _aggregate_results(self, *args) -> Dict:
        """聚合所有Level的结果"""
        pass


# 修改检查清单:
# ✅ E层 extract_text/extract_images 支持async
# ✅ A层 extract_focus 支持async  
# ✅ R层 hybrid_retrieval 支持async
# ✅ K层 build_index 支持async
# ✅ G层 academic_scoring 支持async
# ✅ P层 generate_word 支持async
# ✅ 添加asyncio.Queue流控
# ✅ 添加backpressure处理（Queue满时的blocking）

# 性能测试:
async def benchmark_pipeline():
    """
    基准测试对比
    
    Test 1: 串行处理 (baseline)
      start_time = time.time()
      old_result = await old_serial_process(pdf)
      serial_time = time.time() - start_time
    
    Test 2: 三级并行处理 (new)
      start_time = time.time()
      new_result = await orchestrator.process_document(pdf)
      parallel_time = time.time() - start_time
    
    speedup = serial_time / parallel_time
    # Expected: >1.3x (目标31s/45s = 1.45x)
    """
    pass
```

### 📊 验收标准
- ✅ 单文处理时间 45s → 31s (-31%)
- ✅ 精度无下降（与串行处理结果完全相同）
- ✅ 内存峰值不超过+25%
- ✅ 10文件批处理稳定运行

---

## P2: 冲突自动修复（简化版）

### 📝 Gemini提示词

```text
我需要为学术文献系统实现自动冲突修复功能。

【背景】
- W层已能检测参数冲突：同一参数在不同论文中有不同的结果
- 示例冲突：
  论文A: "激光功率500W时晶粒尺寸50μm"
  论文B: "激光功率505W时晶粒尺寸58μm"
  论文C: "激光功率510W时晶粒尺寸52μm"

【目标】
自动将这些冲突修复为统一的共识值，减少90%的人工审核工作

【修复思路】
1. 参数相似度匹配（数值容差±5%）
2. 相似冲突聚类（DBSCAN or 简单组距法）
3. 加权投票生成共识（按各论文confidence加权平均）
4. 置信度评估（>0.85自动采纳，<0.70保留未决）

【需要你做的】
1. 设计参数相似度算法（数值vs分类）
2. 聚类与投票的具体实现
3. 置信度计算公式
4. 验证方案（准确率、recall等）
5. 用户交互设计（展示修复结果，允许调整）

请提供完整的算法描述、伪代码、数据结构定义、以及测试用例。
```

### 🔧 技术规范

```python
# 文件: layers/conflict_resolver.py

from dataclasses import dataclass
from typing import List, Dict, Tuple
import numpy as np

@dataclass
class ConflictValue:
    """冲突中的单个值"""
    source: str              # 论文ID
    value: Any               # 参数值
    confidence: float        # 该观点的置信度 (0-1)
    extraction_method: str   # "regex" or "llm"

@dataclass
class ConflictResolution:
    """冲突修复结果"""
    parameter: str
    consensus_value: Any
    consensus_confidence: float
    decision_level: str      # "auto_accept" / "needs_review" / "undecidable"
    supporting_values: List[ConflictValue]
    explanation: str         # 人工可读的解释

class ConflictResolver:
    """
    冲突自动修复器
    """
    
    def resolve_conflict(self, conflicts: List[ConflictValue]) -> ConflictResolution:
        """
        主流程：冲突 → 聚类 → 投票 → 决议
        
        Args:
            conflicts: 同一参数的多个冲突观点
        
        Returns:
            ConflictResolution 对象
        """
        
        # Step 1: 检测是否需要聚类（预先判断冲突数量）
        if len(conflicts) <= 1:
            return ConflictResolution(
                parameter=conflicts[0].parameter,
                consensus_value=conflicts[0].value,
                consensus_confidence=conflicts[0].confidence,
                decision_level="auto_accept",
                supporting_values=conflicts,
                explanation="仅单一来源，直接采纳"
            )
        
        # Step 2: 参数相似度匹配与聚类
        clusters = self._cluster_similar_values(conflicts)
        # clusters = [
        #   [ConflictValue(..., "500W"), ConflictValue(..., "505W"), ...],
        #   ...
        # ]
        
        # Step 3: 针对最大的cluster进行加权投票
        main_cluster = max(clusters, key=len)
        consensus_value, consensus_conf = self._weighted_voting(main_cluster)
        
        # Step 4: 决策
        if consensus_conf > 0.85:
            decision_level = "auto_accept"
        elif consensus_conf > 0.70:
            decision_level = "needs_review"
        else:
            decision_level = "undecidable"
        
        return ConflictResolution(
            parameter=conflicts[0].parameter,
            consensus_value=consensus_value,
            consensus_confidence=consensus_conf,
            decision_level=decision_level,
            supporting_values=main_cluster,
            explanation=self._generate_explanation(main_cluster, consensus_value)
        )
    
    def _cluster_similar_values(self, values: List[ConflictValue]) -> List[List[ConflictValue]]:
        """
        聚类相似的值
        
        算法选择（根据参数类型）：
          - 数值参数：按相对距离聚类（允许±5%差异）
          - 分类参数：完全匹配或编辑距离
        
        示例（数值参数）：
          values = [500W, 505W, 510W, 600W]
          clusters = [[500W, 505W, 510W], [600W]]
          （因为500-510都在同一相对距离内）
        
        使用简单的distance-based聚类：
          1. 计算所有对的距离矩阵
          2. 若距离<threshold，归入同一cluster
          3. 使用并查集(Union-Find)或DBSCAN
        """
        
        if not values:
            return []
        
        # 检测参数类型
        param_type = self._detect_parameter_type(values[0].value)
        
        if param_type == "numeric":
            return self._cluster_numeric(values, tolerance=0.05)  # ±5%
        else:
            return self._cluster_categorical(values)
    
    def _cluster_numeric(self, values: List[ConflictValue], tolerance: float = 0.05):
        """数值参数聚类"""
        if not values:
            return []
        
        # 提取数值
        numeric_values = [float(self._extract_numeric(v.value)) for v in values]
        
        # 计算距离矩阵
        n = len(numeric_values)
        distances = np.zeros((n, n))
        for i in range(n):
            for j in range(i+1, n):
                # 相对距离
                rel_dist = abs(numeric_values[i] - numeric_values[j]) / max(numeric_values[i], numeric_values[j])
                distances[i][j] = distances[j][i] = rel_dist
        
        # 聚类：若距离<tolerance，则聚在一起
        clusters = [[] for _ in range(n)]
        visited = [False] * n
        
        for i in range(n):
            if visited[i]:
                continue
            cluster_idx = i
            clusters[cluster_idx].append(values[i])
            visited[i] = True
            
            for j in range(i+1, n):
                if not visited[j] and distances[i][j] < tolerance:
                    clusters[cluster_idx].append(values[j])
                    visited[j] = True
        
        return [c for c in clusters if c]  # 删除空cluster
    
    def _cluster_categorical(self, values: List[ConflictValue]):
        """分类参数聚类"""
        # 直接按值分组
        groups = {}
        for v in values:
            key = str(v.value)
            if key not in groups:
                groups[key] = []
            groups[key].append(v)
        
        return list(groups.values())
    
    def _weighted_voting(self, cluster: List[ConflictValue]) -> Tuple[Any, float]:
        """
        加权投票生成共识值
        
        权重 = 各论文的confidence
        结果 = 加权平均或加权众数
        """
        
        if not cluster:
            return None, 0.0
        
        # 尝试数值加权平均
        try:
            numeric_vals = [float(self._extract_numeric(v.value)) for v in cluster]
            weights = [v.confidence for v in cluster]
            
            weighted_avg = sum(v * w for v, w in zip(numeric_vals, weights)) / sum(weights)
            
            # 计算加权标准差评估一致性
            weighted_var = sum((v - weighted_avg)**2 * w for v, w in zip(numeric_vals, weights)) / sum(weights)
            consensus_confidence = 1.0 - (np.sqrt(weighted_var) / weighted_avg)  # 归一化
            consensus_confidence = max(0.0, min(1.0, consensus_confidence))  # Clip to [0, 1]
            
            return weighted_avg, consensus_confidence
        
        except:
            # 分类参数：加权众数
            value_weights = {}
            for v in cluster:
                key = str(v.value)
                value_weights[key] = value_weights.get(key, 0) + v.confidence
            
            consensus_value = max(value_weights, key=value_weights.get)
            consensus_confidence = value_weights[consensus_value] / sum(value_weights.values())
            
            return consensus_value, consensus_confidence
    
    def _generate_explanation(self, cluster: List[ConflictValue], consensus_value: Any) -> str:
        """生成人工可读的解释"""
        sources = ", ".join([v.source for v in cluster])
        return f"基于{len(cluster)}个来源({sources})，加权投票得出共识值：{consensus_value}"
    
    def _detect_parameter_type(self, value: Any) -> str:
        """检测参数类型"""
        try:
            float(self._extract_numeric(value))
            return "numeric"
        except:
            return "categorical"
    
    def _extract_numeric(self, value: Any) -> float:
        """从字符串中提取数值"""
        import re
        match = re.search(r'-?\d+\.?\d*', str(value))
        if match:
            return float(match.group())
        raise ValueError(f"Cannot extract numeric value from {value}")

# 集成到W层
# 文件: layers/w_layer_cross_paper_analysis.py

class CrossPaperAnalyzer:
    def __init__(self):
        self.conflict_detector = ConflictDetector()
        self.conflict_resolver = ConflictResolver()
    
    async def analyze_conflicts(self, all_claims: List[Claim]) -> List[ConflictResolution]:
        """
        检测并自动修复冲突
        """
        
        conflicts = self.conflict_detector.detect(all_claims)
        # conflicts = {
        #   "激光功率-晶粒尺寸": [ConflictValue(...), ...],
        #   ...
        # }
        
        resolutions = []
        for param_pair, conflict_values in conflicts.items():
            resolution = self.conflict_resolver.resolve_conflict(conflict_values)
            resolutions.append(resolution)
        
        return resolutions

# 测试用例
def test_conflict_resolution():
    resolver = ConflictResolver()
    
    conflicts = [
        ConflictValue("paper_A", "500W", 0.92, "llm"),
        ConflictValue("paper_B", "505W", 0.88, "regex"),
        ConflictValue("paper_C", "510W", 0.85, "llm"),
    ]
    
    resolution = resolver.resolve_conflict(conflicts)
    
    print(f"共识值: {resolution.consensus_value}")
    print(f"置信度: {resolution.consensus_confidence:.2f}")
    print(f"决策级别: {resolution.decision_level}")
    print(f"解释: {resolution.explanation}")
    
    # Expected:
    # 共识值: 505.0
    # 置信度: 0.88
    # 决策级别: needs_review
    # 解释: 基于3个来源(paper_A, paper_B, paper_C)，加权投票得出共识值：505.0
```

### 📊 验收标准
- ✅ 自动修复率 ≥ 65%
- ✅ 决议准确率 ≥ 88% (与人工审核对比)
- ✅ 修复速度 <1s/冲突
- ✅ 支持需审核状态展示

---

## P3: 批处理自适应分配与动态扩展

### 📝 Gemini提示词

```text
我需要升级批处理系统，支持从13篇扩展到100+篇文档。

【当前情况】
- batch_controller.py 中 batch_size=13 是经验值（硬编码）
- 单worker，串行处理
- 无中间结果保存，大规模处理易中断
- 问题：50+篇时内存溢出，100+篇时系统crash

【需求】
1. 根据PDF大小、系统可用内存自动计算最优batch_size
2. 支持多worker并行处理（2-4个进程）
3. 实现增量checkpoint保存，支持断点续传
4. 内存使用量保持在可控范围
5. 支持100+篇论文的稳定处理

【技术背景】
- 单文处理耗时45s（优化后31s）
- 单文内存占用约50MB + 10MB per图表
- 系统可用内存通常2-16GB不等

【需要你做的】
1. 设计自适应batch_size计算算法
2. 多worker的任务分配与结果聚合方案
3. Checkpoint机制设计
4. 内存监控与动态调整逻辑
5. 测试方案（10、50、100篇规模）

请提供完整的系统设计、伪代码、以及恢复逻辑。
```

### 🔧 技术规范

```python
# 文件: adaptive_batch_processor.py

import os
import psutil
import logging
from multiprocessing import Pool, Manager
from dataclasses import dataclass
from typing import List, Dict, Callable

@dataclass
class BatchConfig:
    batch_size: int
    num_workers: int
    memory_per_worker_mb: int
    estimated_total_time_s: float

class AdaptiveBatchProcessor:
    """
    自适应批处理器
    
    核心功能：
      1. 分析输入：PDF大小、页数、图表数
      2. 计算最优配置：batch_size, worker数, 内存限制
      3. 创建worker池并分发任务
      4. 增量保存checkpoint
      5. 异常恢复
    """
    
    def __init__(self, checkpoint_dir: str = "checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        self.logger = logging.getLogger(__name__)
        os.makedirs(checkpoint_dir, exist_ok=True)
    
    def analyze_pdfs(self, pdf_paths: List[str]) -> Dict:
        """
        分析所有PDF的统计信息
        
        Returns:
            {
              "total_size_mb": 1024,
              "avg_size_mb": 80,
              "avg_pages": 25,
              "avg_images": 12,
              "max_size_mb": 250,
              "num_pdfs": 13
            }
        """
        stats = {
            "total_size_mb": 0,
            "avg_size_mb": 0,
            "avg_pages": 0,
            "avg_images": 0,
            "max_size_mb": 0,
            "num_pdfs": len(pdf_paths)
        }
        
        file_stats = []
        for pdf_path in pdf_paths:
            size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            pages, images = self._extract_pdf_metadata(pdf_path)
            
            file_stats.append({
                "size_mb": size_mb,
                "pages": pages,
                "images": images
            })
            
            stats["total_size_mb"] += size_mb
            stats["max_size_mb"] = max(stats["max_size_mb"], size_mb)
        
        if file_stats:
            stats["avg_size_mb"] = stats["total_size_mb"] / len(file_stats)
            stats["avg_pages"] = sum(f["pages"] for f in file_stats) / len(file_stats)
            stats["avg_images"] = sum(f["images"] for f in file_stats) / len(file_stats)
        
        return stats
    
    def compute_optimal_config(self, pdf_paths: List[str]) -> BatchConfig:
        """
        根据PDF统计和系统资源计算最优配置
        
        算法：
          1. 估算单文处理内存占用 = 50MB base + 10MB per图 + 20MB overhead
          2. 获取系统可用内存
          3. 根据内存计算最多worker数
          4. 根据worker数计算batch_size
          5. 验证总耗时预期
        """
        
        stats = self.analyze_pdfs(pdf_paths)
        
        # Step 1: 估算单文内存
        per_pdf_memory_mb = 50 + stats["avg_images"] * 10 + 20
        
        # Step 2: 系统资源
        available_memory_mb = psutil.virtual_memory().available / (1024 * 1024)
        num_cpus = os.cpu_count()
        
        # Step 3: 计算最大worker数（保留30%内存给系统）
        usable_memory_mb = available_memory_mb * 0.7
        memory_per_worker_mb = per_pdf_memory_mb * 3  # 每worker同时处理3个PDF
        max_workers = max(1, int(usable_memory_mb / memory_per_worker_mb))
        actual_workers = min(max_workers, num_cpus, 4)  # 最多4个worker
        
        # Step 4: 计算batch_size
        # 目标：每个worker处理2-5个PDF
        pdfs_per_worker = 3
        batch_size = actual_workers * pdfs_per_worker
        
        # Step 5: 限制batch_size在[5, 25]范围
        batch_size = max(5, min(batch_size, 25))
        
        # Step 6: 预估总耗时
        # 每文处理耗时：31s (优化后)
        # 批处理overhead：每个worker启动2s
        total_time_s = (len(pdf_paths) / actual_workers) * 31 + actual_workers * 2
        
        return BatchConfig(
            batch_size=batch_size,
            num_workers=actual_workers,
            memory_per_worker_mb=memory_per_worker_mb,
            estimated_total_time_s=total_time_s
        )
    
    async def process_documents(self, 
                                pdf_paths: List[str],
                                process_func: Callable) -> Dict:
        """
        主处理流程
        
        Flow:
          1. 检查checkpoint，恢复已处理部分
          2. 计算latest batch配置
          3. 创建worker池
          4. 分批处理
          5. 每batch后保存checkpoint
          6. 最后聚合所有结果
        """
        
        # Step 1: 恢复checkpoint
        processed, remaining = self._restore_checkpoint(pdf_paths)
        self.logger.info(f"恢复进度: {len(processed)}/{len(pdf_paths)} 完成")
        
        if not remaining:
            self.logger.info("所有文档已处理，直接聚合结果")
            return self._aggregate_results(pdf_paths)
        
        # Step 2: 计算配置
        config = self.compute_optimal_config(remaining)
        self.logger.info(f"批处理配置: batch_size={config.batch_size}, "
                        f"workers={config.num_workers}, "
                        f"est_time={config.estimated_total_time_s:.0f}s")
        
        # Step 3: 创建worker池
        with Pool(config.num_workers) as pool:
            # Step 4: 分批处理
            for batch_idx, batch_pdfs in enumerate(
                self._chunked(remaining, config.batch_size)
            ):
                self.logger.info(f"处理第{batch_idx+1}批 ({len(batch_pdfs)}个文件)")
                
                # 分发任务到worker
                batch_results = pool.map(process_func, batch_pdfs)
                
                # Step 5: 保存checkpoint
                self._save_checkpoint(batch_idx, batch_pdfs, batch_results)
                
                # 内存监控
                memory_usage = psutil.virtual_memory().percent
                self.logger.info(f"内存使用率: {memory_usage:.1f}%")
                
                if memory_usage > 90:
                    self.logger.warning("内存使用过高，动态调整batch_size")
                    config.batch_size = max(1, config.batch_size - 1)
        
        # Step 6: 聚合结果
        return self._aggregate_results(pdf_paths)
    
    def _restore_checkpoint(self, pdf_paths: List[str]) -> tuple:
        """
        恢复已处理的checkpoint
        
        Returns:
            (processed_pdfs, remaining_pdfs)
        """
        
        completed_batches = []
        batch_files = sorted([f for f in os.listdir(self.checkpoint_dir) 
                             if f.startswith("batch_")])
        
        for batch_file in batch_files:
            batch_path = os.path.join(self.checkpoint_dir, batch_file)
            with open(batch_path, 'r') as f:
                batch_data = json.load(f)
                completed_batches.extend(batch_data["pdf_paths"])
        
        processed = set(completed_batches)
        remaining = [p for p in pdf_paths if p not in processed]
        
        return list(processed), remaining
    
    def _save_checkpoint(self, batch_idx: int, pdf_paths: List[str], results: List[Dict]):
        """
        保存批处理checkpoint
        
        格式: .cache/batch_<idx>.json
        """
        checkpoint = {
            "batch_idx": batch_idx,
            "pdf_paths": pdf_paths,
            "results": results,
            "timestamp": time.time()
        }
        
        checkpoint_file = os.path.join(
            self.checkpoint_dir,
            f"batch_{batch_idx:06d}.json"
        )
        
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint, f)
        
        self.logger.info(f"Checkpoint保存: {checkpoint_file}")
    
    def _aggregate_results(self, pdf_paths: List[str]) -> Dict:
        """
        聚合所有batch的结果
        
        读取所有checkpoint文件，合并为最终结果
        """
        
        all_results = {}
        
        batch_files = sorted([f for f in os.listdir(self.checkpoint_dir)
                             if f.startswith("batch_")])
        
        for batch_file in batch_files:
            batch_path = os.path.join(self.checkpoint_dir, batch_file)
            with open(batch_path, 'r') as f:
                batch_data = json.load(f)
                for pdf_path, result in zip(batch_data["pdf_paths"], batch_data["results"]):
                    all_results[pdf_path] = result
        
        return {
            "total_pdfs": len(pdf_paths),
            "processed": len(all_results),
            "results": all_results
        }
    
    def _chunked(self, lst: List, chunk_size: int):
        """分块迭代"""
        for i in range(0, len(lst), chunk_size):
            yield lst[i:i + chunk_size]
    
    def _extract_pdf_metadata(self, pdf_path: str) -> tuple:
        """提取PDF页数和图表数"""
        # 使用pypdf or pdfplumber
        pages = 0
        images = 0
        
        try:
            from pdfplumber import open as pdf_open
            with pdf_open(pdf_path) as pdf:
                pages = len(pdf.pages)
                for page in pdf.pages:
                    images += len(page.images)
        except:
            # Fallback: 使用PyPDF2
            pass
        
        return pages, images

# 使用示例
async def main():
    processor = AdaptiveBatchProcessor()
    
    pdf_paths = glob.glob("data/papers/*.pdf")
    
    results = await processor.process_documents(
        pdf_paths,
        process_func=process_single_pdf
    )
    
    print(f"处理完成: {results['processed']}/{results['total_pdfs']}")
```

### 📊 验收标准
- ✅ 支持100+篇论文处理
- ✅ 内存占用增长<15% (vs 13篇)
- ✅ Batch_size自动计算正确率>95%
- ✅ 断点续传成功率100%
- ✅ 10篇耗时<5分钟, 100篇<100分钟

---

## P4: 缓存与记忆双层加速

### 📝 Gemini提示词

```text
我需要为系统实现多层缓存加速机制。

【现状问题】
- 当前仅有ClaimCache (SQLite)，缓存Claim提取结果
- 热点查询（如"激光功率对晶粒尺寸影响"）每次都需完整处理：检索(2s) + 评分(1.5s) + 生成(1.5s) = 5s
- M层MemPalace配置启用但未充分利用
- 相同查询的缓存命中率仅5-10%

【目标】
三层缓存架构：
```
L1 进程内缓存 (最快，全内存)
  ↓ (miss)
L2 SQLite持久缓存 (中速)
  ↓ (miss)  
L3 MemPalace记忆库 (慢，永久)
  ↓ (miss)
实时计算
```

【需求】
1. 设计Query Fingerprint（确保相同查询命中同一缓存键）
2. L1进程缓存：15分钟TTL，LRU驱逐
3. L2检索结果缓存：永久存储，支持TTL更新
4. L3 MemPalace集成：自动存储高置信结果(>0.8)
5. 缓存分析与监控

【预期效果】
- 热点查询响应时间：5s → <100ms (50倍)
- 缓存整体命中率：30-40%
- 平均查询速度提升：5x-10x

【需要你做的】
1. Query Fingerprint生成算法
2. 三层缓存的数据结构设计
3. TTL和驱逐策略
4. MemPalace集成接口
5. 缓存命中率统计与优化建议

请提供完整实现、集成点、以及性能测试方案。
```

### 🔧 技术规范

```python
# 文件: layers/multi_layer_cache.py

import hashlib
import json
import time
import sqlite3
import functools
from typing import Any, Dict, Optional, Callable
from collections import OrderedDict

class QueryFingerprint:
    """
    查询指纹生成器
    
    将复杂的查询转换为唯一的hash key，确保：
      - 相同语义的查询使用同一缓存键
      - 不同查询的hash不碰撞
    """
    
    @staticmethod
    def generate(query: str, focus_keywords: list = None, 
                 domain: str = None) -> str:
        """
        生成查询指纹
        
        示例：
          query = "激光功率对晶粒尺寸的影响"
          focus_keywords = ["激光", "功率", "晶粒"]
          domain = "laser_processing"
          
          → fingerprint = "a7f3d9e2c1b4..." (32-char hex)
        """
        
        # 标准化查询文本（去除多余空格）
        normalized_query = " ".join(query.split()).lower()
        
        # 组合所有查询因子
        factors = {
            "query": normalized_query,
            "focus": sorted(focus_keywords or []),
            "domain": domain or "general",
            "version": "v1"  # 版本号，用于cache invalidation
        }
        
        # 转换为JSON并计算MD5
        factors_json = json.dumps(factors, sort_keys=True)
        fingerprint = hashlib.md5(factors_json.encode()).hexdigest()
        
        return fingerprint


class L1ProcessCache:
    """
    L1: 内存进程缓存
    
    特性：
      - 最快 (O(1) lookup)
      - 大小限制 ~100MB
      - 15分钟TTL
      - LRU驱逐策略
    """
    
    def __init__(self, max_size_mb: int = 100, ttl_seconds: int = 900):
        self.max_size_mb = max_size_mb
        self.ttl_seconds = ttl_seconds
        self.cache = OrderedDict()  # key -> (value, timestamp)
        self.size_bytes = 0
    
    def get(self, key: str) -> Optional[Any]:
        """查询缓存（若过期返回None）"""
        if key not in self.cache:
            return None
        
        value, timestamp = self.cache[key]
        
        # 检查TTL
        if time.time() - timestamp > self.ttl_seconds:
            del self.cache[key]
            self.size_bytes -= self._estimate_size(value)
            return None
        
        # LRU: 移到末尾
        self.cache.move_to_end(key)
        return value
    
    def set(self, key: str, value: Any):
        """设置缓存"""
        if key in self.cache:
            old_value, _ = self.cache[key]
            self.size_bytes -= self._estimate_size(old_value)
        
        self.cache[key] = (value, time.time())
        self.size_bytes += self._estimate_size(value)
        
        # LRU驱逐
        while self.size_bytes > self.max_size_mb * 1024 * 1024 and self.cache:
            oldest_key, oldest_value = self.cache.popitem(last=False)
            self.size_bytes -= self._estimate_size(oldest_value)
    
    def _estimate_size(self, obj: Any) -> int:
        """估算对象大小（字节）"""
        return len(json.dumps(obj, default=str).encode())


class L2SQLiteCache:
    """
    L2: SQLite持久缓存
    
    存储：
      - 检索结果 (retrieval_results)
      - 评分结果 (academic_scores)
      - Claim缓存 (claims_cache, 已有)
    
    特性：
      - 持久存储
      - 快速查询 (<20ms)
      - TTL自动更新
      - 大小自动清理（LRU）
    """
    
    def __init__(self, db_path: str = ".cache/query_results.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 检索结果表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS retrieval_results (
                    id INTEGER PRIMARY KEY,
                    query_fingerprint TEXT UNIQUE NOT NULL,
                    query TEXT,
                    results_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 1,
                    ttl_seconds INTEGER DEFAULT 86400
                )
            """)
            
            # 评分结果表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS academic_scores (
                    ...类似结构...
                )
            """)
            
            # 索引优化
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_retrieval_fingerprint
                ON retrieval_results(query_fingerprint)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_retrieval_accessed
                ON retrieval_results(accessed_at)
            """)
            
            conn.commit()
    
    def get(self, query_fingerprint: str) -> Optional[Dict]:
        """查询缓存"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT results_json, ttl_seconds, accessed_at
                    FROM retrieval_results
                    WHERE query_fingerprint = ?
                """, (query_fingerprint,))
                
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # 检查TTL
                created_at = datetime.fromisoformat(row["accessed_at"])
                if (time.time() - created_at.timestamp()) > row["ttl_seconds"]:
                    # 过期，删除
                    cursor.execute(
                        "DELETE FROM retrieval_results WHERE query_fingerprint = ?",
                        (query_fingerprint,)
                    )
                    conn.commit()
                    return None
                
                # 更新访问统计
                cursor.execute("""
                    UPDATE retrieval_results
                    SET accessed_at = CURRENT_TIMESTAMP,
                        access_count = access_count + 1
                    WHERE query_fingerprint = ?
                """, (query_fingerprint,))
                conn.commit()
                
                return json.loads(row["results_json"])
        
        except sqlite3.Error as e:
            logging.warning(f"L2 cache读取错误: {e}")
            return None
    
    def set(self, query_fingerprint: str, query: str, results: Dict,
            ttl_seconds: int = 86400):
        """保存缓存"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO retrieval_results
                    (query_fingerprint, query, results_json, ttl_seconds)
                    VALUES (?, ?, ?, ?)
                """, (query_fingerprint, query, json.dumps(results), ttl_seconds))
                
                conn.commit()
        
        except sqlite3.Error as e:
            logging.warning(f"L2 cache写入错误: {e}")
    
    def cleanup_expired(self):
        """清理过期缓存"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM retrieval_results
                WHERE datetime(accessed_at, '+' || ttl_seconds || ' seconds') < CURRENT_TIMESTAMP
            """)
            deleted = cursor.rowcount
            conn.commit()
        
        logging.info(f"L2 cache清理: 删除{deleted}条过期记录")


class L3MemPalaceCache:
    """
    L3: MemPalace长期记忆库
    
    存储：高置信度结果 (confidence > 0.8)
    
    特性：
      - 永久存储
      - 专注于高价值洞见
      - 支持相似查询的快速检索
      - 与M层MemPalace集成
    """
    
    def __init__(self, mempalace_adapter):
        self.mempalace = mempalace_adapter
    
    async def store_high_confidence_result(self, query: str, 
                                          results: Dict[str, Any],
                                          confidence: float):
        """
        存储高置信结果到MemPalace
        
        仅存储confidence > 0.8的结果
        """
        
        if confidence < 0.8:
            return
        
        # 构建存储对象
        memory_fact = {
            "query": query,
            "results": results,
            "confidence": confidence,
            "timestamp": time.time(),
            "type": "query_result"
        }
        
        # 调用MemPalace存储接口
        await self.mempalace.store_fact(memory_fact)
    
    async def retrieve_similar_results(self, query: str) -> Optional[Dict]:
        """
        检索相似查询的结果
        
        使用semantic similarity查找相似查询
        """
        
        similar_facts = await self.mempalace.find_similar_facts(
            query=query,
            fact_type="query_result",
            similarity_threshold=0.7
        )
        
        if similar_facts:
            return similar_facts[0]["results"]
        
        return None


class MultiLayerCacheManager:
    """
    三层缓存管理器
    
    统一管理L1、L2、L3缓存的查询和更新
    """
    
    def __init__(self, mempalace_adapter=None):
        self.l1 = L1ProcessCache(max_size_mb=100)
        self.l2 = L2SQLiteCache()
        self.l3 = L3MemPalaceCache(mempalace_adapter) if mempalace_adapter else None
        
        self.stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "l3_hits": 0,
            "misses": 0
        }
    
    async def get_cached_result(self, query: str, focus: list = None,
                               domain: str = None) -> Optional[Dict]:
        """
        多层缓存查询
        
        查询优先级：L1 → L2 → L3 → 实时计算
        """
        
        # 生成fingerprint
        fingerprint = QueryFingerprint.generate(query, focus, domain)
        
        # L1: 进程缓存
        result = self.l1.get(fingerprint)
        if result:
            self.stats["l1_hits"] += 1
            return result
        
        # L2: SQLite缓存
        result = self.l2.get(fingerprint)
        if result:
            self.stats["l2_hits"] += 1
            self.l1.set(fingerprint, result)  # 加载到L1
            return result
        
        # L3: MemPalace记忆
        if self.l3:
            result = await self.l3.retrieve_similar_results(query)
            if result:
                self.stats["l3_hits"] += 1
                # 更新L1和L2
                self.l1.set(fingerprint, result)
                self.l2.set(fingerprint, query, result)
                return result
        
        # Cache miss
        self.stats["misses"] += 1
        return None
    
    async def cache_result(self, query: str, result: Dict,
                          confidence: float = 0.5,
                          focus: list = None, domain: str = None):
        """
        缓存查询结果到三层
        """
        
        fingerprint = QueryFingerprint.generate(query, focus, domain)
        
        # L1: 进程缓存（总是）
        self.l1.set(fingerprint, result)
        
        # L2: SQLite缓存（总是）
        self.l2.set(fingerprint, query, result)
        
        # L3: MemPalace（仅高置信结果）
        if self.l3 and confidence > 0.8:
            await self.l3.store_high_confidence_result(query, result, confidence)
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        total = sum(self.stats.values())
        hit_rate = (total - self.stats["misses"]) / total if total > 0 else 0
        
        return {
            **self.stats,
            "total_queries": total,
            "hit_rate": f"{hit_rate*100:.1f}%",
            "l1_size_mb": self.l1.size_bytes / (1024*1024)
        }


# 集成到系统
# 文件: main_rag_workflow.py

class RAGWorkflow:
    def __init__(self, ...):
        ...
        self.cache_manager = MultiLayerCacheManager(
            mempalace_adapter=self.memory_adapter
        )
    
    async def query(self, user_query: str, focus: list = None) -> str:
        """
        改造的query方法，集成多层缓存
        """
        
        # Step 1: 尝试从缓存获取
        domain = self._identify_domain(focus)
        cached_result = await self.cache_manager.get_cached_result(
            user_query, focus, domain
        )
        
        if cached_result:
            logging.info(f"缓存命中: {user_query}")
            return cached_result["answer"]
        
        # Step 2: 实时计算（检索+评分+生成）
        retrieval_result = await self.retriever.search(user_query, focus)
        scoring_result = await self.scorer.score(retrieval_result)
        final_answer = await self.generator.generate(scoring_result)
        
        result = {
            "answer": final_answer,
            "retrieval": retrieval_result,
            "scoring": scoring_result
        }
        
        # Step 3: 缓存结果
        confidence = scoring_result.get("confidence", 0.5)
        await self.cache_manager.cache_result(
            user_query, result, confidence, focus, domain
        )
        
        return final_answer
    
    def print_cache_stats(self):
        """打印缓存统计"""
        stats = self.cache_manager.get_stats()
        print(f"""
        缓存统计:
          L1命中: {stats['l1_hits']}
          L2命中: {stats['l2_hits']}
          L3命中: {stats['l3_hits']}
          Cache Miss: {stats['misses']}
          命中率: {stats['hit_rate']}
          L1大小: {stats['l1_size_mb']:.1f}MB
        """)
```

### 📊 验收标准
- ✅ 热点查询响应时间 <100ms (L1命中)
- ✅ 冷流程查询 2-3s (L2/L3命中)
- ✅ 缓存整体命中率 ≥30%
- ✅ 内存占用增长 <5%
- ✅ 缓存键碰撞率 <0.01%

---

## 📊 总体时间投入与优先级

| 优化 | 预计时间 | 难度 | ROI | 优先级 |
|-----|--------|------|-----|--------|
| P0 权重自适应 | 5-7天 | ⭐⭐ 中 | ⭐⭐⭐⭐⭐ 极高 | 1️⃣ |
| P1 流水线并行 | 10-14天 | ⭐⭐⭐ 中高 | ⭐⭐⭐⭐⭐ 极高 | 2️⃣ |
| P2 冲突修复 | 7-10天 | ⭐⭐ 中 | ⭐⭐⭐⭐ 高 | 3️⃣ |
| P3 批处理自适应 | 7-10天 | ⭐⭐ 中 | ⭐⭐⭐⭐ 高 | 4️⃣ |
| P4 缓存双层 | 7-10天 | ⭐⭐⭐ 中高 | ⭐⭐⭐ 中高 | 5️⃣ |

**总计**: 36-51天 = 5-8周 (按序列)
**并行策略**: P1/P2/P3可部分并行 → 3-4周完成全部

---

## ✅ 使用指南

1. **从Gemini提示词开始**：复制相应的提示词，粘贴到Gemini获取初步思路
2. **参考技术规范**：查看伪代码理解实现细节
3. **定制化调整**：根据实际项目情况修改参数和算法
4. **集成到项目**：按照指定的文件路径修改或新建文件

每个优化方向都已包含：✅ 问题分析 + ✅ 解决方案 + ✅ 伪代码 + ✅ 验收标准

准备好开始实施了吗？👈
