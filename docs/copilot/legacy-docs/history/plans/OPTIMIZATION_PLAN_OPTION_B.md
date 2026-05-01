# 方案 B: P1-P2 优化与 P3 调整规划

**规划日期**: 2026-04-11  
**执行时间**: 2026-04-12 ~ 04-14 (2-3 天)  
**优化范围**: 精度提升 + 成本优化  
**对 P3 影响评估**: 已包含

---

## 📋 目录

1. [优化范围确定](#优化范围确定)
2. [优化方案详情](#优化方案详情)
3. [P3 计划调整](#p3-计划调整)
4. [实现路线图](#实现路线图)
5. [ROI 分析](#roi-分析)

---

## 优化范围确定

### 优化 1: 正则提取精度提升 (+ NER)

**当前状态** (P2):
```
正则模式匹配: 85% 准确度
- 优点: 快速, 零成本
- 缺点: 复杂句子遗漏 15%
        长难句的主宾体识别偏差
```

**优化方案**:
```
集成 NER 模型 (命名实体识别)
  规则模式 → [初筛 90%] ← 快速
  ↓
  NER 模型 → [精化 95%] ← 补充边界情况
  ↓
  LLM refinement → [最终 98%] ← 仅处理歧义
```

**目标指标**:
```
当前: Precision 85%, Recall 82%
目标: Precision 92%, Recall 90%

提升: +7-8% 准确度
```

**工作量**: 1 天  
**成本**: $2-3 (LLM 精化调用)

---

### 优化 2: 向量 Embedding 集成 (BGE)

**当前状态** (P2):
```
语义相似度计算: 字符集重叠系数
- 问题: 无法处理语义转述
  例: "热裂纹" vs "热开裂" 识别为 0.3 (实际应是 0.95)
```

**优化方案**:
```
使用 BGE-m3 Embedding (已在 P1 中使用)
  Local Vector 计算 → 零成本
  无额外 API 调用
  
效果提升:
  "热裂纹" vs "热开裂" → 向量相似度 0.95 ✓
  "激光功率" vs "激光能量" → 0.87 ✓
  "熔深" vs "焊缝深度" → 0.92 ✓
```

**目标指标**:
```
当前: 对齐准确度 ~75% (需要 LLM 灰度)
目标: 对齐准确度 ~90% (很少需要 LLM)

结果: LLM 调用 1% → 0.1%
      节省成本 90%
```

**工作量**: 0.5 天  
**成本**: $0 (本地模型)

---

### 优化 3: 外部 API 激活

**当前状态** (P2):
```
元数据获取: 100% 依赖本地数据
- 缺失: 权威性指标的实时更新
  例: 被引计数 (可能已更新)
  影响因子 (每年更新)
```

**优化方案**:
```
激活 CrossRef + Scrapedia API
  本地元数据 (85%) → 快速
  ↓
  [冲突严重程度 >= 3] 时
  ↓
  调用 CrossRef → 获取权威元数据
  调用 Scrapedia → 获取最新被引数
```

**目标指标**:
```
当前: 元数据覆盖 85% (部分信息缺失)
目标: 元数据覆盖 98% (几乎完整)

权威性评估准确度:
  当前: 0.78 (基于本地估算)
  目标: 0.88 (基于官方数据)
```

**工作量**: 1 天  
**成本**: $1-2 (仅在高级冲突时调用)

---

## 优化方案详情

### 优化 1 详情: NER 集成方案

#### 步骤 1a: 选择 NER 模型

**选项 A**: 通用 NER (推荐 - 快速)
```
模型: ERNIE-Gram
成本: 本地 fine-tune + 推理
性能: Accuracy 88% (通用领域)
时间: 2h quick-start
```

**选项 B**: 焊接领域微调 NER
```
基础: BiLSTM-CRF or Transformer
数据: 焊接论文标注 (需 200 篇标注)
成本: 标注 $100-200 + 训练 $20-50
性能: Accuracy 95% (专业领域)
时间: 3-4 天
```

**推荐**: 选项 A (快速启动) + 后续考虑选项 B

#### 步骤 1b: 混合管道设计

```python
def extract_claims_with_ner(text: str, source: SourceMeta) -> List[Claim]:
    """
    改进的声明抽取管道
    """
    
    # 阶段 1: 正则初筛 (成本 $0, 速度 5ms)
    rough_claims = regex_extract(text)
    rough_confidence = [0.75]  # 假设初筛准确度 75%
    
    # 阶段 2: NER 精化 (成本 $0, 速度 50ms)
    ner_results = ner_model.extract_entities(text)
    # 结果: [Entity1(type=Material), Entity2(type=Process), ...]
    
    # 结合 Regex 和 NER
    combined_claims = combine_regex_and_ner(rough_claims, ner_results)
    
    # 阶段 3: LLM 精化 (仅处理低置信度, 成本 $0.0005/claim)
    low_confidence = [c for c in combined_claims if c.confidence < 0.80]
    refined = llm_clarify_edge_cases(low_confidence)  # 预计 <2% 的声明
    
    return refined_claims

# 预期效果:
# 准确度: 85% → 92% (+7%)
# LLM 成本: 100% → 2% (-98%)
```

#### 步骤 1c: 实现清单

```
- [ ] 集成 ERNIE-Gram 到 p2_claim_extractor.py
- [ ] 修改 _regex_pre_extract() 添加 NER 路径
- [ ] 实现 combine_regex_and_ner() 逻辑
- [ ] 单元测试 (20 条复杂句子)
- [ ] 性能基准 (1000 条文本)
- [ ] 成本跟踪
```

---

### 优化 2 详情: BGE Embedding 集成

#### 步骤 2a: 现有 BGE 复用

**当前 P1 已有**:
```
library: sentence-transformers
model: BAAI/bge-m3
配置: 已在 master_global_index 中使用
```

**需要做**:
```
在 p2_conflict_detector.py 中复用 BGE

当前:
  align_similarity() 使用字符集重叠 vec_sim
  
改进:
  from sentence_transformers import SentenceTransformer
  
  model = SentenceTransformer('BAAI/bge-m3')
  
  # 第二层: 向量相似度 (改进版)
  embedding_a = model.encode(text_a)
  embedding_b = model.encode(text_b)
  vec_sim = cosine_similarity(embedding_a, embedding_b)
```

#### 步骤 2b: 三级对齐的改进

```
当前实现 (P2):
  L1: 词典查询 (< 1ms)
  L2: 字符重叠 (< 5ms)
  L3: LLM 灰度 (> 500ms, < 1% 调用)
  
改进实现 (优化后):
  L1: 词典查询 (< 1ms) ← 不变
  L2: 向量相似度 BGE (< 50ms) ← 改进: 精度 +15%
  L3: LLM 灰度 (> 500ms, < 0.1% 调用) ← 减少 90%
  
成本影响:
  当前: ~$5-10 (LLM 1% 调用)
  改进: ~$0.5 (LLM 0.1% 调用)
  节省: 90% LLM 成本
```

#### 步骤 2c: 实现清单

```
- [ ] 在 p2_conflict_detector.py 中加载 BGE 模型
- [ ] 修改 align_similarity() 的第二层
- [ ] 添加向量缓存 (可选, 提速 10 倍)
- [ ] 单元测试 (焊接术语对 100 对)
- [ ] 性能基准 (50K claims)
- [ ] 成本确认 (应降至 $0-1)
```

---

### 优化 3 详情: 外部 API 激活

#### 步骤 3a: 配置 CrossRef API

```python
import requests
from datetime import datetime

class CrossRefProvider:
    """CrossRef 元数据提供器"""
    
    BASE_URL = "https://api.crossref.org/works"
    
    def enrich_metadata(self, doi: str) -> Dict:
        """
        查询 CrossRef 获取权威元数据
        
        输入: DOI = "10.1016/j.jmatprotec.2022.xxx"
        输出: {
          "authors": ["Zhang Wei", "Li Na", ...],
          "corresponding_author": "Zhang Wei",
          "impact_factor": 5.2,
          "publisher": "Elsevier",
          "citation_count": 45,
          "update_date": "2026-04-11"
        }
        """
        
        response = requests.get(
            f"{self.BASE_URL}/{doi}",
            params={"mailto": "your-email@example.com"}
        )
        
        if response.status_code == 200:
            data = response.json()['message']
            return {
                "authors": [a['given'] + ' ' + a['family'] 
                           for a in data.get('author', [])],
                "corresponding_author": data.get('author', [{}])[0].get('family'),
                "publisher": data.get('publisher', 'Unknown'),
                "citation_count": data.get('cited-by-count', 0),
                "update_date": datetime.now().isoformat()
            }
        
        return None  # API 失败时返回 None，继续使用本地数据
```

#### 步骤 3b: 配置 Scrapedia API

```python
class ScrapediaProvider:
    """Scrapedia 被引数提供器 (备选)"""
    
    def get_citation_count(self, title: str, year: int) -> Optional[int]:
        """
        查询 Scrapedia 获取最新被引次数
        
        成本: $0.02/查询
        成功率: 80% (需要精确匹配)
        延迟: 500-1000ms
        """
        
        # 构造查询
        query = f"{title[:50]} {year}"
        
        response = requests.get(
            "https://api.scrapedia.com/citations",
            params={"query": query},
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        
        if response.ok:
            return response.json().get('citation_count', 0)
        return None
```

#### 步骤 3c: 分级调用策略

```python
class MetadataEnricher:
    """
    智能元数据富化：本地优先，API 补充
    """
    
    def enrich(self, conflict: ClassifiedConflict) -> ClassifiedConflict:
        """
        根据冲突严重程度决定是否调用 API
        """
        
        # 原则: 仅在高级冲突时调用，节省成本和时间
        if conflict.severity_level < 3:
            # 低级冲突：使用本地元数据即可
            return conflict
        
        # 高级冲突：调用 API 获取最新数据
        cost_tracker = CostTracker()
        
        for claim in conflict.claims_involved:
            if claim.source.doi:
                # 调用 CrossRef
                cost_tracker.track('crossref', 0.05)
                enriched = self.crossref.enrich_metadata(claim.source.doi)
                if enriched:
                    claim.source.update(enriched)
        
        # 检查成本预算
        if cost_tracker.total > 0.5:
            logger.warning("API 成本接近上限，停止调用")
            break
        
        return conflict

# 预期成本:
#   100 条查询 → ~5-10 个高级冲突
#   → 5-10 次 API 调用
#   → $0.25-0.50 总成本
```

#### 步骤 3d: 实现清单

```
- [ ] 申请 CrossRef API 访问 (免费)
- [ ] 申请 Scrapedia API key ($100-200 额度)
- [ ] 实现 CrossRefProvider 类
- [ ] 实现 ScrapediaProvider 类 (可选)
- [ ] 实现分级调用策略
- [ ] 添加成本跟踪和预警
- [ ] 集成到 p2_logic_engine.py
- [ ] 单元测试 (10 个冲突)
- [ ] 错误处理和 fallback
```

---

## P3 计划调整

### 对 P3 的正面影响

**优化完成后，P3 的输入质量提升**:

```
优化前 (P2 原始):
  ├─ 声明抽取准确度: 85%
  ├─ 语义对齐准确度: 75% (需要 LLM)
  ├─ 元数据完整性: 85%
  └─ LLM 成本: $6-10

优化后 (P1-P2 增强):
  ├─ 声明抽取准确度: 92% ↑ +7%
  ├─ 语义对齐准确度: 98% ↑ +23%
  ├─ 元数据完整性: 98% ↑ +13%
  └─ LLM 成本: $0.5-1.5 ↓ -90%
```

### P3 可相应简化

**由于 P1-P2 质量提升，P3 的负担减轻**:

```
P3 的 5 个模块中，以下可简化:

1. 多源对照
   当前: 需要复杂的置信度权衡
   优化后: 由于准确度 98%，冲突更清晰，权衡更简单
   → 工期 -0.5 天
   → 复杂度 -30%

2. 因果链抽取
   当前: 需要 LLM 补充和校准
   优化后: 声明质量更好，自动化程度提高
   → 工期 -0.3 天
   → LLM 调用 -50%

3. 一致性检验
   当前: 需要处理大量边界情况
   优化后: 边界情况减少，检验逻辑更清晰
   → 工期 -0.2 天
```

### P3 修改版方案

**基于优化后的输入，P3 可采用"简化版"方案**:

```
简化版 P3 (3-4 天，而非 4-5 天):

Day 1: 多源对照框架 (-0.5d)
  └─ 由因质量提升而简化 20%

Day 1.5: 因果链抽取 (合并，-0.3d)
  └─ 自动化程度更高

Day 2: 一致性检验 (-0.2d)
  └─ 边界情况减少

Day 3: 冲突消解 + DAG 构造

简化版总工期: 3-4 天 (vs 原计划 4-5 天)
简化版成本: $3-8 (vs 原计划 $5-15)
```

### 或者: P3 保持原计划但深化

**也可选择保持 P3 的 4-5 天工期，但加入更多功能**:

```
深化版 P3 (4-5 天，新增功能):

原有 5 个模块 (占 3 天)
+ 新增能力:
  1. 跨查询知识聚合 (找到不同查询间的共同因果路径)
  2. 动态更新机制 (新文献自动融入推演图)
  3. 前端可视化 (交互式推演图)
  4. 知识图谱导出 (RDF/JSON-LD 格式)

预期提升: 从"单查询推演" → "多查询知识图"
```

---

## 实现路线图

### 优化阶段时间表 (2026-04-12 ~ 04-14)

```
┌─────────────────────────────────────────────────┐
│ 2026-04-12 (Day 1) - 上午                        │
├─────────────────────────────────────────────────┤
│ ✅ NER 模型选型与集成 (2h)                       │
│    ├─ 选用 ERNIE-Gram                           │
│    ├─ 集成到 p2_claim_extractor.py              │
│    └─ 基础测试                                   │
│                                                  │
│ ✅ 精度测试与验证 (2h)                           │
│    ├─ 在 100 条复杂句子上测试                    │
│    ├─ 与原方案对比 (85% → 92%)                  │
│    └─ 确认成本节省                               │
│                                                  │
│ ✅ BGE Embedding 集成 (2h)                       │
│    ├─ 在 p2_conflict_detector 中复用 BGE       │
│    ├─ 修改三级对齐逻辑                          │
│    └─ 快速测试 (50 对术语)                      │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ 2026-04-12 (Day 1) - 下午                        │
├─────────────────────────────────────────────────┤
│ ✅ BGE 性能基准 (2h)                             │
│    ├─ 50K claims 对比                           │
│    ├─ 准确度提升确认                            │
│    └─ LLM 调用降低确认 (1% → 0.1%)              │
│                                                  │
│ ✅ P2 单元测试更新 (1h)                          │
│    ├─ 修改 test_p2_logic.py                     │
│    └─ 运行完整测试套件                          │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ 2026-04-13 (Day 2)                              │
├─────────────────────────────────────────────────┤
│ ✅ CrossRef API 集成 (3h)                        │
│    ├─ 申请 API 访问 (免费)                       │
│    ├─ 实现 CrossRefProvider 类                  │
│    ├─ 集成到 p2_logic_engine.py                 │
│    └─ 基础测试 (10 个 DOI)                      │
│                                                  │
│ ✅ 分级调用策略实现 (2h)                         │
│    ├─ 根据冲突严重程度决定是否调用               │
│    ├─ 成本跟踪与预警                            │
│    └─ Fallback 处理                             │
│                                                  │
│ ✅ 元数据完整性验证 (2h)                         │
│    ├─ 测试 50 个冲突                            │
│    ├─ 确认覆盖率 85% → 98%                      │
│    └─ 成本确认 $1-2                             │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ 2026-04-14 (Day 3)                              │
├─────────────────────────────────────────────────┤
│ ✅ 端到端集成测试 (2h)                           │
│    ├─ NER + BGE + API 完整流程                  │
│    ├─ 在 eval_queries_v1.0.jsonl 上测试         │
│    └─ 性能验收 (<=20 分钟/100 查询)             │
│                                                  │
│ ✅ 成本和精度确认 (1h)                           │
│    ├─ 最终成本统计                              │
│    ├─ 准确度提升确认                            │
│    └─ 生成优化报告                              │
│                                                  │
│ ✅ P3 计划调整 (2h)                               │
│    ├─ 根据优化效果调整 P3 方案                   │
│    └─ 选择简化版 3-4 天 或 深化版 4-5 天         │
└─────────────────────────────────────────────────┘

总计: 3 天 (没有超期风险)
```

---

## ROI 分析

### 投入与产出

#### 投入

```
时间: 2-3 天 (使用原定的 4-5 天的部分)
成本: $2-5 USD (NER 精化调用)
人力: 1 工程师稳定投入
```

#### 产出

```
准确度提升:
  ├─ 声明抽取: 85% → 92% (+7%)
  ├─ 语义对齐: 75% → 98% (+23%)
  └─ 综合质量: 从 8.5/10 → 9.2/10

成本节省:
  └─ LLM 调用降低 90% ($5-10 → $0.5-1.5)

工程收益:
  ├─ P3 工期缩短 0.5-1 天
  ├─ P3 复杂度降低 30%
  └─ 系统稳定性提升

知识质量:
  ├─ 漏检率从 18% → 8% (-55%)
  ├─ 误检率从 15% → 8% (-47%)
  └─ 可信度从 0.75 → 0.85 (+13%)
```

### 投入回报率 (ROI)

```
直接成本回报:
  投入: $2-5 + 2-3 天 工时
  收益: 节省 LLM 成本 $8-9 (长期)
  回报周期: 1 个项目周期

间接收益:
  质量: 系统可信度 +13% (无法量化)
  速度: 后续项目快 0.5-1 天
  可维护性: 代码复杂度降低 30%

总体 ROI: ⭐⭐⭐⭐⭐ (强烈推荐)
```

---

## 关键决策

### 决策 1: 选择 NER 模型

**选项 A**: 通用模型 (ERNIE-Gram) - 推荐 ✓
- 准确度: 88%
- 工期: 2h
- 成本: $0

**选项 B**: 焊接微调模型
- 准确度: 95%
- 工期: 3-4 天
- 成本: $100-200 + 标注
- 建议: 留作后续优化

**选择**: 选项 A (快速启动)

---

### 决策 2: P3 方案选择

基于优化完成后，需要选择:

**方案 A**: 简化版 P3 (3-4 天)
```
工期: 3-4 天 (快速)
成本: $3-8
特性: 核心 5 能力
适合: 想快速完成项目
```

**方案 B**: 深化版 P3 (4-5 天)
```
工期: 4-5 天
成本: $5-15
特性: 核心 5 能力 + 跨查询聚合 + 动态更新 + 可视化
适合: 想完整的知识图谱系统
```

**需要用户选择** ← 待确认

---

### 决策 3: API 激活程度

**选项 A**: CrossRef 全激活
- 成本: $1-2 (高级冲突时调用)
- 收益: 元数据 98% 完整
- 推荐: ✓ 激活

**选项 B**: 可选激活
- 仅在需要时启用
- 默认使用本地数据
- 推荐: ✓

**选择**: 选项 B (灵活) + 默认激活分级调用

---

## 修改后的总体时间表

### 完整项目时间线

```
2026-04-11: P0 ✅, P1 ✅, P2 ✅ 完成
            决定优化方案 B

2026-04-12 ~ 04-14 (3 天): P1-P2 优化
  ├─ NER 集成 + 测试
  ├─ BGE 集成 + 性能验证
  └─ API 配置 + 分级调用

2026-04-15 (评估 1 天):
  发布优化报告
  选择 P3 方案 (简化版 or 深化版)

2026-04-16 ~ 04-18 (3-4 天): P3 执行
  ├─ 简化版: 3 天
  └─ 深化版: 4-5 天

2026-04-19 (评估 1 天):
  P3 验收，决定是否推进 P4

总项目周期: 9-10 天 (vs 原计划 13-14 天)
```

---

## 优化方案实施清单

### Pre-Checks (立即做)

- [ ] 确认 ERNIE-Gram 可用 (检查 transformers 库)
- [ ] 确认 BGE 已在 P1 中使用 (复用配置)
- [ ] 申请 CrossRef API key (免费，5 分钟)
- [ ] 审批 Scrapedia (可选，预留)

### 执行检查 (2026-04-12)

- [ ] 修改 p2_claim_extractor.py (+30 行 NER 代码)
- [ ] 修改 p2_conflict_detector.py (+50 行 BGE 代码)
- [ ] 修改 p2_logic_engine.py (+80 行 API 代码)
- [ ] 更新 test_p2_logic.py (添加 NER/BGE 测试)

### 验证检查 (2026-04-14)

- [ ] 准确度提升验证 (85% → 92%)
- [ ] 成本降低验证 (90% LLM 降低)
- [ ] 性能基准验证 (<20 min/100 queries)
- [ ] 成本预算确认 ($2-5 范围内)

---

## 后续 P3 方案对比

### 简化版 P3

```
特性:
  ✓ 多源对照
  ✓ 因果链抽取
  ✓ 一致性检验
  ✓ 冲突消解
  ✓ DAG 生成
  
工期: 3-4 天
成本: $3-8
文件数: 4 个新文件
代码行数: ~800 行
```

### 深化版 P3

```
特性:
  ✓ 多源对照
  ✓ 因果链抽取
  ✓ 一致性检验
  ✓ 冲突消解
  ✓ DAG 生成
  ✓ 跨查询知识聚合 (新增)
  ✓ 动态更新机制 (新增)
  ✓ 前端可视化 (新增)
  ✓ 知识图谱导出 (新增)
  
工期: 4-5 天
成本: $5-15
文件数: 6-8 个文件
代码行数: ~1500 行
```

---

## 建议与总结

### 强烈推荐执行

✅ **优化方案 B 是正确的选择**

理由:
1. 在不增加总工期的情况下显著提升质量
2. 大幅降低 LLM 成本 (-90%)
3. 为 P3 创造更好的基础
4. P3 可相应简化或深化

### P3 后续决策

**建议**: 执行 **深化版 P3**

理由:
1. 由于 P1-P2 质量提升，P3 复杂度反而降低
2. 额外投入仅 1 天 + $5-7，但产出提升 100%
3. 最终交付一个生产级的知识图谱系统
4. 可以作为后续 P4 的基础

---

**优化方案制定完成 ✅**
