# 后端优化规划确认

**确认时间**: 2026-04-11  
**范围**: Modular-Pipeline-Script (本地单用户后端优化)  

---

## ✅ 架构确认

### 项目结构概览

```
Modular-Pipeline-Script/
│
├─ main (当前分支) ✅
│  ├─ layers/              ← P1-P3核心逻辑 (后端)
│  ├─ 00-12脚本            ← 主要脚本 (后端)
│  ├─ config/              ← 配置文件 (后端)
│  └─ tools/               ← 工具集 (后端)
│
└─ amd (平行分支)          ⚠️ 暂不修改
   ├─ frontend/            ← Electron应用 (前端)
   ├─ backend_adapter/     ← IPC服务层 (后端)
   └─ electron/            ← TypeScript/React (前端)
```

---

## 📌 当前优化范围 (后端)

### 你现在规划的是 `main` 分支的优化

#### Phase 1: 鲁棒性硬化 (本周内)
- **模块**: layers/ai_adapter.py + 新建 layers/robust_parser.py
- **影响**: JSON解析容错，防止pipeline崩溃
- **文档**: [TECHNICAL_SPEC_ROBUSTNESS.md](TECHNICAL_SPEC_ROBUSTNESS.md)

#### Phase 2: 缓存系统 (本周末)
- **模块**: 新建 layers/claim_cache.py + 修改 layers/p2_claim_extractor.py
- **影响**: 本地重复处理加速10-12倍
- **文档**: [TECHNICAL_SPEC_CACHE.md](TECHNICAL_SPEC_CACHE.md)

#### Phase 3: 本地工具链 (下周)
- **工具**: tools/preview_analysis.py, tools/compare_analyses.py
- **影响**: 快速查看和对比分析结果
- **文档**: [LOCAL_SINGLE_USER_OPTIMIZATION_PLAN.md](LOCAL_SINGLE_USER_OPTIMIZATION_PLAN.md)

---

## 🚫 前端暂不动

### amd 分支状态

**当前状态**: Electron 桌面应用平行开发中

**为什么暂不修改**:
```
原因1: 后端还在优化阶段
  - 鲁棒性需要验证
  - 缓存系统需要稳定测试
  - API接口可能还会变化

原因2: 解耦合考虑
  - 前后端应该通过约定好的接口通信
  - 后端优化 ≠ 前端改动
  - 等后端稳定后，前端通过IPC调用即可

原因3: 专注当前目标
  - 本地单用户，优先稳定核心处理能力
  - 前端UI可以随时对接后端的新功能
```

**前端集成计划** (预期):
```
Week 3+ (稳定后):
  □ 后端暴露新的API接口
  □ 前端通过IPC调用缓存查询
  □ 前端支持"一键清理缓存"
  □ 前端显示处理性能指标
```

---

## 📊 三阶段规划时间线

```
┌─────────────────────────────────────────────────────────────┐
│                  后端优化时间线 (单用户)                      │
└─────────────────────────────────────────────────────────────┘

Week 1 (本周4月11-17)
├─ Day 1-2: 鲁棒JSON解析 (RobustParser)
│  └─ 文件: TECHNICAL_SPEC_ROBUSTNESS.md ✅
│
├─ Day 3-4: 缓存系统核心 (ClaimCache)
│  └─ 文件: TECHNICAL_SPEC_CACHE.md ✅
│
└─ Day 5: 集成验证
   └─ 文件: GEMINI_IMPLEMENTATION_PROMPTS.md ✅

成果: 后端稳定性 + 性能 ⬆️13倍


Week 2 (4月18-24)
├─ Day 1: 本地配置管理
│  └─ config/local_settings.ini
│
├─ Day 2-3: 预览与对比工具
│  ├─ tools/preview_analysis.py
│  └─ tools/compare_analyses.py
│
└─ Day 4-5: 可视化自动导出
   └─ 改进 layers/p3_exporter.py

成果: 本地工作流完整


Week 3+ (4月25+)
├─ 后端稳定性测试与优化
├─ 前端集成IPC接口
└─ 联合测试
```

---

## 🎯 交付清单

### 已完成的文档 (今天)

- [x] **TECHNICAL_SPEC_ROBUSTNESS.md**
  - RobustJSONParser完整技术规范
  - 200-250行代码设计
  - 单元测试框架
  - 集成指导

- [x] **TECHNICAL_SPEC_CACHE.md**
  - ClaimCache完整技术规范
  - SQLite schema设计
  - 250-300行代码设计
  - 性能基准指标

- [x] **GEMINI_IMPLEMENTATION_PROMPTS.md**
  - 4份可直接复制给Gemini的提示词
  - 每个模块的实现指导
  - 测试用例框架
  - 执行顺序建议

- [x] **LOCAL_SINGLE_USER_OPTIMIZATION_PLAN.md**
  - 本地单用户优化总体规划
  - 优先级排序 (相比Gemini建议的调整)
  - 工具链设计
  - Phase 1-4 详细计划

---

## 🔄 下一步行动

### 立即行动 (今天/明天)

**选项A**: 使用Gemini实现
```bash
1. 打开 GEMINI_IMPLEMENTATION_PROMPTS.md
2. 复制"提示词 #1: RobustJSONParser实现"
3. 粘贴到Gemini代码生成
4. 获得完整的layers/robust_parser.py

预期: 1-2小时内获得可运行的代码
```

**选项B**: 手工实现
```bash
1. 参考 TECHNICAL_SPEC_ROBUSTNESS.md
2. 自己编写 layers/robust_parser.py
3. 参考测试框架写单元测试

预期: 4-6小时
```

**推荐**: 选项A (Gemini), 节省时间，质量有保障

---

## 📋 验证清单

完成后的验证清单:

### Phase 1 完成标准 (Week 1)
```
RobustJSONParser:
  □ 所有单元测试通过 (>95% coverage)
  □ 修复所有7种常见JSON格式问题
  □ 集成到 AIAdapter，正常工作
  □ 性能 <10ms (需要修复的情况)

ClaimCache:
  □ SQLite表创建正确
  □ 缓存查询和保存工作正常
  □ 集成到 ClaimExtractor
  □ 缓存命中率 >90% (重复处理场景)
```

### 性能验证
```
□ 相同论文处理提速 10-12倍
□ 缓存大小 <500KB/论文 (合理)
□ 缓存命中率统计正常输出
□ 无性能回退 (首次处理不变或更快)
```

### 向后兼容性
```
□ disable_cache=True 时系统正常工作
□ 现有脚本无需修改即可运行
□ 所有现有单元测试仍通过
```

---

## 💬 FAQ

### Q: 前端什么时候能用到这些优化?

A: 
```
后端优化是内部改进，前端不需要立即改动。
预计 Week 3+ 前端可以:
  - 通过IPC调用新的缓存接口
  - 显示缓存统计信息
  - 提供"清理缓存"按钮
```

### Q: 这些改动会影响amd分支吗?

A:
```
不会。amd分支通过IPC通信调用main分支的服务。
只要后端API接口保持稳定，前端无需改动。
```

### Q: 如果后端有bug怎么办?

A:
```
每个模块都有完整的单元测试和集成测试。
出现bug时:
  1. 修改后端代码
  2. 重新运行测试
  3. 前端无需改动 (通过IPC自动获取最新版本)
```

### Q: 能否跳过某个Phase?

A:
```
不推荐。建议按顺序:
  ✅ Phase 1 (鲁棒性) - 必做 (生产稳定性)
  ✅ Phase 2 (缓存) - 必做 (本地常见需求)
  🔄 Phase 3 (工具) - 可选 (提升体验)
  ⚪ Phase 4 (架构) - 可选 (后续考虑)
```

---

## 📞 联系方式

- **技术规范**: 查看 TECHNICAL_SPEC_*.md 文件
- **Gemini提示词**: 查看 GEMINI_IMPLEMENTATION_PROMPTS.md
- **进度跟踪**: LOCAL_SINGLE_USER_OPTIMIZATION_PLAN.md

---

## 🎯 最终目标

本地单用户能快速、稳定地：

1. ✅ 处理论文而不担心JSON解析崩溃 (鲁棒性)
2. ✅ 重复处理不浪费时间和Token (缓存)
3. ✅ 快速查看和对比分析结果 (工具)
4. ✅ 通过配置灵活调整处理参数 (配置管理)

**开始时间**: 建议今天/明天启动Phase 1

你准备好了吗? 😊
