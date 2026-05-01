# P2 冲突检测算法设计文档

**版本**: 1.0  
**设计日期**: 2026-04-11  
**预期工时**: 4-5 天  
**目标交付**: 逻辑推演框架 v1.0

---

## 📋 目录

1. [问题定义](#问题定义)
2. [整体架构](#整体架构)
3. [核心算法 I：实体声明抽取](#核心算法-i实体声明抽取)
4. [核心算法 II：冲突检测](#核心算法-ii冲突检测)
5. [核心算法 III：冲突分类](#核心算法-iii冲突分类)
6. [核心算法 IV：推演链构造](#核心算法-iv推演链构造)
7. [实现路线图](#实现路线图)
8. [质量保证](#质量保证)

---

## 问题定义

### 何为"冲突"

在焊接领域，冲突是指：
1. **直接矛盾**: 两个文献对同一实体属性给出相反的结论
   - 例: 文献 A 说"高功率→高熔深"，文献 B 说"高功率→低熔深"
   
2. **条件冲突**: 同一结论在不同条件下不适用
   - 例: "薄材料用低功率" vs "厚材料也能用低功率"
   
3. **时间冲突**: 同一实体的性质在不同时期发生演变
   - 例: 2020 年"Ti-6Al-4V 易热裂"，2024 年"新工艺消除热裂"
   
4. **因果冲突**: 因果链条不一致
   - 例: A→B→C vs A→B→D

### 冲突的严重程度

```
Level 1 (低): 措辞不同，实意相同
  "增加功率" vs "提高激光功率"  → 相同
  
Level 2 (中): 量化差异需要澄清
  "功率 500W 得到好结果" vs "功率 700W 得到最好结果"  → 需要梯度分析
  
Level 3 (高): 直接矛盾
  "功率增加→熔深增加" vs "功率增加→熔深减少"  → 充分矛盾
  
Level 4 (严重): 涉及安全性或物理规律违反
  "某材料在真空中无脆性" vs "该材料在真空中极易脆裂"  → 严重冲突
```

---

## 整体架构

```
输入: Query + 检索结果 (from P1 R-Layer)
  ↓
┌─────────────────────────────────────┐
│ 步骤 1: 实体声明抽取 (Claim Extract)  │  → 从 chunks 中提取结构化声明
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ 步骤 2: 冲突检测 (Conflict Detection) │  → 对声明对进行比较
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ 步骤 3: 冲突分类 (Conflict Classify)  │  → 判定冲突类型和严重程度
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ 步骤 4: 推演链构造 (Reasoning Chain)  │  → 生成结构化推演报告
└─────────────────────────────────────┘
  ↓
输出: 推演报告 (JSON 格式)
  {
    "conflicts": [...],
    "reasoning_chains": [...],
    "recommendations": [...]
  }
```

---

## 核心算法 I：实体声明抽取

### 问题
从非结构化的论文文本中提取**结构化的声明** (claim)

### 声明的结构定义

```python
@dataclass
class Claim:
    """单个声明的结构化表示"""
    claim_id: str                    # 唯一 ID
    subject: Entity                  # 主体 (如: Ti-6Al-4V, 激光功率)
    predicate: str                   # 谓词 (如: 控制, 影响, 导致)
    object: Entity | Value           # 宾体 (如: 熔深, 600W)
    context: Dict[str, str]          # 条件 (如: {"material": "Ti-6Al-4V", "method": "激光焊"})
    confidence: float                # 置信度 0-1
    evidence_text: str               # 证据原文
    source_doc: str                  # 来源文献 ID
    publication_year: int            # 发表年份
    
    # 量化属性 (如果适用)
    quantitative_value: Optional[float]
    quantitative_unit: Optional[str]
    quantitative_range: Optional[Tuple[float, float]]  # [min, max]
```

### 抽取策略

#### 方式 1：LLM 抽取（精度高，成本较高）

```python
def extract_claims_via_llm(chunk: str, entity_registry: EntityRegistry) -> List[Claim]:
    """
    使用 LLM 从单个 chunk 抽取声明
    
    提示词结构:
    ────────────────
    你是一个焊接领域的知识抽取专家。
    从下面的文献段落中抽取"声明"(claim)。
    
    声明的定义:
    - 主体: 焊接相关实体 (材料、工艺参数、性能指标)
    - 谓词: 实体间的关系动词 (控制、影响、导致、改善、恶化)
    - 宾体: 另一个实体或数值
    - 条件: 使该声明成立的前提条件
    
    输出格式: JSON List
    [
      {
        "subject": "激光功率",
        "predicate": "影响",
        "object": "焊缝熔深",
        "context": {"material": "Ti-6Al-4V", "shielding": "Ar"},
        "confidence": 0.95,
        "quantitative_value": 500,
        "quantitative_unit": "W",
        "evidence_text": "..."
      }
    ]
    
    文献段落:
    ────────
    {chunk}
    """
    
    response = llm_call(
        model="qwen-7b-instruct",  # 或 Gemini API
        prompt=build_prompt(chunk, entity_registry),
        temperature=0.3,
        max_tokens=1024
    )
    
    claims = parse_json(response)
    return [Claim(**c) for c in claims]
```

**成本估算**:
- 每个 chunk: ~200 tokens
- 总 chunks: ~50K (100 节点群落)
- 总成本: 50K × 200 tokens / 1M × $0.02 = ~$0.10/1000 chunks

#### 方式 2：规则抽取（快速，精度中等）

```python
def extract_claims_via_regex(chunk: str, entity_registry: EntityRegistry) -> List[Claim]:
    """
    使用预定义模式快速抽取声明
    
    规则模板:
    ─────────
    Pattern 1: [实体] + [动词] + [实体/值]
      - {entity1} (改善|提升|增加|提高|减少|降低) {entity2}
      - {entity1} 与 {entity2} (呈正相关|呈负相关)
    
    Pattern 2: 因果链
      - 当 {condition} 时，{entity1} 会 {action}
      - 由于 {cause}，{effect}
    
    Pattern 3: 量化声明
      - {entity} = {value} {unit}
      - {entity} 范围: {min}-{max} {unit}
      - {entity} 从 {old_val} 变化到 {new_val}
    """
    
    claims = []
    
    # 句子级别分割
    sentences = chunk.split("。")
    
    for sent in sentences:
        # 尝试 Pattern 1: 二元关系
        match = re.search(
            r'(\w+(?:[\u4e00-\u9fff]+)*)'  # entity1 (中英混合)
            r'(改善|提升|增加|改进|减少|降低|控制|影响|导致)',  # verb
            sent
        )
        if match:
            subject_text = match.group(1)
            predicate_text = match.group(2)
            
            # 查找对应实体
            subject = entity_registry.fuzzy_match(subject_text)
            if subject:
                # 提取 object (可能在句子后面)
                remaining = sent[match.end():]
                object_match = re.search(r'(\w+)', remaining)
                if object_match:
                    claims.append(Claim(
                        subject=subject,
                        predicate=predicate_text,
                        object=object_match.group(1),
                        confidence=0.7,  # 规则抽取置信度较低
                        evidence_text=sent
                    ))
    
    return claims
```

**优势**: 速度快 (100K chunks 需要 ~10 分钟)

#### 推荐策略：混合抽取

```python
def extract_claims_hybrid(chunks: List[str], entity_registry: EntityRegistry) -> List[Claim]:
    """
    混合使用 LLM 和规则
    
    优化策略:
    ──────
    1. 首先用规则快速过一遍 (10 分钟)
    2. 获取 confidence < 0.75 的声明
    3. 使用 LLM 二次精化 (成本低)
    4. LLM 聚焦于"复杂声明"，规则充当"初筛"
    
    预期成本:
    - 规则抽取: 0 成本，处理 ~10K chunks
    - LLM 精化: ~5K claims × $0.001/claim = $5
    - 总成本: ~$5 (控制在预算内)
    """
    
    # 步骤 1: 快速规则抽取
    claims_rough = []
    for chunk in chunks:
        claims_rough.extend(extract_claims_via_regex(chunk, entity_registry))
    
    # 步骤 2: LLM 精化低置信度声明
    low_confidence_claims = [c for c in claims_rough if c.confidence < 0.75]
    
    claims_refined = []
    for claim in low_confidence_claims:
        # 询问 LLM 是否确认
        confirmation = llm_refine_claim(claim, entity_registry)
        if confirmation['is_valid']:
            claim.confidence = confirmation['confidence']
        claims_refined.append(claim)
    
    # 步骤 3: 合并
    return [c for c in claims_rough if c.confidence >= 0.75] + claims_refined
```

---

## 核心算法 II：冲突检测

### 问题
给定两个声明，判定是否存在冲突

### 冲突检测决策树

```
输入: Claim A, Claim B
      ↓
Step 1: 主体匹配?
  ├─ 否 → return NO_CONFLICT
  └─ 是 ↓
      ├─ Step 2: 条件兼容?
      │  ├─ 完全不同的条件 → return CONDITIONAL_CONFLICT (需要新增条件)
      │  ├─ 部分重叠 ↓
      │  └─ 相同条件 ↓
      └─ Step 3: 宾体匹配?
         ├─ 不同的宾体 → return INDIRECT_CONFLICT
         ├─ 相同宾体，量化值相反 ↓
         └─ 相同宾体，量化值相同但置信度不同 ↓
             ↓
      Step 4: 计算冲突分数
         ├─ 完全相反 (如 +增加 vs -减少) → score = 1.0 (DIRECT_CONFLICT)
         ├─ 量化范围不重叠 → score = 0.9
         ├─ 量化范围部分重叠 → score = 0.5
         └─ 完全重叠 → score = 0.1 (NO_CONFLICT)
```

### 实现细节

```python
from enum import Enum
from dataclasses import dataclass
from typing import Tuple

class ConflictType(Enum):
    NO_CONFLICT = 0              # 无冲突
    DIRECT_CONFLICT = 1          # 直接矛盾
    CONDITIONAL_CONFLICT = 2     # 条件冲突
    INDIRECT_CONFLICT = 3        # 间接冲突 (因果链不一致)
    QUANTITATIVE_CONFLICT = 4    # 量化数值冲突

@dataclass
class ConflictResult:
    conflict_type: ConflictType
    severity_score: float              # 0-1, 越高越严重
    explanation: str
    required_conditions: List[str]     # 消解冲突需的条件

def detect_conflict(claim_a: Claim, claim_b: Claim) -> ConflictResult:
    """
    主冲突检测函数
    """
    
    # 步骤 1: 主体匹配检查
    subject_sim = semantic_similarity(claim_a.subject, claim_b.subject)
    if subject_sim < 0.7:  # 主体不匹配
        return ConflictResult(
            conflict_type=ConflictType.NO_CONFLICT,
            severity_score=0.0,
            explanation="主体不匹配"
        )
    
    # 步骤 2: 条件兼容性检查
    condition_compat = check_condition_compatibility(claim_a.context, claim_b.context)
    
    if condition_compat == "INCOMPATIBLE":
        # 条件完全不同 → 条件冲突
        return ConflictResult(
            conflict_type=ConflictType.CONDITIONAL_CONFLICT,
            severity_score=0.3,
            explanation=f"条件冲突: A在{claim_a.context}成立，B在{claim_b.context}成立",
            required_conditions=[...conditions to reconcile...]
        )
    
    # 步骤 3: 宾体和谓词匹配
    object_sim = semantic_similarity(claim_a.object, claim_b.object)
    if object_sim < 0.7:
        # 宾体不同 → 间接冲突
        return ConflictResult(
            conflict_type=ConflictType.INDIRECT_CONFLICT,
            severity_score=0.5,
            explanation=f"因果链不一致: {claim_a.subject}的影响目标不同"
        )
    
    # 步骤 4: 谓词相反性检查
    predicate_opposition = check_predicate_opposition(claim_a.predicate, claim_b.predicate)
    
    if predicate_opposition > 0.8:  # 谓词相反
        # 可能的直接冲突，检查量化值
        if claim_a.quantitative_value and claim_b.quantitative_value:
            # 量化值冲突检测
            conflict_score = calculate_quantitative_conflict(
                claim_a.quantitative_value,
                claim_b.quantitative_value,
                claim_a.quantitative_range,
                claim_b.quantitative_range
            )
            
            return ConflictResult(
                conflict_type=ConflictType.DIRECT_CONFLICT if conflict_score > 0.8 
                               else ConflictType.QUANTITATIVE_CONFLICT,
                severity_score=conflict_score,
                explanation=f"直接矛盾: 声明 A({claim_a.evidence_text[:50]}) "
                           f"vs 声明 B({claim_b.evidence_text[:50]})"
            )
        else:
            # 非量化直接冲突
            return ConflictResult(
                conflict_type=ConflictType.DIRECT_CONFLICT,
                severity_score=0.9,
                explanation=f"直接矛盾: {claim_a.subject}{claim_a.predicate} "
                           f"vs 不{claim_b.predicate}"
            )
    
    # 否则无冲突
    return ConflictResult(
        conflict_type=ConflictType.NO_CONFLICT,
        severity_score=0.0,
        explanation="无冲突"
    )

def check_condition_compatibility(context_a: Dict, context_b: Dict) -> str:
    """
    检查两个条件是否兼容
    
    返回值:
    - "COMPATIBLE": 条件相同或兼容
    - "OVERLAPPING": 条件部分重叠
    - "INCOMPATIBLE": 条件互斥
    """
    
    if not context_a or not context_b:
        return "COMPATIBLE"
    
    # 检查是否有互斥的条件值
    for key in set(context_a.keys()) & set(context_b.keys()):
        if context_a[key] != context_b[key]:
            # 检查是否真的互斥（不是简单的别名）
            if not are_equivalent(context_a[key], context_b[key]):
                return "INCOMPATIBLE"
    
    return "COMPATIBLE"

def check_predicate_opposition(pred_a: str, pred_b: str) -> float:
    """
    计算两个谓词的相反性 (0-1)
    
    相反对:
    - 增加 vs 减少: 0.95
    - 提升 vs 降低: 0.93
    - 改善 vs 恶化: 0.90
    """
    
    opposition_pairs = [
        ("增加", "减少"), ("增强", "减弱"),
        ("提升", "降低"), ("改善", "恶化"),
        ("加快", "减慢"), ("升高", "下降"),
    ]
    
    for pair in opposition_pairs:
        if (pred_a in pair and pred_b in pair):
            return 0.95
    
    # 否则使用语义相似度的负值
    sim = semantic_similarity(pred_a, pred_b)
    return max(0, 1 - sim)  # 不相似 → 较可能相反

def calculate_quantitative_conflict(val_a: float, val_b: float,
                                   range_a: Tuple[float, float],
                                   range_b: Tuple[float, float]) -> float:
    """
    计算两个量化声明的冲突分数
    
    逻辑:
    1. 如果范围完全不重叠 → score = 1.0 (完全冲突)
    2. 如果范围部分重叠 → score = overlap_ratio (部分冲突)
    3. 如果范围完全重叠 → score = 0.0 (无冲突)
    """
    
    # 默认范围 (如未指定)
    if not range_a:
        range_a = (val_a * 0.9, val_a * 1.1)
    if not range_b:
        range_b = (val_b * 0.9, val_b * 1.1)
    
    # 检查是否不重叠
    if range_a[1] < range_b[0] or range_b[1] < range_a[0]:
        return 1.0  # 完全不重叠
    
    # 计算重叠比例
    overlap_start = max(range_a[0], range_b[0])
    overlap_end = min(range_a[1], range_b[1])
    overlap = overlap_end - overlap_start
    
    range_a_size = range_a[1] - range_a[0]
    range_b_size = range_b[1] - range_b[0]
    
    overlap_ratio = 2 * overlap / (range_a_size + range_b_size)
    
    # 冲突分数 = 1 - overlap_ratio
    return max(0, 1 - overlap_ratio)
```

---

## 核心算法 III：冲突分类

### 问题
对检测到的冲突进行分类和严重程度评估

### 冲突分类矩阵

```
                      直接冲突     间接冲突    条件冲突    量化冲突
────────────────────────────────────────────────────────────
严重程度
  Level 4 (严重)      √                        
  Level 3 (高)        √         √√              √√
  Level 2 (中)                  √              √         √√
  Level 1 (低)                                            √
────────────────────────────────────────────────────────────
```

### 分类逻辑

```python
@dataclass
class ClassifiedConflict:
    conflict_id: str
    type: ConflictType
    severity_level: int              # 1-4 (低到严重)
    claims_involved: List[Claim]
    evidence_strength: float         # 0-1 (证据充分度)
    temporal_info: Dict              # 时间维度
    timeline_evolution: str          # "稳定" | "演变中" | "矛盾涌现"
    resolution_suggestions: List[str]

def classify_conflict(conflict_result: ConflictResult,
                     claims: List[Claim],
                     entity_timeline: Dict,
                     eval_queries: List[str]) -> ClassifiedConflict:
    """
    对冲突进行多维度分类
    """
    
    severity_level = 1
    
    # 维度 1: 冲突类型严重性
    if conflict_result.conflict_type == ConflictType.DIRECT_CONFLICT:
        severity_level = max(severity_level, 3)
        
        # 如果涉及安全相关的实体，升级为 Level 4
        if any(is_safety_critical(c.subject) for c in claims):
            severity_level = 4
    
    elif conflict_result.conflict_type == ConflictType.DIRECT_CONFLICT:
        severity_level = max(severity_level, 2)
    
    # 维度 2: 时间维度分析
    temporal_info = analyze_temporal_dimension(claims, entity_timeline)
    
    # 如果是时间演变 (知识更新)，降低严重性
    if temporal_info['evolution'] == "EVOLUTION":
        severity_level = max(1, severity_level - 1)
    
    # 维度 3: 证据强度
    avg_confidence = sum(c.confidence for c in claims) / len(claims)
    evidence_strength = avg_confidence
    
    # 维度 4: 影响范围 (在多少条 eval_queries 中出现)
    impact_range = calculate_impact_range(claims, eval_queries)
    if impact_range > 0.5:  # 影响超过 50% 的查询
        severity_level = min(4, severity_level + 1)
    
    # 生成建议
    suggestions = generate_resolution_suggestions(conflict_result, claims, temporal_info)
    
    return ClassifiedConflict(
        conflict_id=generate_conflict_id(claims),
        type=conflict_result.conflict_type,
        severity_level=severity_level,
        claims_involved=claims,
        evidence_strength=evidence_strength,
        temporal_info=temporal_info,
        timeline_evolution=temporal_info['evolution'],
        resolution_suggestions=suggestions
    )

def analyze_temporal_dimension(claims: List[Claim], entity_timeline: Dict) -> Dict:
    """
    分析冲突的时间维度
    
    返回:
    {
      "evolution": "STABLE" | "EVOLUTION" | "CONTRADICTION",
      "timeline": {year: count},
      "trend": "increasing" | "decreasing" | "cyclical",
      "gap_detected": bool
    }
    """
    
    years = sorted(set(c.publication_year for c in claims))
    timeline = {year: sum(1 for c in claims if c.publication_year == year) 
                for year in years}
    
    # 检测是否存在知识演变
    if len(years) >= 2:
        # 如果旧年份的声明被新年份的声明否定，这是"EVOLUTION"
        # 而不是"CONTRADICTION"
        evolution_score = detect_evolution(claims, entity_timeline)
        if evolution_score > 0.7:
            return {
                "evolution": "EVOLUTION",
                "timeline": timeline,
                "trend": detect_trend(timeline),
                "gap_detected": detect_gap(years)
            }
    
    return {
        "evolution": "STABLE" if len(set(c.publication_year for c in claims)) == 1 
                    else "CONTRADICTION",
        "timeline": timeline,
        "trend": detect_trend(timeline),
        "gap_detected": detect_gap(years)
    }

def generate_resolution_suggestions(conflict_result: ConflictResult,
                                   claims: List[Claim],
                                   temporal_info: Dict) -> List[str]:
    """
    生成解决建议
    """
    
    suggestions = []
    
    if temporal_info['gap_detected']:
        suggestions.append(
            "📚 检测到时间缺口，建议查阅该时期的相关文献以补充知识"
        )
    
    if temporal_info['evolution'] == "EVOLUTION":
        suggestions.append(
            "🔄 该冲突可能反映知识的递进演变，建议按时间顺序审视"
        )
    
    if conflict_result.required_conditions:
        suggestions.append(
            f"⚙️ 建议在以下条件下分别验证: {', '.join(conflict_result.required_conditions)}"
        )
    
    if len(claims) >= 3:
        suggestions.append(
            "🔬 多源证据存在分歧，建议开展实验验证"
        )
    
    return suggestions
```

---

## 核心算法 IV：推演链构造

### 问题
将冲突组织成结构化的推演链，方便用户理解推理逻辑

### 推演链结构

```python
@dataclass
class ReasoningChain:
    """推演链：从输入查询到最终推论"""
    chain_id: str
    query: str                              # 用户查询
    
    # 推演步骤
    steps: List[ReasoningStep]              # [检索 → 提取 → 关联 → 冲突...]
    
    # 最终结论
    conclusion: str
    conclusion_confidence: float
    
    # 冲突信息
    conflicts_involved: List[ClassifiedConflict]
    conflict_impact: str                    # "HIGH" | "MEDIUM" | "LOW"
    
    # 建议
    next_steps: List[str]

@dataclass
class ReasoningStep:
    step_id: int
    step_type: str                          # "RETRIEVAL" | "EXTRACTION" | "ASSOCIATION" | "CONFLICT" | "SYNTHESIS"
    description: str
    inputs: List[str]
    outputs: List[str]
    confidence: float

def construct_reasoning_chain(
    query: str,
    retrieval_results: List[Document],
    extracted_claims: List[Claim],
    detected_conflicts: List[ClassifiedConflict],
    entity_timeline: Dict
) -> ReasoningChain:
    """
    构造完整的推演链
    """
    
    chain = ReasoningChain(
        chain_id=generate_chain_id(),
        query=query,
        steps=[],
        conflicts_involved=detected_conflicts,
        conflict_impact=assess_conflict_impact(detected_conflicts),
        next_steps=[]
    )
    
    # 步骤 1: 检索
    chain.steps.append(ReasoningStep(
        step_id=1,
        step_type="RETRIEVAL",
        description=f"从知识库检索与 '{query}' 相关的文献",
        inputs=[query],
        outputs=[f"检索到 {len(retrieval_results)} 篇文献"],
        confidence=1.0
    ))
    
    # 步骤 2: 声明提取
    chain.steps.append(ReasoningStep(
        step_id=2,
        step_type="EXTRACTION",
        description=f"从 {len(retrieval_results)} 篇文献中提取结构化声明",
        inputs=[f"{len(retrieval_results)} 篇文献"],
        outputs=[f"提取 {len(extracted_claims)} 条声明"],
        confidence=0.85  # 抽取置信度
    ))
    
    # 步骤 3: 关联分析
    # 对已提取的声明进行聚类和关联
    claim_groups = cluster_claims(extracted_claims)
    chain.steps.append(ReasoningStep(
        step_id=3,
        step_type="ASSOCIATION",
        description=f"将声明聚类成 {len(claim_groups)} 个论点组",
        inputs=[f"{len(extracted_claims)} 条声明"],
        outputs=[f"{len(claim_groups)} 个论点组"],
        confidence=0.80
    ))
    
    # 步骤 4: 冲突检测和分类
    if detected_conflicts:
        conflict_summary = summarize_conflicts(detected_conflicts)
        chain.steps.append(ReasoningStep(
            step_id=4,
            step_type="CONFLICT",
            description=f"检测到 {len(detected_conflicts)} 个冲突",
            inputs=[f"{len(claim_groups)} 个论点组"],
            outputs=[conflict_summary],
            confidence=0.75
        ))
    
    # 步骤 5: 综合推论
    conclusion = synthesize_conclusion(claim_groups, detected_conflicts, entity_timeline)
    chain.steps.append(ReasoningStep(
        step_id=5,
        step_type="SYNTHESIS",
        description="基于提取的声明和检测的冲突，合成最终推论",
        inputs=[f"{len(claim_groups)} 个论点组", f"{len(detected_conflicts)} 个冲突"],
        outputs=[conclusion],
        confidence=0.70
    ))
    
    chain.conclusion = conclusion
    chain.conclusion_confidence = 0.70
    
    # 生成建议后续步骤
    chain.next_steps = generate_next_steps(chain, entity_timeline)
    
    return chain

def cluster_claims(claims: List[Claim]) -> List[List[Claim]]:
    """
    根据主体和宾体将声明聚类
    """
    
    graph = {}
    for claim in claims:
        key = (claim.subject, claim.object)
        if key not in graph:
            graph[key] = []
        graph[key].append(claim)
    
    return list(graph.values())

def summarize_conflicts(conflicts: List[ClassifiedConflict]) -> str:
    """
    生成冲突摘要
    
    示例:
    "检测到 3 个冲突:
     1. 直接冲突 (Level 3): 激光功率与熔深的影响关系
     2. 条件冲突 (Level 2): 在不同材料下的表现差异
     3. 时间冲突 (Level 1): 研究结论在不同年份的演变"
    """
    
    high_level = [c for c in conflicts if c.severity_level >= 3]
    medium_level = [c for c in conflicts if c.severity_level == 2]
    low_level = [c for c in conflicts if c.severity_level == 1]
    
    summary = f"检测到 {len(conflicts)} 个冲突:\n"
    if high_level:
        summary += f"  🔴 {len(high_level)} 个高级冲突\n"
    if medium_level:
        summary += f"  🟡 {len(medium_level)} 个中级冲突\n"
    if low_level:
        summary += f"  🟢 {len(low_level)} 个低级冲突\n"
    
    return summary

def synthesize_conclusion(claim_groups: List[List[Claim]],
                         conflicts: List[ClassifiedConflict],
                         entity_timeline: Dict) -> str:
    """
    综合最终推论
    
    逻辑:
    1. 找到共识声明 (大多数文献支持)
    2. 标记有争议的声明 (冲突多)
    3. 识别演变性声明 (时间上的递进)
    """
    
    # 识别主流声明 (>60% 的证据支持)
    consensus_groups = [g for g in claim_groups if len(g) > len(claim_groups) * 0.6]
    
    # 识别争议声明
    disputed_groups = [g for g in claim_groups if len(g) <= len(claim_groups) * 0.6]
    
    conclusion = "基于文献分析:\n\n"
    
    if consensus_groups:
        conclusion += "✅ 共识观点:\n"
        for group in consensus_groups[:3]:  # 最多列 3 个
            conclusion += f"  - {group[0].subject} {group[0].predicate} {group[0].object}\n"
    
    if disputed_groups:
        conclusion += "\n⚠️ 争议观点:\n"
        for group in disputed_groups[:3]:
            conclusion += f"  - {group[0].subject}的影响存在分歧\n"
    
    if conflicts:
        conclusion += f"\n❌ 检测到 {len(conflicts)} 个冲突需要澄清\n"
    
    return conclusion

def generate_next_steps(chain: ReasoningChain, entity_timeline: Dict) -> List[str]:
    """
    根据推演链生成后续建议
    """
    
    suggestions = []
    
    # 根据冲突情况生成建议
    high_severity_conflicts = [c for c in chain.conflicts_involved if c.severity_level >= 3]
    if high_severity_conflicts:
        suggestions.append(
            "🔬 建议通过实验或查阅更新文献来解决高级冲突"
        )
    
    # 根据覆盖缺口
    for entity in extract_entities_from_chain(chain):
        if entity in entity_timeline:
            gaps = detect_coverage_gaps(entity_timeline[entity])
            if gaps:
                suggestions.append(
                    f"📚 {entity} 在 {gaps} 有覆盖缺口"
                )
    
    # 根据证据强度
    avg_confidence = mean([step.confidence for step in chain.steps])
    if avg_confidence < 0.70:
        suggestions.append(
            "📖 证据强度不足，建议查阅更多高引用文献"
        )
    
    return suggestions
```

---

## 实现路线图

### 第一阶段：基础框架 (Day 1)
- [ ] 定义数据结构 (`Claim`, `ClassifiedConflict`, `ReasoningChain`)
  - ⭐ 包含 `AuthorityAssessment` (【决策 2】)
- [ ] 实现声明抽取模块 (LLM + 规则混合)
- [ ] 实现冲突检测算法
  - ⭐ 集成同义词表加载器 (【决策 1】)
  - ⭐ 实现混合语义对齐 (规则→向量→LLM)
- [ ] 创建本地同义词表 (`p2_synonym_dictionary.json`)

**交付**: `p2_claim_extractor.py`, `p2_conflict_detector.py`, `p2_synonym_dictionary.json`

### 第二阶段：分类和推演 (Day 2)
- [ ] 实现冲突分类算法
- [ ] 实现时间维度分析
- [ ] 实现推演链构造

**交付**: `p2_conflict_classifier.py`, `p2_reasoning_chain_builder.py`

### 第三阶段：集成和优化 (Day 3)
- [ ] 集成到 P1 R-Layer 的输出
- [ ] 实现异步处理 (处理大量查询)
- [ ] 性能优化

**交付**: `p2_reasoning_engine.py` (主文件)

### 第四阶段：测试和验证 (Day 4)
- [ ] 单元测试 (声明抽取、冲突检测)
- [ ] E2E 集成测试
- [ ] 性能基准 (处理 100 条 eval_queries 的耗时)

**交付**: `test_p2_reasoning_engine.py`

### 第五阶段：完成和交付 (Day 5)
- [ ] 生成 P2 完成报告
- [ ] 代码审查和优化
- [ ] P3 规划

**交付**: `P2_COMPLETION_REPORT.md`, `P2_IMPLEMENTATION_CODE.md`

---

## 质量保证

### 单元测试策略

#### 测试 1: 声明抽取准确性

```python
def test_claim_extraction():
    """测试声明抽取的准确性和覆盖度"""
    
    test_chunks = [
        "激光功率为 500W 时，焊缝熔深增加 30%。",
        "在 Ti-6Al-4V 材料上，高功率会导致热裂纹。",
        "实验结果表明，低功率焊接可以改善表面质量。"
    ]
    
    expected_claims = 3
    extracted = extract_claims_hybrid(test_chunks, entity_registry)
    
    assert len(extracted) >= expected_claims * 0.8  # 允许 20% 的遗漏
    assert all(c.confidence > 0.6 for c in extracted)  # 置信度要求
```

#### 测试 2: 冲突检测准确性

```python
def test_conflict_detection():
    """测试冲突检测的准确性"""
    
    # 测试用例 1: 直接矛盾
    claim_a = Claim(
        subject="激光功率",
        predicate="增加",
        object="焊缝熔深"
    )
    claim_b = Claim(
        subject="激光功率",
        predicate="减少",
        object="焊缝熔深"
    )
    
    result = detect_conflict(claim_a, claim_b)
    assert result.conflict_type == ConflictType.DIRECT_CONFLICT
    assert result.severity_score > 0.8
    
    # 测试用例 2: 无冲突
    claim_c = Claim(
        subject="焊接速度",
        predicate="增加",
        object="焊接效率"
    )
    
    result = detect_conflict(claim_a, claim_c)
    assert result.conflict_type == ConflictType.NO_CONFLICT
```

#### 测试 3: 推演链生成

```python
def test_reasoning_chain_generation():
    """测试推演链的完整性和逻辑性"""
    
    chain = construct_reasoning_chain(
        query="激光功率如何影响焊缝质量",
        retrieval_results=mock_retrieval_results,
        extracted_claims=mock_claims,
        detected_conflicts=mock_conflicts,
        entity_timeline=mock_timeline
    )
    
    # 验证步骤完整性
    assert len(chain.steps) >= 4  # 至少 4 个步骤
    assert chain.steps[0].step_type == "RETRIEVAL"
    assert chain.steps[-1].step_type == "SYNTHESIS"
    
    # 验证结论非空
    assert len(chain.conclusion) > 0
    assert chain.conclusion_confidence > 0
```

### 性能基准

```
目标:
  - 处理 1000 条评估查询: < 10 分钟
  - 声明抽取 (规则): ~50K chunks / 10 min
  - 冲突检测: O(n²) 但有早停机制
  
目前预估:
  规则抽取:   10 分钟
  LLM 精化:   2 分钟 (批量)
  冲突检测:   3 分钟 (50K claims 比较)
  推演链构造: 2 分钟
  ─────────────────
  总计:       ~17 分钟 (可优化)
```

### 准确性度量

```
指标:
  1. 声明抽取 Precision: 目标 > 0.85
  2. 声明抽取 Recall: 目标 > 0.75
  3. 冲突检测 F1-Score: 目标 > 0.80
  4. 推演链逻辑连贯性: 人工评分 > 4/5
  
验证方法:
  - 在 eval_queries_v1.0.jsonl 的 20 条查询上人工标注
  - 对比算法输出与人工标注
  - 计算 Precision/Recall
```

---

## 算法总结

| 模块 | 输入 | 输出 | 复杂度 | 成本 |
|------|------|------|--------|------|
| **声明抽取** | Chunks | Claims | O(n) | ~$5 (LLM) |
| **冲突检测** | Claims | Conflicts | O(n²) | $0 |
| **冲突分类** | Conflicts | ClassifiedConflicts | O(n) | $0 |
| **推演链** | ClassifiedConflicts | ReasoningChain | O(k) | $0 |

**总成本**: 约 **$5-10 USD** 用于首次处理

**总耗时**: 约 **15-20 分钟** 用于 50K chunks + 100 条查询

---

## 下一步行动

1. **实现声明抽取器** (Day 1)
   - 规则模板完善
   - LLM 提示词优化

2. **实现冲突检测** (Day 2)
   - 决策树测试
   - 量化冲突计算

3. **集成和测试** (Day 3-4)
   - 与 P1 R-Layer 对接
   - 性能基准测试

---

**算法设计完成 ✅ — 准备实现阶段**
