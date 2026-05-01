# 给Gemini的实现提示词

**说明**: 以下是可以直接复制给Gemini代码生成工具的提示词。选择其中一个使用。

---

## 提示词 #1: RobustJSONParser 实现

```
你是一个Python高级开发者。我需要你实现一个鲁棒的JSON解析器模块。

项目背景:
- 这是一个学术文献处理系统，使用LLM生成结构化数据
- LLM输出经常包含格式问题（markdown包裹、尾部逗号、截断等）
- 需要一个鲁棒的解析器来处理这些问题

任务:
在 layers/robust_parser.py 中实现 RobustJSONParser 类，满足以下要求：

核心功能:
1. parse(text: str, fallback=None) -> Dict
   - 安全解析JSON，按优先级尝试多种修复策略
   - 直接解析 → 剥离markdown → 删除尾部逗号 → 修复引号 → 修复截断 → 返回fallback
   
2. parse_list(text: str, fallback=None) -> List[Dict]
   - 解析JSON数组的特殊版本

修复策略详情:
- 剥离markdown: 移除 ```json ... ``` 包裹
- 删除尾部逗号: 处理 {,} 和 [,]
- 修复引号: 单引号改双引号
- 修复截断: 若 { 比 } 多，补充缺失的 }

测试覆盖:
- test_direct_parse_valid_json: 正常JSON
- test_strip_markdown_single_line: markdown包裹
- test_fix_trailing_commas: 尾部逗号
- test_fix_unmatched_quotes: 单引号
- test_repair_truncated: 被截断的JSON
- test_parse_list: JSON数组
- test_fallback_on_failure: 完全失败时返回fallback

日志需求:
- DEBUG级别: 记录每个修复策略的尝试
- INFO级别: 成功解析时记录使用的策略
- WARNING级别: 所有策略都失败时记录

代码质量:
- 类型注释完整 (Python 3.10+)
- 至少80行的docstring文档
- 无外部依赖 (仅stdlib)
- 线程安全 (如果需要)

交付物:
1. layers/robust_parser.py (完整实现, 200-250行)
2. 包含单元测试的测试文件 (test_robust_parser.py, 120-150行)
3. 集成示例代码 (如何在ai_adapter.py中使用)

性能要求:
- 正常JSON: <1ms
- 需要修复的JSON: 2-10ms
- 失败情况: <1ms (快速fallback)
```

---

## 提示词 #2: ClaimCache 实现

```
你是一个Python高级开发者。我需要你实现一个SQLite-based的声明缓存系统。

项目背景:
- 学术文献处理系统需要缓存已提取的LLM结果
- 用户经常重复处理相同论文（改变goal或scoring_rules）
- 当前没有缓存导致70-90%的Token重复浪费
- 目标: 本地单用户场景，相同文献的二次处理提速10-12倍

任务:
在 layers/claim_cache.py 中实现 ClaimCache 类，满足以下要求：

核心功能:
1. 初始化与数据库设置
   - __init__(db_path=".cache/claims.db", auto_init=True)
   - 自动初始化SQLite表

2. 签名生成
   - get_chunk_signature(text: str, source_meta: dict) -> str
   - 基于文本内容+doc_id生成唯一签名 (SHA256)
   - 必须标准化文本 (removing extra spaces)
   - 必须稳定 (相同input总是生成相同output)

3. 缓存查询
   - get_claims(chunk_sig: str) -> Optional[List[Dict]]
   - 快速查询 (<5ms via SQLite index)
   - 自动更新 accessed_at 和 access_count

4. 缓存写入
   - save_claims(chunk_sig, claims, metadata=None)
   - 使用 INSERT OR IGNORE 处理冲突
   - 自动计算平均置信度

5. 缓存失效
   - invalidate_paper(doc_id: str): 删除整篇论文的所有缓存
   - clear_all(): 清空所有缓存
   - cleanup_old_entries(days=30): 删除N天未访问的条目

6. 统计功能
   - get_stats() -> Dict[str, int]: 返回缓存统计信息
   - log_stats(): 打印统计信息

数据库schema:
CREATE TABLE claims_cache (
    id INTEGER PRIMARY KEY,
    chunk_signature TEXT UNIQUE,
    doc_id TEXT,
    chunk_index INTEGER,
    claims_json TEXT,
    cached_at TIMESTAMP,
    accessed_at TIMESTAMP,
    access_count INTEGER,
    cache_version TEXT,
    llm_model TEXT,
    extraction_confidence REAL,
    INDEX idx_doc_id (doc_id),
    INDEX idx_cached_at (cached_at)
)

测试覆盖:
- test_signature_generation: 签名是否正确生成
- test_save_and_retrieve: 保存和查询功能
- test_cache_miss: 缓存未命中时返回None
- test_invalidate_paper: 论文失效功能
- test_stats: 统计功能
- test_signature_stability: 相同input生成相同signature
- test_signature_different_doc: 不同doc_id生成不同signature

集成需求:
- 需要与 layers/p2_claim_extractor.py 集成
- 修改 ClaimExtractor.__init__() 初始化缓存
- 修改 extract_from_chunk() 方法添加缓存查询和保存逻辑
- 参考流程: 生成签名 → 查询缓存 → 缓存命中返回 → 缓存未命中执行正常流程 → 保存到缓存

代码质量:
- 完整的类型注释
- 异常处理 (捕获SQLite错误)
- 日志记录 (DEBUG/INFO/ERROR级别)
- 无外部依赖 (仅标准库)
- 线程安全考虑

交付物:
1. layers/claim_cache.py (完整实现, 250-300行)
2. 测试文件 (test_claim_cache.py, 150-200行)
3. 集成修改指导 (modify_claim_extractor.md, 说明如何修改ClaimExtractor)

性能指标 (需要在代码中验证):
- 缓存命中: <5ms
- 缓存写入: <10ms
- 单chunk处理无缓存: 100-200ms
- 单chunk处理有缓存命中: 5-10ms
- 提速比: 15-20倍
```

---

## 提示词 #3: RobustJSONParser + ClaimCache 集成

```
你是一个Python高级开发者。这是一个两阶段的集成任务。

前置条件:
- 已有 layers/robust_parser.py (RobustJSONParser)
- 已有 layers/claim_cache.py (ClaimCache)
- 需要将它们集成到现有的处理流程中

阶段1: 修改 layers/ai_adapter.py
1. 导入 RobustJSONParser
2. 在 AIAdapter.__init__() 中初始化 self.parser = RobustJSONParser()
3. 修改 extract_claims() 方法:
   - 调用 LLM 后，使用 self.parser.parse() 代替 json.loads()
   - 添加日志记录解析结果
4. 添加异常处理，若JSON解析全部失败，返回 []

修改代码量: ~50行

阶段2: 修改 layers/p2_claim_extractor.py
1. 导入 ClaimCache
2. 在 ClaimExtractor.__init__() 中初始化:
   if enable_cache:
       self.cache = ClaimCache()
   else:
       self.cache = None
3. 修改 extract_from_chunk() 方法:
   
   async def extract_from_chunk(self, text: str, source: SourceMeta) -> List[Claim]:
       # 1. 检查缓存（若启用）
       if self.cache:
           chunk_sig = self.cache.get_chunk_signature(text, source.__dict__)
           cached_claims = self.cache.get_claims(chunk_sig)
           if cached_claims is not None:
               logger.info(f"✅ 缓存命中: {len(cached_claims)} claims")
               return [Claim(**c) for c in cached_claims]
       
       # 2. 执行正常流程 (regex → NER → LLM)
       rough_claims = self._regex_pre_extract(text, source)
       ner_claims = self._ner_enhance_claims(text, source, rough_claims)
       
       if self.llm_client:
           low_confidence = [c for c in ner_claims if c.confidence < 0.80]
           if low_confidence:
               refined = await self._llm_refine_edge_cases(...)
               final_claims = [c for c in ner_claims if c.confidence >= 0.80] + refined
           else:
               final_claims = ner_claims
       else:
           final_claims = ner_claims
       
       # 3. 保存到缓存
       if self.cache:
           self.cache.save_claims(
               chunk_sig,
               [c.__dict__ for c in final_claims],
               metadata={"doc_id": source.doc_id, "llm_model": "gpt-4o-mini"}
           )
       
       return final_claims

修改代码量: ~80行

集成测试:
- 创建 tests/test_integration_robust_cache.py
- 测试完整的流程: 第一次调用 → 第二次调用（应使用缓存）
- 验证性能提升 (时间对比)

交付物:
1. 修改后的 layers/ai_adapter.py
2. 修改后的 layers/p2_claim_extractor.py
3. 集成测试文件 (test_integration_robust_cache.py)
4. 集成指南文档 (INTEGRATION_GUIDE.md)

验收标准:
- 所有单元测试通过
- 集成测试通过
- 不破坏现有功能 (向后兼容)
- 日志清晰记录缓存命中情况
```

---

## 提示词 #4: 性能基准测试脚本

```
你是一个Python高级开发者。我需要一个性能基准测试脚本。

需求:
在 benchmarks/benchmark_robust_cache.py 中创建性能测试脚本，用于验证RobustJSONParser和ClaimCache的性能提升。

测试场景:

1. JSON解析性能 (test_json_parsing_performance)
   - 测试数据集: 10个不同格式的JSON (正常、markdown包裹、尾部逗号、截断等)
   - 测试方式: 每种格式运行1000次
   - 输出: 平均解析时间, 最快/最慢时间, 成功率

2. 缓存系统性能 (test_cache_performance)
   - 场景A: 首次处理 (无缓存):
     - 处理100个不同的chunks
     - 测量总耗时
   
   - 场景B: 重复处理相同chunks:
     - 处理相同100个chunks
     - 测量缓存命中率
     - 测量总耗时
     - 计算提速比 (A耗时 / B耗时)

3. 端到端集成性能 (test_e2e_performance)
   - 模拟完整的论文处理流程
   - 第一次运行: 不使用缓存
   - 第二次运行: 使用缓存
   - 输出: 时间对比, 加速倍数

输出格式:
```
🔧 性能基准测试结果
─────────────────────────────────

📊 JSON解析性能
  正常JSON:          0.8ms
  markdown包裹JSON:  2.3ms (剥离markdown)
  尾部逗号JSON:      2.1ms (删除逗号)
  平均成功率: 98.5%

⚡ 缓存系统性能
  无缓存处理:        2450ms
  有缓存处理:        180ms
  提速比:            13.6倍
  缓存命中率:        95%

🏃 端到端性能
  首次处理:          4320ms
  二次处理:          250ms
  加速倍数:          17.3倍
```

代码要求:
- 使用 timeit 或 time.perf_counter() 精确计时
- 记录详细的日志输出
- 生成可选的CSV报告
- 支持命令行参数控制测试参数

启动方式:
python benchmarks/benchmark_robust_cache.py [--iterations 1000] [--output report.csv]
```

---

## 使用指南

1. **选择提示词**: 根据需要实现的模块选择相应的提示词
2. **复制完整内容**: 将提示词的完整文本(包括任务和要求)复制到Gemini
3. **粘贴到Gemini**: 使用Gemini代码生成功能
4. **验证质量**: 获得代码后:
   - 检查类型注释和文档
   - 运行单元测试
   - 进行代码审查

---

## 顺序建议

**推荐执行顺序**:

1. **第一步** → 提示词 #1 (RobustJSONParser)
   - 耗时: 1天
   - 难度: 中等
   
2. **第二步** → 提示词 #2 (ClaimCache)
   - 耗时: 2天
   - 难度: 中等
   
3. **第三步** → 提示词 #3 (集成修改)
   - 耗时: 1天
   - 难度: 低
   
4. **第四步** (可选) → 提示词 #4 (性能基准)
   - 耗时: 1天
   - 难度: 低

**总耗时**: 5-7天

---

## 注意事项

1. **保留原始实现**: 在修改现有文件前，先备份
2. **增量集成**: 每个模块完成后，先本地测试再集成
3. **文档更新**: 完成后更新README和API文档
4. **性能验证**: 使用提示词#4的基准测试验证提速效果
5. **Git提交**: 按模块提交，便于回滚

---

## 特殊说明

**针对本地单用户场景的优化**:
- ClaimCache使用SQLite (无服务器依赖)
- 缓存默认启用，但可通过 `enable_cache=False` 禁用
- 支持手动清理缓存 (`.cache/claims.db`)
- 所有缓存操作都是本地操作 (<10ms)

**集成兼容性**:
- RobustJSONParser: 无需修改现有代码，即插即用
- ClaimCache: 与现有ClaimExtractor完全兼容，可选启用
- 所有修改都是向后兼容的
