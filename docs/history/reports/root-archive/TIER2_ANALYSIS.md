# Tier 2 性能分析报告

## 关键发现：门槛缺口问题

### 离线估算结果
```
Tier 1 基线：        Recall@5=0.1304, MRR=0.0953
Phase 4 (Reranker):  Recall@5=0.1964 (-33% gap to 0.28)
Phase 5 (Expansion): Recall@5=0.3274 (-27% gap to 0.40) ❌
Phase 6 (Context):   Recall@5=0.3519 (-22% gap to 0.45) ❌
```

### 核心问题
**即使 Tier 2 全部 Phase 激活，Recall@5 仍差 0.1 以上，无法达到 0.45 的项目门槛。**

这说明：
1. **估算的提升比例（基于历史数据）可能过度保守**
   - Phase 4: +50.6% 基于 2-3 个月前的 A/B 测试，可能不适用当前查询分布
   - Phase 5: +66.7% 基于 30 个样本，样本量太小
   - Phase 6: +7.5% 是保守估计（原数据无正信号）

2. **或者需要 Tier 3 的能力**
   - Tier 2 的设计目标可能只是 Recall@5≥0.35
   - Hard 难度查询需要多轮交互、显式反馈、或强化学习

---

## 立即行动方案

### 选项 A：验证估算（推荐）
```bash
# 配置最少的 API 环境：只需 SILICONFLOW_API_KEY
export SILICONFLOW_API_KEY="your-key"

# 运行实测验证
python eval_retrieval_runtime.py --queries eval_queries_v1.0.jsonl

# 对比实测 vs 离线估算
# 如果实测 > 估算 → Tier 2 可能更强
# 如果实测 ≈ 估算 → 需要 Tier 3
```

### 选项 B：深度调优（Tier 2.5）
如果不想依赖外部 API，可以改进 Tier 1 架构：

1. **关键词图权重调优**
   - 当前：统一权重
   - 改进：基于 TF-IDF 的权重分配
   - 预期收益：+5~10%

2. **BM25 参数调优**
   - 当前：默认 k1=1.5, b=0.75
   - 改进：针对中文文档优化（k1=2.0, b=0.6）
   - 预期收益：+3~8%

3. **稠密向量模型升级**
   - 当前：BGE-m3
   - 改进：换用 BGE-M3-Unified 或 NoMic-Embed
   - 预期收益：+2~5%

4. **RRF 融合权重调优**
   - 当前：均等权重 (1/3 each)
   - 改进：基于每个方法的稳定性加权
   - 预期收益：+2~4%

### 选项 C：多轮检索（Tier 2.75）
- 第一轮：用改进的 Tier 1 + Query Expansion
- 第二轮：基于用户意图识别，二次查询
- 预期收益：+15~25%

---

## 关键数据点

| Phase | 基线 | 提升 | 理论值 | 现实值 | 备注 |
|-------|------|------|-------|--------|------|
| Tier 1 | - | - | 0.1304 | ? | 当前基线 |
| Phase 4 | 0.1304 | +50.6% | 0.1964 | TBD | 需验证 |
| Phase 5 | 0.1964 | +66.7% | 0.3274 | TBD | 30 样本，可能过度 |
| Phase 6 | 0.3274 | +7.5% | 0.3519 | TBD | 保守估计 |
| 目标 | - | - | 0.45 | - | 项目门槛 |

---

## 建议决策树

```
Do we have SILICONFLOW_API_KEY?
├─ YES → Go Option A: Verify with real API
│        ├─ If actual > offline est → Continue Tier 2
│        └─ If actual ≈ offline est → Go Option C: Multi-turn
│
└─ NO → Go Option B: Deep-tune Tier 1
        ├─ Target: Recall@5 from 0.13 → 0.25+
        ├─ If reaches 0.25+ → Option C multi-turn on top
        └─ If plateaus < 0.20 → Accept Tier 1 limit, document
```

---

## 下一步关键问题

1. **API 密钥配置**：是否有 SILICONFLOW_API_KEY？
2. **时间预算**：是否有时间做 Option B 的参数调优？
3. **硬约束**：项目是否一定要 Recall@5≥0.45，还是 0.35 可接受？

