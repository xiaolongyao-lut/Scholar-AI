# P3 深化版执行规划 | 交付给 Gemini

**计划日期**: 2026-04-11  
**执行时间**: 2026-04-16 ~ 04-20 (5-5.5 天)  
**选择版本**: 🚀 **深化版 P3** (完整系统)  
**执行者**: Gemini (AI Agent)  
**输入质量**: 优化后 P1-P2 (准确度 92%, 成本 -90%)

---

## 📋 目录

1. [核心能力定义](#核心能力定义)
2. [详细实现方案](#详细实现方案)
3. [5 天执行路线图](#5-天执行路线图)
4. [核心算法设计](#核心算法设计)
5. [测试和验收](#测试和验收)
6. [交付物清单](#交付物清单)

---

## 核心能力定义

### 简化版 5 个核心能力

```
Tier 1 (基础能力):
  1️⃣ 多源证据对照 (Evidence Triangulation)
  2️⃣ 因果链路追踪 (Causal Chain Extraction)
  3️⃣ 知识一致性检验 (Consistency Validation)

Tier 2 (决策能力):
  4️⃣ 冲突消解决策 (Conflict Resolution)
  5️⃣ 推演 DAG 生成 (Inference DAG Generation)
```

### 新增 4 个高级能力 (深化版独有)

```
Tier 3 (智能化):
  6️⃣ 跨查询知识聚合 (Cross-Query Aggregation) ← NEW
  7️⃣ 动态增量更新 (Dynamic Incremental Update) ← NEW

Tier 4 (可视化和导出):
  8️⃣ 前端交互可视化 (Interactive Visualization) ← NEW
  9️⃣ 知识图谱导出 (Knowledge Graph Export) ← NEW
```

---

## 详细实现方案

### 能力 1️⃣: 多源证据对照 (Evidence Triangulation)

**目标**: 从多个来源对同一个因果关系进行交叉验证

**输入**:
```python
{
  "query": "激光功率如何影响焊缝熔深？",
  "retrieved_papers": [
    {
      "title": "Laser Welding of TC4",
      "claims": [Claim(subject="激光功率", predicate="增加", object="熔深")],
      "source_meta": SourceMeta(year=2023, IF=2.5, citations=25)
    },
    ...
  ]
}
```

**处理逻辑**:
```python
class EvidenceTriangulation:
    """多源证据对照"""
    
    def triangulate(self, claims: List[Claim]) -> List[EvidenceSet]:
        """
        1. 按 (subject, predicate, object) 三元组聚类
        2. 对每个三元组，收集所有支持证据
        3. 计算证据强度 (基于 IF, 被引数, 年份)
        4. 生成对照报告
        """
        
        # 步骤 1: 聚类相似三元组
        triplets = defaultdict(list)
        for claim in claims:
            key = (claim.subject.canonicalize(), 
                   claim.predicate.canonicalize(), 
                   claim.object.canonicalize())
            triplets[key].append(claim)
        
        # 步骤 2: 对每个三元组计算证据强度
        evidence_sets = []
        for (s, p, o), claims_list in triplets.items():
            # 证据强度 = IF * 0.4 + Citations * 0.3 + Recency * 0.3
            strength_scores = [
                c.source.impact_factor * 0.4 + 
                min(c.source.citation_count / 100, 5) * 0.3 +
                (2024 - c.source.year) / 20 * 0.3
                for c in claims_list
            ]
            
            evidence_set = EvidenceSet(
                claim_triplet=(s, p, o),
                supporting_claims=claims_list,
                total_strength=sum(strength_scores),
                avg_strength=np.mean(strength_scores),
                consensus_level=self._calculate_consensus(claims_list)
            )
            evidence_sets.append(evidence_set)
        
        return evidence_sets

    def _calculate_consensus(self, claims: List[Claim]) -> str:
        """计算共识水平"""
        if len(claims) >= 5:
            return "STRONG"  # 5+ 篇同意
        elif len(claims) >= 3:
            return "MODERATE"  # 3-4 篇同意
        else:
            return "WEAK"  # 1-2 篇
```

**输出**:
```json
{
  "evidence_sets": [
    {
      "triplet": ["激光功率", "增加", "焊缝熔深"],
      "supporting_papers": 8,
      "consensus_level": "STRONG",
      "total_strength": 18.5,
      "citations": "Zhang et al. 2023, Li et al. 2024, ..."
    }
  ]
}
```

**工期**: 2 小时

---

### 能力 2️⃣: 因果链路追踪 (Causal Chain Extraction)

**目标**: 从多个声明构建因果链条

**例子**:
```
激光功率 → 熔池温度 → 冷却速率 → 焊缝组织 → 焊缝韧性
```

**处理逻辑**:
```python
class CausalChainExtractor:
    """因果链路提取"""
    
    def extract_chains(self, triplets: List[Tuple], 
                      conflict_map: Dict) -> List[CausalChain]:
        """
        1. 构建因果图 (有向无环图 DAG)
        2. 识别因果人物的端点 (source 和 sink)
        3. 沿 DAG 路径进行深度优先搜索
        4. 提取所有有效因果链
        """
        
        # 构建图
        graph = defaultdict(list)  # node → neighbors
        for (s, p, o) in triplets:
            # 边: s -p-> o
            graph[s].append((o, p))
        
        # DFS 找所有路径
        chains = []
        for start_node in graph:
            if self._is_source_node(start_node, graph):
                paths = self._dfs_paths(start_node, graph, max_depth=6)
                for path in paths:
                    chain = self._path_to_chain(path, triplets)
                    chains.append(chain)
        
        return chains
    
    def _dfs_paths(self, start, graph, max_depth=6, 
                  current_path=None, current_depth=0):
        """DFS 遍历找路径"""
        if current_path is None:
            current_path = [start]
        
        if current_depth >= max_depth:
            return [current_path]
        
        if start not in graph:
            return [current_path]
        
        paths = []
        for next_node, relation in graph[start]:
            if next_node not in current_path:  # 避免环
                new_path = current_path + [next_node]
                paths.extend(
                    self._dfs_paths(next_node, graph, max_depth,
                                  new_path, current_depth + 1)
                )
        
        return paths or [current_path]

class CausalChain:
    """因果链数据结构"""
    
    def __init__(self, nodes: List[str], edges: List[Tuple]):
        self.nodes = nodes  # [激光功率, 熔池温度, 冷却速率, ...]
        self.edges = edges  # [(激光功率→熔池温度, 增加), ...]
        self.length = len(nodes) - 1
        self.confidence = self._calculate_confidence()
    
    def _calculate_confidence(self) -> float:
        """链的整体可信度"""
        # 基于每条边的证据强度
        if self.length == 0:
            return 1.0
        return 0.95 ** (self.length - 1)  # 链越长，可信度衰减
```

**输出**:
```json
{
  "causal_chains": [
    {
      "chain": ["激光功率", "熔池温度", "冷却速率", "焊缝组织"],
      "relations": ["增加", "增加", "加快"],
      "confidence": 0.78,
      "evidence_count": 5,
      "literature_support": "Zhang 2023, Li 2024, Wang 2022"
    }
  ]
}
```

**工期**: 3 小时

---

### 能力 3️⃣: 一致性检验 (Consistency Validation)

**目标**: 检验不同因果链间的一致性

**处理逻辑**:
```python
class ConsistencyValidator:
    """一致性检验"""
    
    def validate(self, chains: List[CausalChain],
                conflicts: List[ClassifiedConflict]):
        """
        1. 提取每条链的结论
        2. 检查是否与已知冲突相符
        3. 识别逻辑矛盾
        4. 生成一致性评分
        """
        
        validation_results = []
        
        for i, chain_a in enumerate(chains):
            for j, chain_b in enumerate(chains[i+1:], i+1):
                # 检查两条链是否在共同部分一致
                consistency = self._check_consistency(chain_a, chain_b, conflicts)
                
                if consistency < 0.5:
                    validation_results.append({
                        "chain_a": chain_a,
                        "chain_b": chain_b,
                        "consistency_score": consistency,
                        "issue": "CONFLICTING_PATHS",
                        "recommendation": "需要人工审查"
                    })
        
        return validation_results

# 一致性评分算法:
#   - 完全一致: 1.0 (100%)
#   - 大部分一致: 0.7-0.9 (轻微差异)
#   - 部分冲突: 0.3-0.7 (条件不同)
#   - 完全冲突: 0-0.3 (<30%)
```

**工期**: 2 小时

---

### 能力 4️⃣: 冲突消解 (Conflict Resolution)

**目标**: 对检测到的冲突进行消解和解释

**处理逻辑**:
```python
class ConflictResolver:
    """冲突消解"""
    
    def resolve(self, conflicts: List[ClassifiedConflict],
               evidence_sets: List[EvidenceSet]) -> List[Resolution]:
        """
        冲突消解的三个策略:
        
        1. 证据权重判定 (Evidentiary Hierarchy)
           - 高被引 + 新论文 优先
           - 元数据完整的优先
        
        2. 条件细化 (Condition Refinement)
           - 冲突可能是由于条件不同
           - 例: "激光功率增加熔深" vs "激光功率过高导致气孔"
                 → 条件不同: 功率 800W vs 功率 >1200W
        
        3. 时间演变判定 (Temporal Evolution)
           - 新观点逐步取代旧观点
           - 例: 2019 结论 vs 2024 最新研究
        """
        
        resolutions = []
        
        for conflict in conflicts:
            resolution = Resolution()
            
            # 策略 1: 权重比对
            primary_claim = self._select_by_authority(
                conflict.claims_involved
            )
            resolution.primary_claim = primary_claim
            
            # 策略 2: 条件分析
            condition_analysis = self._analyze_conditions(
                conflict.claims_involved
            )
            if condition_analysis['are_conditions_different']:
                resolution.type = "CONDITIONAL_DIFFERENCE"
                resolution.explanation = f"两项声明在不同条件下成立。{primary_claim.context}"
            
            # 策略 3: 时间演变判定
            temporal_info = self._analyze_temporal(
                conflict.claims_involved
            )
            if temporal_info['is_evolution']:
                resolution.type = "TEMPORAL_EVOLUTION"
                resolution.explanation = f"从 {temporal_info['old_consensus']} 演变к {temporal_info['new_consensus']}"
                resolution.recommendation = f"优先采用 {temporal_info['newer_consensus']} (年份更新)"
            
            resolutions.append(resolution)
        
        return resolutions
```

**输出**:
```json
{
  "resolutions": [
    {
      "conflict_id": "CF-12345",
      "type": "TEMPORAL_EVOLUTION",
      "resolution": "接受 2024 研究结论",
      "evidence_weight": "新研究 (IF=3.2, 20引用) > 旧研究 (IF=2.0, 10引用)",
      "recommendation": "在相同条件下优先采用新结论"
    }
  ]
}
```

**工期**: 2 小时

---

### 能力 5️⃣: 推演 DAG 生成 (Inference DAG)

**目标**: 将所有因果链聚合为统一的有向无环图

**处理逻辑**:
```python
class DAGBuilder:
    """DAG 构造"""
    
    def build_dag(self, chains: List[CausalChain],
                 resolutions: List[Resolution]) -> DAG:
        """
        1. 合并所有链的节点和边
        2. 应用冲突消解结果
        3. 添加置信度和支持数据
        4. 生成最终的统一图
        """
        
        dag = DAG()
        
        # 添加节点
        for chain in chains:
            for node in chain.nodes:
                if node not in dag.nodes:
                    dag.add_node(node, confidence=0.8)
        
        # 添加边，并标注置信度
        edge_map = defaultdict(list)  # (s, o) → [relations]
        
        for chain in chains:
            for i, node_a in enumerate(chain.nodes[:-1]):
                node_b = chain.nodes[i+1]
                relation = chain.edges[i]
                edge_map[(node_a, node_b)].append(relation)
        
        for (s, o), relations in edge_map.items():
            # 多个支持证据 → 置信度更高
            confidence = min(0.7 + 0.3 * len(relations) / 5, 1.0)
            dag.add_edge(s, o, relations=relations, confidence=confidence)
        
        # 应用冲突消解 (移除或降低置信度不足的边)
        for resolution in resolutions:
            if resolution.type == "TEMPORAL_EVOLUTION":
                dag.upgrade_edge(resolution.primary_claim)
        
        return dag
```

**输出**: 完整的 DAG 数据结构，包含所有节点和边的置信度

**工期**: 1.5 小时

---

### 能力 6️⃣: 跨查询知识聚合 (Cross-Query Aggregation) ⭐ NEW

**目标**: 从 100 条查询的推演结果中提炼"焊接领域的因果知识库"

**处理逻辑**:
```python
class CrossQueryAggregator:
    """跨查询知识聚合"""
    
    def aggregate(self, all_dags: List[DAG]) -> KnowledgeBase:
        """
        1. 收集所有查询的 DAG
        2. 计算高频因果路径 (出现 >50% 查询)
        3. 生成"焊接领域的标准因果关系库"
        """
        
        # 统计边频度
        edge_frequency = defaultdict(int)
        total_dags = len(all_dags)
        
        for dag in all_dags:
            for edge in dag.get_all_edges():
                edge_frequency[edge] += 1
        
        # 筛选高频边 (出现频度 > 50%)
        high_frequency_edges = {
            edge: freq for edge, freq in edge_frequency.items()
            if freq / total_dags > 0.5
        }
        
        # 构建知识库
        kb = KnowledgeBase()
        kb.add_standard_causal_patterns(high_frequency_edges)
        kb.metadata = {
            "generated_from_queries": total_dags,
            "pattern_count": len(high_frequency_edges),
            "average_confidence": sum(
                edge.confidence for edge in high_frequency_edges.values()
            ) / len(high_frequency_edges),
            "generation_time": datetime.now()
        }
        
        return kb
```

**例子**:
```
Input: 100 条不同查询的 DAG

Output: 高频因果模板库
  ├─ 模板 1: параметр → 微观组织 → 力学性能 (出现 87 次)
  ├─ 模板 2: 热输入 → 热影响区 → 晶粒长大 (出现 76 次)
  ├─ 模板 3: 冷却速率 → 相变 → 硬度 (出现 64 次)
  └─ ...
```

**工期**: 2 小时

---

### 能力 7️⃣: 动态增量更新 (Dynamic Incremental Update) ⭐ NEW

**目标**: 支持新论文的自动集成和过期知识的自动淘汰

**处理逻辑**:
```python
class DynamicUpdater:
    """动态增量更新"""
    
    def update_with_new_paper(self, existing_kb: KnowledgeBase,
                              new_paper: Paper) -> KnowledgeBase:
        """
        1. 从新论文提取新的因果声明
        2. 检测与现有知识库的冲突
        3. 更新权重和置信度
        4. 淘汰过期知识 (>5 年)
        """
        
        # 步骤 1: 提取新论文的声明
        new_claims = self.extract_paper_claims(new_paper)
        
        # 步骤 2: 冲突检测
        conflicts = self.detect_conflicts(new_claims, existing_kb)
        
        for conflict in conflicts:
            # 冲突消解: 比较权威性
            new_authority = self._calculate_authority(new_paper)
            old_authority = self._calculate_authority(conflict.existing_paper)
            
            if new_authority > old_authority:
                # 新论文权威性更高，更新
                existing_kb.update_edge(
                    conflict,
                    new_weight=new_authority
                )
                logger.info(f"更新: {conflict}, 权重 {new_authority:.2f}")
            else:
                # 旧知识保留，但降低新论文的权重
                new_claims = [c for c in new_claims 
                             if c not in conflict.claims]
        
        # 步骤 3: 添加新的非冲突声明
        for claim in new_claims:
            existing_kb.add_edge(claim)
        
        # 步骤 4: 淘汰过期知识 (超过 5 年)
        existing_kb.remove_stale_edges(max_age=5)
        
        return existing_kb
```

**工期**: 2.5 小时

---

### 能力 8️⃣: 前端可视化 (Interactive Visualization) ⭐ NEW

**目标**: 基于 D3.js 的交互式因果关系图

**前端架构**:
```
├─ index.html (框架)
├─ styles.css (美化)
└─ visualization.js (D3.js 交互)

核心功能:
  1. 节点展示: 圆形节点，大小表示影响度
  2. 边展示: 箭头表示因果方向，颜色表示置信度
  3. 交互:
     - 鼠标悬停: 显示相关论文
     - 点击钻取: 展开节点的详细信息
     - 拖拽调整: 重新布局
  4. 筛选: 按置信度、年份等筛选显示的边
```

**前端代码示例**:
```javascript
// visualization.js
class CausalGraphVisualizer {
    constructor(containerSelector, dagData) {
        this.svg = d3.select(containerSelector).append("svg")
            .attr("width", 1200)
            .attr("height", 800);
        
        this.force = d3.forceSimulation()
            .force("link", d3.forceLink().id(d => d.id).distance(100))
            .force("charge", d3.forceManyBody().strength(-500))
            .force("center", d3.forceCenter(600, 400));
        
        this.render(dagData);
    }
    
    render(dagData) {
        // 添加节点
        const nodes = this.svg.selectAll(".node")
            .data(dagData.nodes)
            .enter()
            .append("circle")
            .attr("class", "node")
            .attr("r", d => 10 + d.importance * 20)
            .on("click", d => this.showNodeDetails(d));
        
        // 添加边
        const links = this.svg.selectAll(".link")
            .data(dagData.edges)
            .enter()
            .append("line")
            .attr("class", "link")
            .attr("stroke-width", d => 1 + d.confidence * 3);
        
        // 力导向布局
        this.force.nodes(dagData.nodes)
                 .force("link").links(dagData.edges);
        
        this.force.on("tick", () => {
            links.attr("x1", d => d.source.x)
                 .attr("y1", d => d.source.y)
                 .attr("x2", d => d.target.x)
                 .attr("y2", d => d.target.y);
            
            nodes.attr("cx", d => d.x)
                 .attr("cy", d => d.y);
        });
    }
    
    showNodeDetails(node) {
        // 显示钻取面板: 相关论文、支持度等
        d3.select("#details-panel")
            .html(`
                <h3>${node.name}</h3>
                <p>支持论文: ${node.literatureCount}</p>
                <ul>${node.references.map(r => `<li>${r}</li>`).join('')}</ul>
            `);
    }
}
```

**工期**: 4 小时

---

### 能力 9️⃣: 知识图谱导出 (Knowledge Graph Export) ⭐ NEW

**目标**: 将 DAG 导出为标准格式 (RDF/JSON-LD/Cypher)

**导出格式**:

#### RDF Turtle 格式
```turtle
@prefix welding: <http://welding.knowlwdge.org/> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .

welding:LaserPower rdf:type owl:Class ;
    rdfs:label "激光功率"@zh ;
    rdfs:comment "激光焊接装置中的功率参数" .

welding:increases rdf:type owl:ObjectProperty ;
    rdfs:label "增加" ;
    rdfs:domain welding:Parameter ;
    rdfs:range welding:Property .

welding:LaserPower welding:increases welding:MeltPoolDepth ;
    dc:source "Zhang et al. 2023" ;
    welding:confidence 0.92 ;
    welding:frequency 0.87 .
```

#### JSON-LD 格式
```json
{
  "@context": {
    "welding": "http://welding.knowledge.org/",
    "increases": {"@id": "welding:increases", "@type": "@id"},
    "confidence": "welding:confidence"
  },
  "@graph": [
    {
      "@id": "welding:LaserPower",
      "@type": "welding:Parameter",
      "welding:name": "激光功率",
      "increases": "welding:MeltPoolDepth",
      "confidence": 0.92
    }
  ]
}
```

#### Neo4j Cypher
```cypher
CREATE (lp:Parameter {name: "激光功率", type: "PROCESS_PARAM"})
CREATE (md:Property {name: "焊缝熔深", type: "WELD_PROPERTY"})
CREATE (lp)-[r:INCREASES {confidence: 0.92, sources: 8, frequency: 0.87}]->(md)
CREATE (lp)-[s:SOURCE {paper: "Zhang et al. 2023", year: 2023}]->(md)
```

**实现**:
```python
class KnowledgeGraphExporter:
    """知识图谱导出"""
    
    def export_to_rdf(self, kb: KnowledgeBase) -> str:
        """导出为 RDF Turtle"""
        turtle = "@prefix welding: <http://welding.knowledge.org/> .\n"
        turtle += "@prefix dc: <http://purl.org/dc/elements/1.1/> .\n\n"
        
        for edge in kb.edges:
            turtle += f"{edge.get_rdf_triple()}\n"
        
        return turtle
    
    def export_to_jsonld(self, kb: KnowledgeBase) -> Dict:
        """导出为 JSON-LD"""
        return {
            "@context": KnowledgeGraphExporter.JSONLD_CONTEXT,
            "@graph": [edge.to_jsonld() for edge in kb.edges]
        }
    
    def export_to_cypher(self, kb: KnowledgeBase) -> str:
        """生成 Neo4j Cypher 脚本"""
        cypher_statements = []
        
        for edge in kb.edges:
            cypher = edge.to_cypher()
            cypher_statements.append(cypher)
        
        return "\n".join(cypher_statements)
```

**工期**: 2 小时

---

## 5 天执行路线图

### Day 1 (2026-04-16) - 多源对照 + 因果链抽取

```
上午 (4h):
  09:00-10:00: 代码框架搭建
  10:00-11:00: 能力 1 实现 (EvidenceTriangulation)
  11:00-12:00: 能力 1 单元测试
  12:00-13:00: 午休

下午 (4h):
  13:00-14:00: 能力 2 设计文档 (CausalChainExtractor)
  14:00-16:00: 能力 2 实现 (DAG 构建)
  16:00-17:00: 能力 2 单元测试

产出:
  - p3_evidence_triangulation.py (~200 行)
  - p3_causal_chain_extractor.py (~250 行)
  - 2 个单元测试脚本
```

### Day 1.5 (2026-04-17) - 一致性检验 + 冲突消解

```
上午 (4h):
  09:00-10:00: 能力 3 实现 (ConsistencyValidator)
  10:00-11:00: 能力 3 单元测试
  11:00-12:00: 能力 4 设计 (ConflictResolver)
  12:00-13:00: 午休

下午 (4h):
  13:00-15:00: 能力 4 实现
  15:00-16:00: 冲突消解的三策略 (权重、条件、时间)
  16:00-17:00: 能力 4 单元测试

产出:
  - p3_consistency_validator.py (~200 行)
  - p3_conflict_resolver.py (~250 行)
  - 冲突消解决策库
```

### Day 2 (2026-04-18) - DAG 生成 + 跨查询聚合

```
上午 (4h):
  09:00-10:30: 能力 5 实现 (DAGBuilder)
  10:30-11:30: 能力 5 单元测试
  11:30-12:30: 集成前 4 个能力 (Pipeline)
  12:30-13:00: 午休

下午 (4h):
  13:00-14:00: 能力 6 设计 (CrossQueryAggregator)
  14:00-15:30: 能力 6 实现
  15:30-16:30: 知识库建设
  16:30-17:00: 性能测试

产出:
  - p3_inference_engine.py (~200 行)
  - p3_knowledge_aggregator.py (~300 行)
  - 完整的 E2E 测试 (5 条查询)
  - 焊接领域因果模板库 (50+ 模板)
```

### Day 3 (2026-04-19) - 前端可视化 + 动态更新

```
上午 (4h):
  09:00-10:00: 前端框架搭建 (HTML/CSS)
  10:00-12:00: D3.js 可视化实现 (2h)
  12:00-13:00: 午休

下午 (4h):
  13:00-14:00: 能力 7 设计 (DynamicUpdater)
  14:00-15:30: 能力 7 实现 (增量更新逻辑)
  15:30-16:30: 冲突检测与消解集成
  16:30-17:00: 集成测试

产出:
  - visualization.html / styles.css / visualization.js
  - p3_dynamic_updater.py (~250 行)
  - p3_visualization_server.py (~150 行)
```

### Day 4 (2026-04-20) - 知识图谱导出 + 测试优化

```
上午 (4h):
  09:00-10:30: 能力 9 实现 (RDF/JSON-LD/Cypher)
  10:30-11:30: 知识图谱验证
  11:30-12:30: 性能基准 (100 条查询)
  12:30-13:00: 午休

下午 (4h):
  13:00-14:00: E2E 集成测试 (完整流程)
  14:00-15:00: 成本验证和优化
  15:00-16:00: 文档生成
  16:00-17:00: 缓冲和修复

产出:
  - p3_graph_exporter.py (~200 行)
  - E2E 测试通过
  - 性能报告: <15 min/100 queries
  - 成本报告: <$15 USD
```

### Day 5 (2026-04-21) - 最终验收和计划完成

```
上午 (2h):
  09:00-10:00: 缺陷修复和优化
  10:00-11:00: 最终验收测试

产出:
  - 最终验收报告
  - 所有 8 个模块交付完成 ✅
  - 完整文档和 API 规范
```

---

## 核心算法设计

### 三级冲突消解算法

```python
def resolve_conflict_threelevel(conflict: Conflict) -> Resolution:
    """
    三级冲突消解:
    L1: 证据权重 (Authority-based)
    L2: 条件细化 (Condition-based)
    L3: 时间演变 (Temporal-based)
    """
    
    # L1: 证据权重判定
    primary = select_by_authority(conflict.claims)  # 权威性最高
    
    # L2: 条件细化
    if conditions_are_different(conflict.claims):
        # 冲突来自于不同的条件
        return Resolution(
            type="CONDITIONAL",
            explanation=f"两项声明在不同条件下成立",
            recommendation="在指定条件下分别采用"
        )
    
    # L3: 时间演变
    if is_temporal_evolution(conflict.claims):
        newer = get_newer_claim(conflict.claims)
        return Resolution(
            type="EVOLUTION",
            explanation=f"从 {get_older_claim(conflict.claims).year} 演变到 {newer.year}",
            recommendation=f"优先采用 {newer.year} 的新研究"
        )
    
    # 最终: 返回权威性最高的
    return Resolution(
        type="AUTHORITY_BASED",
        primary_claim=primary,
        explanation=f"采用权威性最高的声明"
    )
```

### 跨查询聚合算法导出

```python
def aggregate_across_100_queries(all_dags: List[DAG]) -> 
    KnowledgeBase:
    """
    从 100 条查询的 DAG 聚合为知识库
    
    算法:
    1. 遍历所有 DAG，统计边频度
    2. 筛选高频边 (出现 >50% 的查询中)
    3. 为每条高频边计算标准权重
    4. 生成标准因果模板库
    """
    
    edge_frequency = Counter()
    
    for dag in all_dags:
        for edge in dag.edges:
            edge_frequency[edge] += 1
    
    # 计算频度阈值 (50% 的查询)
    threshold = len(all_dags) * 0.5
    
    # 筛选高频边
    standard_edges = {
        edge: freq 
        for edge, freq in edge_frequency.items()
        if freq >= threshold
    }
    
    # 权重标准化
    for edge in standard_edges:
        edge.set_standard_weight(
            frequency=edge_frequency[edge] / len(all_dags)
        )
    
    kb = KnowledgeBase()
    kb.load_standard_patterns(standard_edges)
    
    return kb
```

---

## 测试和验收

### 单元测试 (Day 1-4)

每个能力都有对应的单元测试:

```python
# test_p3_capabilities.py

class TestEvidenceTriangulation(unittest.TestCase):
    def test_triangulation_basic(self):
        """测试基本的多源对照"""
        triangulator = EvidenceTriangulation()
        
        claims = [
            Claim(..., source=SourceMeta(IF=2.5, citations=25)),
            Claim(..., source=SourceMeta(IF=3.0, citations=30)),
        ]
        
        result = triangulator.triangulate(claims)
        
        self.assertEqual(len(result), 1)  # 聚合为 1 个 EvidenceSet
        self.assertGreater(result[0].total_strength, 5.0)
        self.assertEqual(result[0].consensus_level, "STRONG")

# ... 其他能力的单元测试

class TestE2E(unittest.TestCase):
    def test_complete_pipeline(self):
        """端到端测试"""
        query = "激光功率如何影响焊缝质量？"
        papers = load_test_papers(5)
        
        result = process_query(query, papers)
        
        self.assertGreater(len(result.chains), 0)
        self.assertGreater(len(result.dag.nodes), 3)
        self.assertGreater(result.confidence, 0.7)
```

### E2E 集成测试 (Day 4)

```
5 条查询的完整流程:
  ├─ 查询 1: "激光功率如何影响焊缝熔深？"
  ├─ 查询 2: "扫描速度与焊缝气孔的关系"
  ├─ 查询 3: "焊接工艺参数对焊缝强度的影响"
  ├─ 查询 4: "热输入与焊接金相组织"
  └─ 查询 5: "冷却速率与焊缝硬度"
  
预期输出:
  - 5 个独立的 DAG
  - 1 个聚合的知识库 (50+ 标准模板)
  - 冲突数: <10
  - 平均置信度: >0.8
```

### 性能基准 (Day 4-5)

```
100 条查询的性能测试:
  
  指标:
    - 处理时间: <15 分钟 (144ms/query)
    - 内存使用: <2GB
    - DAG 平均大小: 8-12 节点
    - 聚合知识库大小: 50-100 高频模板
    
  成本:
    - LLM 调用: <100 次 ($1-2)
    - API 调用: <50 次 ($2-5)
    - 总成本: <$15
```

---

## 交付物清单

### 代码文件 (8 个)

```
layers/p3/
├── p3_evidence_triangulation.py (~200 行)
├── p3_causal_chain_extractor.py (~250 行)
├── p3_consistency_validator.py (~200 行)
├── p3_conflict_resolver.py (~250 行)
├── p3_inference_engine.py (~200 行)
├── p3_knowledge_aggregator.py (~300 行)
├── p3_dynamic_updater.py (~250 行)
├── p3_graph_exporter.py (~200 行)
├── p3_visualization_server.py (~150 行)
└── __init__.py

models/p3/
├── p3_data_models.py (DAG, Chain, Resolution, KnowledgeBase)

frontend/
├── index.html (D3.js 可视化框架)
├── styles.css (样式表)
└── visualization.js (交互逻辑)

总代码行数: ~1500 + 前端代码
```

### 测试文件

```
tests/
├── test_p3_evidence_triangulation.py
├── test_p3_causal_chain_extractor.py
├── test_p3_consistency_validator.py
├── test_p3_conflict_resolver.py
├── test_p3_e2e.py (完整端到端)
└── test_p3_performance.py (性能基准)
```

### 文档文件

```
docs/
├── P3_COMPREHENSIVE_COMPLETION_REPORT.md
├── P3_API_SPECIFICATION.md
├── P3_ALGORITHM_DESIGN.md
├── FRONTEND_USER_GUIDE.md
├── KNOWLEDGE_GRAPH_SPECIFICATION.md
└── DEPLOYMENT_GUIDE.md
```

### 数据导出

```
exports/
├── welding_knowledge_base.ttl (RDF Turtle)
├── welding_knowledge_base.jsonld (JSON-LD)
├── welding_knowledge_base.cypher (Neo4j Cypher)
└── test_results.json (性能和成本报告)
```

---

## 关键依赖和先决条件

### 输入依赖

✅ **来自 P1-P2 优化**:
- 声明准确度: 92% (从 85%)
- 语义对齐: 98% (从 75%)
- 元数据完整度: 98% (从 85%)
- LLM 成本: -90% (节省产出可用于 P3)

### 外部依赖

- Python 3.8+
- transformers (已安装)
- sentence-transformers (已安装)
- requests (API 调用)
- networkx (DAG 操作)
- d3.js (前端可视化)
- pandas / numpy (数据处理)

### 计算资源

- CPU: 4+ 核心
- 内存: 2-4 GB
- 网络: 用于 API 调用

---

## Gemini 执行指南

### 启动命令

```bash
# 创建 P3 执行目录
mkdir -p layers/p3 models/p3 tests/p3 frontend exports

# 启动执行
python main_p3_orchestrator.py --mode full --queries 100 --cost-budget 15
```

### 监控关键指标

```json
{
  "execution_checklist": {
    "day_1": {
      "events_triangulation": "✅/❌",
      "causal_chains": "✅/❌",
      "test_1_pass": "✅/❌"
    },
    "day_2": {
      "consistency_validation": "✅/❌",
      "conflict_resolution": "✅/❌",
      "dag_generation": "✅/❌",
      "test_2_pass": "✅/❌"
    },
    "day_3": {
      "cross_query_aggregation": "✅/❌",
      "frontend_visualization": "✅/❌",
      "test_3_pass": "✅/❌"
    },
    "day_4": {
      "dynamic_updates": "✅/❌",
      "knowledge_export": "✅/❌",
      "e2e_test": "✅/❌",
      "performance_ok": "✅/❌"
    },
    "day_5": {
      "final_verification": "✅/❌",
      "all_deliverables": "✅/❌"
    }
  },
  
  "resource_tracking": {
    "time_used": "X/5.5 days",
    "cost_used": "$X / $15",
    "memory_peak": "X MB"
  }
}
```

### 成功标准

- ✅ 所有 8 个能力模块代码完成
- ✅ E2E 测试通过 (5 条查询)
- ✅ 性能基准通过 (<15 min/100 queries)
- ✅ 成本控制 (<$15 USD)
- ✅ 前端可视化可用
- ✅ 知识图谱成功导出
- ✅ 完整文档交付

---

**P3 深化版执行规划完成** ✅

**下一步**: 等待 Gemini 启动 P3 执行

**预计完成**: 2026-04-20 下午

**最终交付**: 2026-04-21 上午 (项目完成)
