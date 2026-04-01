# 关注点注册表设计文档 (Focus Registry Design)

**版本**: v1.0  
**日期**: 2026-04-01  
**作者**: System Design  
**状态**: In Progress - Implementation Phase

---

## 1. 概述

### 问题陈述

在学术文献语义路由系统中，关注点（Focus）的管理面临三个核心问题：

1. **重复污染** - 同一篇文献中，同一关注点在不同位置重复出现时，会被多次加入主关注点表，导致主表膨胀
2. **同义词碎片化** - "热输入"、"焊接热输入"、"heat input" 作为三个独立的关注点存在，导致向量化冗余和路由准确度下降
3. **出现追踪缺失** - 无法记录某个关注点在哪些文献、哪些位置出现，影响后续的证据链接和可解释性

### 解决方案

实现**关注点规范化注册表** (Focus Registry)，包含三层结构：

1. **主关注点表** (`focus_registry`) - 规范化的关注点，一个 `canonical_name` ↔ 一个 `id`
2. **文献映射** (`doc_map`) - 记录每篇文献涉及哪些关注点，避免文献级重复
3. **出现记录** (`mentions`) - 记录每个关注点在文献中的具体位置和上下文

---

## 2. 核心设计原则

### 2.1 规范化 (Normalization)

参考：Microsoft Dynamics 365 数据统一文档的规范化策略

**规范化层次**（按优先级）：

1. **Unicode 规范化** - 统一字符形式（如 "à" → "a"）
   - 方法: `unicodedata.normalize('NFKC', text)`
   - 作用: 处理输入中的特殊字符、重音符号

2. **文本清理** - 移除符号、多余空格、大小写统一
   - 规则:
     - 移除 `!？#$%&'()+,.-*/:;<=>@^*~{}[] ` 等符号
     - 多个连续空格 → 单个空格
     - 全转换为小写（便于匹配，但主表中仍保持原始大小写）

3. **形式转换** - 中英文变体和同义词映射
   - 例: "激光焊接" ↔ "laser welding"
   - 例: "热输入" ↔ "焊接热输入" (via alias map)

### 2.2 去重 (Deduplication)

**三层去重键**：

| 层级 | 去重对象 | 去重键 | 处理方式 |
|------|--------|--------|----------|
| **全局** | 主关注点表 | `canonical_name` | 唯一，一个词汇 = 一条记录 |
| **文献** | 文献内关注点 | `doc_id + canonical_name` | 同文献内重复 → 合并为单条 |
| **提及** | 出现记录 | `doc_id + focus_id + evidence_hash` | 完全重复 → 覆盖 |

**实现策略**：

- 入库时先规范化文本 → 查询是否已存在 → 存在则更新，不存在则新增
- 文献级去重：在处理单篇文献时维护 `{doc_id → Set[canonical_name]}`，避免重复插入
- Mention 级去重：计算 snippet 的 hash，相同 hash 的 mention 不重复记录

### 2.3 别名归并 (Alias Consolidation)

参考：Microsoft 中的 "alias mapping" 和 ASIM 的 aliases 概念

**别名来源**（优先级从低到高）：

1. **规范化后精确匹配** - 最低优先级
   ```
   "热 输 入" (normalized) == "热输入" (normalized) → 合并
   ```

2. **手工别名表** - 中优先级（由领域专家维护）
   ```json
   {
     "焊接热输入": "热输入",
     "heat input": "热输入",
     "氮化合金": "氮合金化"
   }
   ```

3. **LLM 同义词判定** - 最高优先级（需要时触发）
   ```
   query_llm("这两个词是同义词吗？'热输入' vs '焊接热输入'") → "yes" → 合并
   ```

**实现细节**：

- 别名表存储在 `focus_registry` 条目的 `aliases` 字段
- 当发现新词汇时，首先查询别名表，确定应该合并到哪个 canonical_name
- 如果未找到，可选择创建新的 canonical focus，或在评审时由人工判定

---

## 3. 数据结构 (Schema)

### 3.1 完整 JSON Schema

```json
{
  "version": "v2",
  "updated_at": "ISO8601 timestamp",
  
  "points": [
    "热输入控制",
    "晶粒细化",
    "氮传输",
    ...
  ],
  
  "focus_registry": [
    {
      "id": "focus_heat_input",
      "canonical_name": "热输入控制",
      "aliases": [
        "焊接热输入",
        "heat input",
        "thermal input"
      ],
      "category": "工艺参数",
      "description": "激光焊接过程中的输入热量",
      "source_docs": ["paper_a", "paper_b", "paper_c"],
      "mention_count": 12,
      "created_at": "ISO8601",
      "last_updated_at": "ISO8601"
    },
    {
      "id": "focus_grain_refine",
      "canonical_name": "晶粒细化",
      "aliases": ["grain refinement", "fine grain structure"],
      "category": "组织控制",
      "description": "通过工艺控制实现焊接区晶粒的微细化",
      "source_docs": ["paper_a", "paper_d"],
      "mention_count": 8,
      "created_at": "ISO8601",
      "last_updated_at": "ISO8601"
    }
  ],
  
  "doc_map": {
    "paper_a": {
      "title": "Laser Welding Parameters Study",
      "source_path": "/papers/paper_a.pdf",
      "focus_ids": ["focus_heat_input", "focus_grain_refine"],
      "focus_names": ["热输入控制", "晶粒细化"],
      "mention_count": {
        "focus_heat_input": 6,
        "focus_grain_refine": 4
      },
      "processed_at": "ISO8601"
    },
    "paper_b": {
      "title": "Thermal Control in Arc Welding",
      "source_path": "/papers/paper_b.md",
      "focus_ids": ["focus_heat_input"],
      "focus_names": ["热输入控制"],
      "mention_count": {
        "focus_heat_input": 6
      },
      "processed_at": "ISO8601"
    }
  },
  
  "mentions": [
    {
      "mention_id": "mention_paper_a_heat_1",
      "focus_id": "focus_heat_input",
      "doc_id": "paper_a",
      "doc_title": "Laser Welding Parameters Study",
      "section": "results",
      "page": 5,
      "paragraph": 3,
      "snippet": "With increase in the heat input, the HAZ width increases...",
      "source_type": "text",
      "evidence_hash": "sha256_hash_of_snippet",
      "extracted_at": "ISO8601"
    },
    {
      "mention_id": "mention_paper_a_heat_2",
      "focus_id": "focus_heat_input",
      "doc_id": "paper_a",
      "doc_title": "Laser Welding Parameters Study",
      "section": "discussion",
      "page": 7,
      "paragraph": 2,
      "snippet": "The thermal input directly affects cooling rate...",
      "source_type": "text",
      "evidence_hash": "sha256_hash_of_snippet",
      "extracted_at": "ISO8601"
    }
  ],
  
  "metadata": {
    "total_focus_points": 42,
    "total_documents": 15,
    "total_mentions": 347,
    "processing_stats": {
      "extracted_points": 156,
      "deduplicated_points": 114,
      "canonical_points": 42
    }
  }
}
```

### 3.2 向后兼容性

**旧版 schema** (focus_extractor v1)：
```json
{
  "timestamp": "...",
  "total_points": 42,
  "points": ["热输入", "晶粒细化", ...],
  "stats": {...}
}
```

**兼容策略**：
- 新版本在 `points` 字段中保留规范化后的关注点列表（来自 `focus_registry[].canonical_name`）
- `semantic_router.py` 优先读取 `focus_registry[].canonical_name`，如果不存在则回退到 `points[]`
- 这样旧代码仍能工作，新代码可利用更丰富的元数据

---

## 4. 核心操作流程

### 4.1 提取 → 规范化 → 入库流程

```
1. focus_extractor 从文献中提取原始关注点
   ↓ (例: ["热 输 入", "HEAT INPUT", "热输入"])
   
2. FocusRegistry.normalize_focus_text()
   ↓ (Unicode 正规化 + 清理 + 小写)
   → ["热输入", "heat input", "热输入"]
   
3. FocusRegistry.canonicalize_focus()
   ↓ (查询别名表，确定目标 canonical)
   → "热输入" (all aliased to same canonical)
   
4. FocusRegistry.upsert_focus()
   ↓ (检查是否已存在)
   → 如果不存在: 创建新的 focus record
   → 如果存在: 更新别名列表、更新时间戳
   
5. FocusRegistry.add_mention()
   ↓ (记录出现位置)
   → 在 mentions 表中添加一条记录
```

### 4.2 查询和路由流程

```
用户查询: "激光焊接中的热输入如何影响晶粒?"

1. SemanticRouter.route_query()
   ↓
2. 优先读取 focus_registry[].canonical_name
   → ["热输入控制", "晶粒细化", ...]
   ↓
3. 调用硅基流动向量化这些标准名称
   ↓
4. 计算查询与向量的相似度
   ↓
5. 返回 top-k 关注点
```

### 4.3 增量更新流程

```
处理新文献 paper_c.pdf

1. extract_from_document(paper_c.pdf) 
   → 提取: ["参数优化", "热输入", "新参数A"]
   
2. 对每个提取的点:
   a. normalize_focus_text()
   b. canonicalize_focus(alias_map)
   c. upsert_focus() → 返回 focus_id
   d. add_mention(focus_id, doc_id, snippet)
   
3. 更新 doc_map[paper_c]
   
4. 重新生成 focus_points.json
```

---

## 5. 防守逻辑和错误处理

### 5.1 输入验证

```python
def normalize_focus_text(text: str) -> str:
    """
    Rules:
    - text 必须是非空字符串
    - text 长度 2-100 个字符（过短或过长都不合理）
    - 返回小写的规范化形式
    """
    if not isinstance(text, str) or len(text.strip()) == 0:
        raise ValueError(f"Invalid focus text: '{text}'")
    if len(text) > 100:
        raise ValueError(f"Focus text too long (max 100 chars): '{text}'")
    # ... normalization logic
```

### 5.2 冲突检测

```python
def canonicalize_focus(text: str, alias_map: dict) -> str:
    """
    检查别名表中是否有冲突映射：
    - "热输入" → "热输入控制"
    - "热输入" → "焊接热输入"  ← 冲突！
    """
    normalized = normalize_focus_text(text)
    if normalized in alias_map:
        canonical = alias_map[normalized]
        # 验证 canonical 本身是否也是某个别名
        if canonical in alias_map:
            raise ValueError(f"Circular alias mapping: {normalized} → {canonical} → {alias_map[canonical]}")
        return canonical
    return normalized
```

### 5.3 唯一性约束

```python
def upsert_focus(canonical_name: str, ...) -> str:
    """
    约束：
    - canonical_name 必须唯一（按规范化后的值）
    - 同一个 doc_id + canonical_name 组合只能有一条 doc_map 记录
    - mention_id 必须唯一
    """
    normalized_canonical = normalize_focus_text(canonical_name)
    if not self._is_unique_canonical(normalized_canonical):
        raise ValueError(f"Duplicate canonical focus: {canonical_name}")
    # ... insertion logic
```

---

## 6. 去重规则详解

### 6.1 跨文献主去重

**场景**:
```
文献库中多篇文献都提到"热输入"，以不同的表述方式:
- paper_a: "heat input"
- paper_b: "热输入"
- paper_c: "焊接热输入"
```

**处理**:
1. 全部规范化为 "热输入"（中文为优先）
2. 通过别名表识别同义词
3. 在 `focus_registry` 中只创建一条记录: `id=focus_heat_input, canonical_name=热输入`
4. 这三篇文献都在 `doc_map` 和 `mentions` 中指向同一个 `focus_heat_input`

### 6.2 文献内重复去重

**场景**:
```
paper_a.pdf 中：
- 第 2 页: "The heat input was set to 2 kW"
- 第 5 页: "Increasing heat input reduces cooling rate"
- 第 8 页: "heat input parameter"

都被提取器识别为"热输入"
```

**处理**:
1. 在 `doc_map[paper_a].focus_ids` 中，`focus_heat_input` 只出现一次
2. 但在 `mentions` 中，会创建 3 条记录（因为 evidence_hash 不同）
3. `doc_map[paper_a].mention_count[focus_heat_input]` = 3

**结果**:
```json
"doc_map": {
  "paper_a": {
    "focus_ids": ["focus_heat_input", ...],  // 去重
    "mention_count": {
      "focus_heat_input": 3  // 统计
    }
  }
}
```

### 6.3 Mention 级完全去重

**场景**:
```
运行两次提取器，都会提取同一篇文献的同一个片段
```

**处理**:
1. 计算 snippet 的 SHA256 hash
2. 若 `(doc_id, focus_id, evidence_hash)` 组合已存在，则覆盖（而非重复插入）

---

## 7. 兼容性保证

### 7.1 semantic_router.py 的向后兼容

**旧代码**:
```python
router = SemanticRouter(focus_points_path="focus_points.json")
# 期望读取 focus_points.json，其中有 data["points"]
```

**新代码**:
```python
def _load_focus_points(self, focus_points_path: str):
    data = json.load(...)
    
    # 优先级 1: 新版 schema
    if "focus_registry" in data:
        self.focus_points = [item["canonical_name"] for item in data["focus_registry"]]
    
    # 优先级 2: 旧版 schema (fallback)
    elif "points" in data:
        self.focus_points = data["points"]
    
    else:
        raise ValueError("Invalid focus_points.json schema")
```

**保证**: 旧版 JSON（只有 `points` 字段）仍能被新版 `semantic_router.py` 读取

### 7.2 focus_extractor.py 的输出

**新版输出** (focus_points.json v2):
```json
{
  "version": "v2",
  "points": [...],  // ← 保留，用于兼容
  "focus_registry": [...],
  "doc_map": {...},
  "mentions": [...]
}
```

**保证**: `points` 字段始终包含 `focus_registry[].canonical_name` 的完整列表

---

## 8. 增量更新策略

### 8.1 全量重新生成 (Recommended)

```
python -m layers.focus_extractor --doc-folder ./papers --output focus_points.json
```

**优点**:
- 简单、可靠、易于调试
- 充分发挥规范化和去重的优势
- 别名表可以随时更新

**缺点**:
- 每次都需要重新处理所有文献

### 8.2 增量更新 (Future)

```
registry = FocusRegistry.load("focus_points.json")
new_doc = extract_and_normalize("new_paper.pdf")
registry.update_from_document(new_doc, doc_id="paper_new", alias_map=alias_map)
registry.save("focus_points.json")
```

**实现方式**:
- 加载现有的 `focus_points.json`
- 仅处理新文献
- 合并到现有的 registry
- 重新生成 JSON

**当前状态**: 未实现（可作为 v1.1 功能）

---

## 9. 验收标准

### 用例 1: 同义词自动归并

**输入**:
```
文献: paper_a.md
内容片段:
  "heat input is controlled"
  "焊接热输入 parameters"
  "热输入 affects cooling"
```

**提取器输出**:
```
["heat input", "焊接热输入", "热输入"]
```

**registry 处理后**:
```json
{
  "focus_registry": [
    {
      "id": "focus_heat_input",
      "canonical_name": "热输入",
      "aliases": ["heat input", "焊接热输入"],
      "source_docs": ["paper_a"],
      "mention_count": 3
    }
  ],
  "doc_map": {
    "paper_a": {
      "focus_ids": ["focus_heat_input"],  // ← 单个 id
      "focus_names": ["热输入"],  // ← 单个名称
      "mention_count": { "focus_heat_input": 3 }
    }
  },
  "mentions": [
    { "mention_id": "...", "focus_id": "focus_heat_input", "doc_id": "paper_a", "snippet": "heat input is controlled..." },
    { "mention_id": "...", "focus_id": "focus_heat_input", "doc_id": "paper_a", "snippet": "焊接热输入 parameters" },
    { "mention_id": "...", "focus_id": "focus_heat_input", "doc_id": "paper_a", "snippet": "热输入 affects cooling" }
  ]
}
```

**验证**: ✅ 三个不同表述的同一概念被归并到一个 canonical focus

### 用例 2: 多文献关注点映射

**输入**:
```
文献库:
  - paper_a.md: 提到"热输入"和"晶粒细化"
  - paper_b.md: 只提到"热输入"
  - paper_c.md: 提到"参数优化"和"晶粒细化"
```

**focus_registry 中**:
```json
{
  "focus_registry": [
    { "id": "focus_heat_input", "canonical_name": "热输入", "source_docs": ["paper_a", "paper_b"] },
    { "id": "focus_grain", "canonical_name": "晶粒细化", "source_docs": ["paper_a", "paper_c"] },
    { "id": "focus_param", "canonical_name": "参数优化", "source_docs": ["paper_c"] }
  ]
}
```

**doc_map 中**:
```json
{
  "paper_a": {
    "focus_ids": ["focus_heat_input", "focus_grain"],
    "focus_names": ["热输入", "晶粒细化"]
  },
  "paper_b": {
    "focus_ids": ["focus_heat_input"],
    "focus_names": ["热输入"]
  },
  "paper_c": {
    "focus_ids": ["focus_grain", "focus_param"],
    "focus_names": ["晶粒细化", "参数优化"]
  }
}
```

**验证**: ✅ 每篇文献准确映射到其实际关注的关注点集合，无重复、无遗漏

### 用例 3: semantic_router 兼容性

**输入**:
```python
# 使用新版 focus_points.json
router = SemanticRouter(
    api_key="...",
    focus_points_path="focus_points.json"
)

results = router.route_query("激光焊接中热输入如何影响晶粒？", top_k=3)
```

**验证**:
```python
assert isinstance(results, list)
assert len(results) <= 3
assert all(isinstance(p, str) for p in results)
# 返回的应该是规范化的 canonical_name，如 ["热输入", "晶粒细化", ...]
```

**验证**: ✅ semantic_router 能正确读取新版 schema，向量化和路由工作正常

---

## 10. 后续扩展空间

### 10.1 PDF 原生支持

当前: 需要手工转换或用 PyPDF2/pdfplumber  
未来: 直接集成 Marker、Docling 等高阶 PDF 解析工具

### 10.2 LLM 同义词检测

当前: 静态别名表  
未来: 动态查询 LLM 判断两个词是否同义（可选、按需触发）

### 10.3 向量预计算和缓存

当前: 路由时实时向量化  
未来: 在 registry 中预计算所有 canonical_name 的向量，存储在本地，加速查询

### 10.4 分层关注点

当前: 平铺结构  
未来: 支持关注点分类（如 "工艺参数 > 热输入控制"），便于更精细的路由和可视化

---

## 11. 相关文档和参考

- **Microsoft Dynamics 365 数据统一**: [Remove duplicates](https://learn.microsoft.com/dynamics365/customer-insights/data/data-unification-duplicates)
- **Microsoft ASIM Aliases**: [Advanced Security Information Model Aliases](https://learn.microsoft.com/azure/sentinel/normalization-about-schemas#aliases)
- **Unicode 规范化**: [Using Unicode Normalization](https://learn.microsoft.com/windows/win32/intl/using-unicode-normalization-to-represent-strings)
- **RAG 数据管道**: [Build an unstructured data pipeline for RAG](https://learn.microsoft.com/azure/databricks/generative-ai/tutorials/ai-cookbook/quality-data-pipeline-rag)

---

**下一步**: 查看 `focus_registry.py` 的实现细节和 smoke test 用例。
