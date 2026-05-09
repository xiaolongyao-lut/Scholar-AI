# TOLF-Wiki 集成设计

## 文档状态

**版本**：v1.0
**状态**：Draft
**创建日期**：2026-05-04
**负责人**：待明确

---

## 1. 背景与目标

### 1.1 当前状态

**TOLF 实现**：
- 已实现：`layers/tolf_engine.py`, `test_tolf_engine.py`
- 功能：judgment summary、template export、review packet、inspection packet、bilingual control、query bridge diagnostics
- 状态：可选实验能力，未替换默认主链

**Wiki 实现**：
- 已完成 Wave 0-14
- 功能：source registry、page store、citation validator、compiler、query、graph、doctor、review queue、API、前端工作台
- 状态：基础设施已完成，待集成 TOLF

### 1.2 集成目标

**Phase 1（当前）**：TOLF 与 RAG 并行
- TOLF 和 RAG 互不干扰，独立运行
- 用户可选择使用 TOLF 或 RAG

**Phase 2（Wave 15）**：TOLF 输出进入 Wiki
- TOLF judgment summary → Wiki synthesis page
- TOLF review packet → Wiki review queue
- TOLF inspection packet → Wiki doctor report

**Phase 3（未来）**：TOLF 替换默认主链
- 主链切换：RAG → TOLF
- 评测对照：TOLF vs RAG
- 回滚点：保留 RAG 兼容层

---

## 2. 集成点设计

### 2.1 TOLF Judgment → Wiki Synthesis

**TOLF 输出格式**（推测，需验证）：
```json
{
  "judgment_id": "j-20260504-001",
  "query": "焊接缺陷检测方法",
  "summary": "...",
  "evidence": [...],
  "confidence": 0.85,
  "created_at": "2026-05-04T10:00:00Z"
}
```

**Wiki Synthesis 输入格式**：
```json
{
  "page_path": "synthesis/j-20260504-001.md",
  "frontmatter": {
    "title": "焊接缺陷检测方法",
    "status": "draft",
    "source_type": "tolf_judgment",
    "source_id": "j-20260504-001",
    "created_at": "2026-05-04T10:00:00Z",
    "evidence_refs": [...]
  },
  "body": "..."
}
```

**映射逻辑**：
1. TOLF judgment_id → Wiki source_id
2. TOLF summary → Wiki body
3. TOLF evidence → Wiki evidence_refs
4. TOLF confidence → Wiki frontmatter metadata

**实现文件**：`literature_assistant/core/wiki/tolf_adapter.py`

---

### 2.2 TOLF Review Packet → Wiki Review Queue

**TOLF 输出格式**（推测，需验证）：
```json
{
  "review_id": "r-20260504-001",
  "judgment_id": "j-20260504-001",
  "review_type": "quality_check",
  "issues": [...],
  "status": "pending",
  "created_at": "2026-05-04T10:00:00Z"
}
```

**Wiki Review Queue 输入格式**：
```json
{
  "review_item_id": "r-20260504-001",
  "page_path": "synthesis/j-20260504-001.md",
  "review_type": "tolf_quality_check",
  "issues": [...],
  "status": "pending",
  "created_at": "2026-05-04T10:00:00Z"
}
```

**映射逻辑**：
1. TOLF review_id → Wiki review_item_id
2. TOLF judgment_id → Wiki page_path（通过 source_id 查找）
3. TOLF issues → Wiki issues
4. TOLF status → Wiki status

**实现文件**：`literature_assistant/core/wiki/tolf_adapter.py`

---

### 2.3 TOLF Inspection Packet → Wiki Doctor Report

**TOLF 输出格式**（推测，需验证）：
```json
{
  "inspection_id": "i-20260504-001",
  "inspection_type": "citation_check",
  "findings": [...],
  "severity": "warning",
  "created_at": "2026-05-04T10:00:00Z"
}
```

**Wiki Doctor Report 输入格式**：
```json
{
  "check_type": "tolf_citation_check",
  "findings": [...],
  "severity": "warning",
  "created_at": "2026-05-04T10:00:00Z"
}
```

**映射逻辑**：
1. TOLF inspection_type → Wiki check_type
2. TOLF findings → Wiki findings
3. TOLF severity → Wiki severity

**实现文件**：`literature_assistant/core/wiki/tolf_adapter.py`

---

## 3. 数据流设计

### 3.1 Phase 1：并行模式

```
User Query
    ↓
    ├─→ RAG Pipeline → RAG Result
    │
    └─→ TOLF Pipeline → TOLF Judgment
```

**特点**：
- 两条链路独立运行
- 用户可选择使用哪条链路
- 无数据交换

---

### 3.2 Phase 2：集成模式

```
User Query
    ↓
TOLF Pipeline
    ↓
TOLF Judgment
    ↓
TOLF Adapter
    ↓
Wiki Page Store
    ↓
Wiki Query Pipeline
    ↓
Wiki Result
```

**特点**：
- TOLF 输出进入 Wiki
- Wiki 可查询 TOLF 生成的内容
- TOLF 和 RAG 结果可对比

---

### 3.3 Phase 3：替换模式

```
User Query
    ↓
TOLF Pipeline (主链)
    ↓
TOLF Judgment
    ↓
TOLF Adapter
    ↓
Wiki Page Store
    ↓
Wiki Query Pipeline
    ↓
Wiki Result

(RAG Pipeline 作为 fallback)
```

**特点**：
- TOLF 成为默认主链
- RAG 作为 fallback
- 保留 RAG 兼容层

---

## 4. 实现计划

### 4.1 Phase 1（当前）

**任务**：
- [x] TOLF 独立运行
- [x] RAG 独立运行
- [x] 补充 TOLF 设计文档（本文档）

**验收**：
- TOLF 和 RAG 可独立运行
- 无数据交换
- 无冲突

---

### 4.2 Phase 2（Wave 15）

**任务**：
- [ ] 实现 `tolf_adapter.py`
- [ ] 实现 TOLF judgment → Wiki synthesis 映射
- [ ] 实现 TOLF review → Wiki review queue 映射
- [ ] 实现 TOLF inspection → Wiki doctor 映射
- [ ] 添加 TOLF-Wiki 集成测试
- [ ] 添加 TOLF-Wiki 集成文档

**验收**：
- TOLF 输出可进入 Wiki
- Wiki 可查询 TOLF 生成的内容
- TOLF 和 RAG 结果可对比
- 集成测试通过

---

### 4.3 Phase 3（未来）

**任务**：
- [ ] 设计主链切换策略
- [ ] 实现主链切换开关
- [ ] 实现 RAG fallback 逻辑
- [ ] 添加 TOLF vs RAG 评测对照
- [ ] 添加回滚点和兼容层

**验收**：
- TOLF 可作为默认主链
- RAG 可作为 fallback
- 主链切换无数据丢失
- 评测对照完整
- 回滚点可用

---

## 5. 风险与缓解

### 5.1 数据格式不兼容

**风险**：TOLF 输出格式与 Wiki 输入格式不兼容

**缓解**：
- 先验证 TOLF 输出格式（读取实际输出）
- 设计灵活的 adapter 层
- 添加格式验证和错误处理

---

### 5.2 功能重叠

**风险**：TOLF 和 Wiki 功能重叠，导致重复实现

**缓解**：
- 明确 TOLF 和 Wiki 的边界
- TOLF 负责生成，Wiki 负责存储和查询
- 避免在 Wiki 中重复实现 TOLF 功能

---

### 5.3 性能问题

**风险**：TOLF → Wiki 转换影响性能

**缓解**：
- 异步转换
- 批量转换
- 缓存转换结果

---

### 5.4 测试覆盖不足

**风险**：TOLF-Wiki 集成测试覆盖不足

**缓解**：
- 添加 focused 集成测试
- 添加端到端测试
- 添加性能测试

---

## 6. 下一步行动

1. **验证 TOLF 输出格式**：读取实际 TOLF 输出，确认格式
2. **设计 adapter 接口**：定义 `tolf_adapter.py` 的接口
3. **实现最小 adapter**：实现 judgment → synthesis 映射
4. **添加集成测试**：验证 adapter 正确性
5. **更新主计划**：将 TOLF 集成纳入 Wave 15

---

## 7. 参考资料

- TOLF 实现：`layers/tolf_engine.py`
- TOLF 测试：`test_tolf_engine.py`
- Wiki 数据模型：`literature_assistant/core/wiki/models.py`
- Wiki page store：`literature_assistant/core/wiki/page_store.py`
- Wiki review queue：`literature_assistant/core/wiki/review_queue.py`
- Wiki doctor：`literature_assistant/core/wiki/doctor.py`
