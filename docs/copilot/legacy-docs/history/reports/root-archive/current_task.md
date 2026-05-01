# 当前会话任务状态

## 已完成的修改（本次会话）

### E-Layer (`layers/e_layer_multimodal.py`)
- 添加了章节检测：`SECTION_HEADER_RE`, `NUMBERED_SECTION_RE`, `_is_noise_block()`, `_detect_section_header()`
- `full_extract()` 现在：
  - 计算全文平均字体大小（body_font）
  - 检测章节标题并跳过（不生成 chunk），用 `current_section` 追踪当前章节
  - 过滤噪声块（期刊元数据、URL、版权声明等）
  - 最小长度从 10 提升到 40 字符
  - 每个 chunk 的 `section_title` 现在是真实章节名而非 "Page Content"

### G-Layer (`layers/g_layer_academic_generator.py`)
- 添加了 `_GLAYER_NOISE_SKIP_RE` 正则
- 在 `analyze_bound_data()` 循环中加了噪声预过滤（在 len<40 过滤之后）

### resources_router.py
- `MAX_CHUNKS_PER_MATERIAL` 从 2 改为 5（RAG 每篇文献最多返回 5 个片段）

## 功能缺失（用户询问但未实现）
1. **撒饵捕鱼算法** — 代码库中完全不存在，从未实现
2. **一句话灵感** — 后端有 `inspiration_engine.py` 文件（InspirationEngine, InspirationSpark 类），但：
   - 没有 API 路由（routers/ 中无 inspiration 路由）
   - 没有前端页面（frontend/src/pages/ 中无对应页面）
   - inspiration_engine.py 是孤立文件，未接入任何 router

## 已完成验证
- E-Layer 噪声过滤、章节检测：导入测试通过
- G-Layer 噪声预过滤：导入测试通过
- 前端构建：Exit 0 (2.69s)
- git commit: 08212d5 (HEAD -> main) feat(pipeline): 提升切片质量 + RAG召回深度

## 用户要求的未实现功能（需在下次对话中实现）
1. **撒饵捕鱼算法** — 从未实现，代码库中不存在。需要用户确认具体需求。
2. **一句话灵感** — backend 有 inspiration_engine.py 但无 API 路由和前端页面。
   需要：
   - 在 routers/ 创建 inspiration_router.py
   - 在 python_adapter_server.py 中注册路由
   - 在 frontend/src/pages/ 创建对应页面或在 Workbench 添加入口
