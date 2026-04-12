# 功能优化快速参考表

## 📊 一览表

| # | 优化方向 | 优先级 | 预期收益 | 时间 | 复杂度 | ROI |
|---|--------|-------|--------|--------|--------|-----|
| P0 | 混合检索权重自适应 | ⭐⭐⭐⭐⭐ | +20% 精度 | 5-7天 | 中 | 极高 |
| P1 | 流水线并行化 | ⭐⭐⭐⭐ | -30% 耗时 | 10-14天 | 中-高 | 极高 |
| P2 | 知识图谱+冲突修复 | ⭐⭐⭐⭐ | +40% 一致性 | 14-21天 | 高 | 高 |
| P3 | 批处理自适应分配 | ⭐⭐⭐ | 支持100+ | 7-10天 | 中 | 高 |
| P4 | 缓存双层加速 | ⭐⭐⭐ | 20倍查询速度 | 7-10天 | 中 | 中-高 |

---

## 🎯 并行执行方案

**Month 1**
```
Week 1-2: P0 + Performance Baseline
Week 3-4: P1 Infrastructure + P2 Design
```

**Month 2**
```
Week 1-2: P2 Implementation + P3 Start
Week 3-4: P3 Continue + P4 Prep
```

**Month 3**
```
Week 1-2: P4 Implementation
Week 3-4: Integration + Full Testing + Performance Verification
```

**预期结果**: 78% → 89% 功能完整度，单文处理 45s → 31s

---

## 💡 各优化的关键要点

### P0: 检索权重自适应
**问题**: BM25/Vector/Context权重硬编码，无法适配不同领域  
**解决**: 利用`p1_fusion_weight_calibrator`缓存最优权重，首次校准后复用  
**关键文件**: `r_layer_hybrid_retriever.py`, `p1_fusion_weight_calibrator.py`  
**预期**: Recall ↑18%, 检索精度 ↑20%

### P1: 流水线并行化
**问题**: 7层串行处理，总耗时45s/文  
**解决**: A(关注点)与R(检索)并行，三级流水架构  
**关键文件**: `integrated_pipeline.py`, 核心层async优化  
**预期**: 耗时 45s → 31s (-33%)

### P2: 知识图谱+冲突修复
**问题**: 检测到冲突但无法自动修复，知识分散  
**解决**: 参数级KG构建，相似冲突聚类投票，M层驱动快速决议  
**关键文件**: `w_layer_cross_paper_analysis.py`, `m_layer_mempalace_memory.py`  
**预期**: 冲突自动修复率 0% → 65%, 共识生成 10s → 1s

### P3: 批处理自适应
**问题**: batch_size=13固定，不支持>50篇，单worker  
**解决**: 根据PDF大小/内存自动计算batch_size和worker数，增量保存  
**关键文件**: `batch_controller.py`
**预期**: 支持100+篇，内存占用 -15%

### P4: 缓存双层加速
**问题**: 仅缓存Claims，重复查询仍需5s，M层未自动利用  
**解决**: L1进程缓存 + L2检索结果缓存 + L3 MemPalace记忆层  
**关键文件**: `claim_cache.py`, `r_layer_hybrid_retriever.py`, `m_layer_mempalace_memory.py`  
**预期**: 热点查询20x加速，缓存命中率+45%

---

## 🚀 立即行动（本周）

### Step 1: 性能基准（2h）
```bash
# 建立测试套件
python tests/test_performance_benchmark.py
# 记录各层耗时：E提取(8s), A关注(10s), R检索(12s), K索引(5s), G评分(7s), P生成(3s)
# 总计：45s
```

### Step 2: 分析可行性（3h）
```python
# 评估P0可行性
from layers.p1_fusion_weight_calibrator import FusionWeightCalibrator
calibrator = FusionWeightCalibrator()
# 检查是否已实现grid search，是否支持缓存
# → 如果✅，则P0可立即启动

# 评估P1可行性  
# 绘制依赖图：E → A → R → K → G → P
# 找出可因行的：A || R (同步执行)
```

### Step 3: 制定P0技术设计（4h）
```
设计文档：
  1. Adaptive Weight Manager架构图
  2. Domain标签生成规则（从A层focus）
  3. 缓存键设计
  4. grid_search → 缓存的工作流
  5. 降级方案（缓存未hit时的fallback）
```

### Step 4: 建立测试框架（4h）
```
测试用例：
  - 创建10篇测试论文集
  - 测试P0前后的检索精度对比（P@5, Recall@20）
  - 验证权重缓存有效性
  - 性能对比（缓存命中时的开销）
```

---

## 📋 资源预算

### 人力
- **Week 1-2 (P0)**: 1人全职 (5-7天)
- **Week 3-4 (P1)**: 1-2人 (10-14天)
- **Month 2 (P2+P3)**: 2人并行 (4-5周)
- **Month 3 (P4+测试)**: 1-2人 (2-3周)

**总计**: 40-50个人天

### 资源依赖
- ✅ Python 3.9+环境 (已有)
- ✅ SQLite (已有)
- ⚠️ 向量数据库 (P2/P4可选)
- ⚠️ 多进程支持 (P3必需)
- ⚠️ MemPalace外部存储 (P2+可选，目前内存)

---

## ⚠️ 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|-----|-----|-----|--------|
| P0性能基准数据不一致 | 中 | 中 | 建立稳定的测试环境，多次运行取平均 |
| P1并行化引入race condition | 中 | 高 | 完整的单元测试，使用asyncio.Lock | 
| P2复杂度超出预期 | 中-高 | 高 | 分阶段实现，先做聚类部分，再做KG |
| P3多worker导致OOM | 低 | 中 | 内存监控，动态调整batch_size |
| P4缓存键碰撞 | 低 | 低 | 使用MD5 hash，添加版本号 |

---

## 📞 决策点

**在启动P2之前需要决策**:
1. 知识图谱用什么存储？(SQLite/Neo4j/内存?)
2. 相似度计算用embedding还是传统算法？
3. MemPalace如何与其他层交互？

**建议**:
- 初阶：SQLite + 传统相似度 + 后期考虑embedding
- 中阶：Neo4j + 向量相似度
- 高阶：图数据库 + 完整的知识抽取管道

---

## 📑 详细方案文档

完整的技术规格请查看同目录的 **FUNCTIONAL_OPTIMIZATION_ROADMAP.md**

---

**状态**: 📋 Ready to implement  
**下一步**: 审核本表格 → 批准P0 → 启动实施
