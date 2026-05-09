# P3 阶段规划：交叉验证与因果推演框架

**规划日期**: 2026-04-11  
**预计工时**: 4-5 天  
**预计成本**: $5-15 USD  
**目标**: 知识图谱推演与多源证据验证

---

## 📋 目录

1. [P3 目标定义](#p3-目标定义)
2. [核心能力](#核心能力)
3. [算法设计](#算法设计)
4. [实现路线图](#实现路线图)
5. [验收标准](#验收标准)

---

## P3 目标定义

### 问题陈述

P1 提供了**检索能力**（Recall>0.70）  
P2 提供了**冲突识别能力**（Conflict Detection）  

**P3 的目标**: 从认知单个冲突 → **理解整体的因果逻辑体系**

### 具体任务

```
输入: 单条用户查询
  例: "激光功率如何通过焊接工艺影响钛合金焊缝质量？"

P3 处理流程:
  1. 多源证据收集 (使用 P2 的冲突报告)
  2. 因果关系抽取 (A→B→C 链路)
  3. 证据交叉验证 (多文献对照，权重对齐)
  4. 冲突消解 (利用 P2 的权威性评分)
  5. 推演链可视化 (DAG + Confidence 标注)

输出: 结构化推演报告
  {
    "claim": "激光功率通过影响熔池温度进而影响焊缝质量",
    "causal_chain": [影响因子 A] → [中间过程 B] → [最终效果 C],
    "confidence": 0.82,
    "supporting_evidence": [...],
    "contradictions": [...],
    "unknown_gaps": [...]
  }
```

### 核心价值

```
当前 (P2) → P3
────────────────────
"论文 A 说 X,
 论文 B 说 ¬X,     →  "根据权威性评估，
 无法判断"             X 的因果机制是...
                      且我们在 [时间段] 
                      有知识缺口"
```

---

## 核心能力

### 1️⃣ 多源证据对照 (Evidence Triangulation)

**目标**: 从多个独立源获得对同一事实的验证

**算法**:
```python
def triangulate_evidence(claim: str, sources: List[Claim]) -> Dict:
    """
    多源对照验证
    
    输入:
      claim = "激光功率增加 → 焊缝强度增加"
      sources = [来自论文 A、B、C 的相关声明]
    
    输出:
      {
        "claim": "激光功率增加 → 焊缝强度增加",
        "evidence_count": 3,
        "sources": [
          {"paper": "A", "agreement": True, "strength": 0.9},
          {"paper": "B", "agreement": True, "strength": 0.85},
          {"paper": "C", "agreement": False, "caveat": "仅在 X 条件下成立"}
        ],
        "consensus_confidence": 0.75,
        "consensus_type": "QUALIFIED_AGREEMENT"
      }
    """
    
    results = {
        "claim": claim,
        "sources": [],
        "agreement_count": 0,
        "disagreement_count": 0
    }
    
    for source in sources:
        agreement = semantic_similarity(claim, source.evidence_text)
        results["sources"].append({
            "paper": source.source.doc_id,
            "agreement": agreement > 0.7,
            "confidence": agreement,
            "authority_score": source.source.authority_score
        })
        
        if agreement > 0.7:
            results["agreement_count"] += 1
        else:
            results["disagreement_count"] += 1
    
    # 加权共识：考虑文献权威性
    weighted_agreement = sum(
        s["confidence"] * s["authority_score"]
        for s in results["sources"]
    ) / len(results["sources"])
    
    results["consensus_confidence"] = weighted_agreement
    return results
```

### 2️⃣ 因果链路追踪 (Causal Chain Extraction)

**目标**: 从声明序列中提取 A→B→C→...的因果链

**算法**:
```python
@dataclass
class CausalEdge:
    source: str           # 原因 (如: 激光功率)
    target: str           # 结果 (如: 熔深)
    mechanism: str        # 机制 (如: 熔池温度)
    confidence: float     # 置信度
    evidences: List[Claim]

def extract_causal_chain(claims: List[Claim]) -> List[CausalEdge]:
    """
    从声明集合中提取因果链
    
    示例:
    声明1: "激光功率 影响 熔池温度"
    声明2: "熔池温度 影响 冷却速率"
    声明3: "冷却速率 影响 焊缝组织"
    声明4: "焊缝组织 影响 机械性能"
    
    提取的因果链:
      激光功率 → 熔池温度 → 冷却速率 → 焊缝组织 → 机械性能
    """
    
    # 步骤 1: 建立实体-实体的有向图
    graph = defaultdict(list)
    for claim in claims:
        edge = CausalEdge(
            source=claim.subject,
            target=claim.object,
            mechanism=normalize_mechanism(claim),
            confidence=claim.confidence,
            evidences=[claim]
        )
        graph[claim.subject].append(edge)
    
    # 步骤 2: 深度优先搜索寻找最长链
    longest_chains = []
    for start_node in graph.keys():
        chain = dfs_find_longest_path(graph, start_node)
        if len(chain) > 2:  # 至少 3 个链节
            longest_chains.append(chain)
    
    # 步骤 3: 链验证 (确保没有循环, 置信度逐级累积)
    verified_chains = [verify_chain(c) for c in longest_chains]
    return sorted(verified_chains, key=lambda x: x.overall_confidence, reverse=True)

def verify_chain(chain: List[CausalEdge]) -> CausalChain:
    """
    验证因果链的有效性
    
    检查项:
    1. 无循环
    2. 置信度递减合理 (不能太陡峭)
    3. 机制解释一致 (不能自相矛盾)
    """
    ...
```

### 3️⃣ 知识一致性检验 (Consistency Validation)

**目标**: 检查整体知识体系中的逻辑一致性

**算法**:
```python
class ConsistencyValidator:
    """
    多维度一致性检查
    """
    
    def validate_temporal_consistency(
        self,
        chains: List[CausalChain],
        entity_timeline: Dict
    ) -> Dict:
        """
        时间一致性检查
        
        问题: 2020 年的观点与 2024 年的观点是否一致？
        
        案例:
          2020 年: "钛合金易产生热裂纹"
          2024 年: "新工艺消除了热裂纹"
          
        判断: EVOLUTION (技术进步) ✓ 而非 CONTRADICTION ✗
        """
        inconsistencies = []
        
        for chain in chains:
            for edge in chain.edges:
                # 检查该因果关系是否在不同时期有不同表述
                time_variants = []
                for evidence in edge.evidences:
                    time_variants.append({
                        'year': evidence.source.year,
                        'confidence': evidence.confidence,
                        'text': evidence.evidence_text
                    })
                
                if len(set(v['year'] for v in time_variants)) > 1:
                    # 存在时间变异，需要判断是演变还是矛盾
                    variance_type = self._classify_time_variance(time_variants)
                    if variance_type == "CONTRADICTION":
                        inconsistencies.append({
                            'edge': edge,
                            'type': 'TEMPORAL_CONTRADICTION',
                            'variants': time_variants
                        })
        
        return {'temporal_inconsistencies': inconsistencies}
    
    def validate_mechanistic_consistency(
        self,
        chains: List[CausalChain]
    ) -> Dict:
        """
        机制一致性检查
        
        问题: 同一个中间变量是否有相矛盾的作用？
        
        案例:
          链1: 功率 → 热量 → 熔深增加
          链2: 功率 → 热量 → 冷却速率降低 → 脆性增加
          
        检验: 热量既增加熔深又增加脆性？ 
               → 需要量化范围 (如: 低热量→脆性, 中等热量→深度, 高热量→脆性)
        """
        
        mechanism_effects = defaultdict(list)
        for chain in chains:
            for edge in chain.edges:
                mechanism_effects[edge.mechanism].append({
                    'source': edge.source,
                    'target': edge.target,
                    'confidence': edge.confidence
                })
        
        inconsistencies = []
        for mechanism, effects in mechanism_effects.items():
            # 检查同一机制是否指向相反的结果
            targets = set(e['target'] for e in effects)
            if len([e for e in effects if "增加" in e['target']]) > 0 and \
               len([e for e in effects if "减少" in e['target']]) > 0:
                # 可能矛盾
                inconsistencies.append({
                    'mechanism': mechanism,
                    'conflicting_targets': list(targets),
                    'severity': 'MEDIUM'
                })
        
        return {'mechanistic_inconsistencies': inconsistencies}
```

### 4️⃣ 冲突消解与决策（Conflict Resolution）

**目标**: 当存在矛盾时，给出权威性考虑下的"最佳判断"

**算法**:
```python
def resolve_conflicts(
    conflict_pairs: List[Tuple[CausalEdge, CausalEdge]],
    p2_authority_scores: Dict[str, float]
) -> Dict:
    """
    基于文献权威性的冲突消解
    
    输入:
      conflict_pairs = [
        (Edge1: "高功率→高熔深", Edge2: "高功率→低熔深")
      ]
      p2_authority_scores = {"DOC-2022": 0.92, "DOC-2024": 0.78}
    
    输出:
      {
        "primary_claim": "高功率→高熔深",
        "supporting_evidence": 15 篇 (IF≥2.0),
        "conflicting_evidence": 2 篇 (IF<2.0),
        "confidence": 0.88,
        "caveats": ["在超高功率(>2000W)时可能发生非单调效应"],
        "recommended_action": "采用 Edge1,但需要在高功率条件下验证"
      }
    """
    
    resolution = {}
    
    for edge1, edge2 in conflict_pairs:
        # 计算每条边的"权威性权重"
        weight1 = sum(
            p2_authority_scores.get(e.source.doc_id, 0.5)
            for e in edge1.evidences
        ) / len(edge1.evidences)
        
        weight2 = sum(
            p2_authority_scores.get(e.source.doc_id, 0.5)
            for e in edge2.evidences
        ) / len(edge2.evidences)
        
        # 选择权重更高的边作为主张
        if weight1 > weight2:
            primary_edge = edge1
            conflicting_edge = edge2
        else:
            primary_edge = edge2
            conflicting_edge = edge1
        
        # 生成建议
        resolution[f"{edge1.source}→{edge1.target}"] = {
            "primary_claim": str(primary_edge),
            "supporting_count": len(primary_edge.evidences),
            "conflicting_count": len(conflicting_edge.evidences),
            "confidence": max(weight1, weight2),
            "recommendation": f"采用主张:{primary_edge.source}→{primary_edge.target}"
                            f",但需要关注 {conflicting_edge.source}→{conflicting_edge.target} 的边界条件"
        }
    
    return resolution
```

### 5️⃣ 推演链可视化（Visualization）

**数据结构**:
```python
@dataclass
class InferenceDAG:
    """推演有向无环图"""
    nodes: List[str]              # 实体节点
    edges: List[CausalEdge]       # 因果边
    node_confidence: Dict[str, float]  # 节点置信度
    edge_confidence: Dict[str, float]  # 边置信度
    conflicts: List[Dict]         # 冲突标注
    
    def to_graphviz(self) -> str:
        """生成 Graphviz DOT 格式用于可视化"""
        ...
    
    def to_json(self) -> Dict:
        """生成 JSON 用于前端展示"""
        ...

# 输出示例 (JSON)
{
  "query": "激光功率如何影响焊缝质量",
  "nodes": [
    {"id": "激光功率", "type": "input", "confidence": 1.0},
    {"id": "熔池温度", "type": "intermediate", "confidence": 0.92},
    {"id": "冷却速率", "type": "intermediate", "confidence": 0.85},
    {"id": "焊缝组织", "type": "intermediate", "confidence": 0.80},
    {"id": "机械性能", "type": "output", "confidence": 0.75}
  ],
  "edges": [
    {"source": "激光功率", "target": "熔池温度", "confidence": 0.92, "mechanism": "直接加热"},
    {"source": "熔池温度", "target": "冷却速率", "confidence": 0.85, "mechanism": "热梯度影响"},
    ...
  ],
  "conflicts": [
    {
      "type": "QUANTITATIVE_NONLINEARITY",
      "description": "在功率>2000W 时,关系可能发生反转",
      "severity": "MEDIUM"
    }
  ],
  "overall_confidence": 0.82
}
```

---

## 实现路线图

### 🏃 第一阶段: 多源对照框架（Day 1）

**任务**:
- [ ] 定义 `CausalEdge`, `CausalChain`, `InferenceDAG` 数据结构
- [ ] 实现多源证据对照算法
- [ ] 实现加权共识计算

**交付**: `p3_evidence_triangulation.py`

**成果**:
```python
triangulator = EvidenceTriangulator(p2_conflicts)
result = triangulator.triangulate(claim, sources)
# output: {"consensus_confidence": 0.82, "sources": [...]}
```

---

### 🔗 第二阶段: 因果链抽取（Day 2）

**任务**:
- [ ] 实现图构造算法 (实体→实体)
- [ ] 实现最长路径搜索
- [ ] 实现链验证逻辑

**交付**: `p3_causal_chain_extractor.py`

**成果**:
```python
extractor = CausalChainExtractor()
chains = extractor.extract(claims_list)
# output: [
#   CausalChain(edges=[A→B, B→C, C→D]),
#   ...
# ]
```

---

### ✔️ 第三阶段: 一致性检验（Day 3）

**任务**:
- [ ] 实现时间一致性检查
- [ ] 实现机制一致性检查
- [ ] 实现冲突消解算法

**交付**: `p3_consistency_validator.py`

**成果**:
```python
validator = ConsistencyValidator()
inconsistencies = validator.validate(chains, entity_timeline)
# output: {
#   "temporal": [...],
#   "mechanistic": [...],
#   "resolutions": [...]
# }
```

---

### 📊 第四阶段: 推演 DAG 构造（Day 4）

**任务**:
- [ ] 集成多源对照 + 因果链 + 一致性检验
- [ ] 生成最终推演有向图
- [ ] 实现 Graphviz 和 JSON 输出

**交付**: `p3_inference_dag_builder.py`

**成果**:
```python
builder = InferenceDAGBuilder()
dag = builder.build(query, p1_results, p2_conflicts)
print(dag.to_graphviz())  # 可视化
json_output = dag.to_json()  # 前端展示
```

---

### 🧪 第五阶段: 测试与优化（Day 5）

**任务**:
- [ ] 单元测试 (多源对照、因果链、一致性)
- [ ] E2E 集成测试
- [ ] 性能优化与成本确认

**交付**: `test_p3_inference.py`

---

## 验收标准

| 标准 | 指标 | 目标 | 方法 |
|------|------|------|------|
| **多源对照准确度** | Precision | > 0.80 | 人工标注 20 条查询 |
| **因果链抽取完整度** | Recall | > 0.75 | 检查遗漏的链接 |
| **一致性检验有效性** | F1-Score | > 0.80 | 在冲突检测中验证 |
| **推演置信度** | 平均值 | > 0.75 | 在 eval_queries 上评分 |
| **性能指标** | 处理时间 | < 5 min/query | 测量 100 条查询 |
| **成本控制** | 总成本 | < $15 | 跟踪 LLM + API 调用 |

---

## P3 对后续的支持

### 可用于 P4 (如果需要)

```
P4 可能目标: "知识图谱持久化与实时更新"
- 使用 P3 的 InferenceDAG 作为图结构
- 使用 P3 的冲突消解作为更新冲突处理

或 P4 目标: "多查询知识聚合"
- 将多个 P3 推演 DAG 进行聚合
- 识别跨查询的共同因果路径
```

---

## 关键决策点 (待用户确认)

> **问题 1**: 是否需要实时的文献数据更新？  
> 建议: 目前使用静态数据 (P1 索引)，后续可考虑增量更新

> **问题 2**: 对于高度复杂的图 (100+ 个节点)，是否需要简化展示？  
> 建议: 支持"子图聚类展示"，用户可逐层钻取

> **问题 3**: 推演 DAG 的格式是否需要标准化 (如 RDF 或 Knowledge Graph)?  
> 建议: 目前使用 JSON + Graphviz，支持后续转换

---

**P3 规划完成 ✅ — 等待用户确认是否启动**
