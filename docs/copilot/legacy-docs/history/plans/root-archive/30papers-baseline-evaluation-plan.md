# 30篇论文评测基线执行计划

## 任务进度 (2026-04-17)

### ✅ 已完成
1. **论文选择** - 从287篇中选出30篇激光焊接/熔池相关论文
2. **批量入库** - 30/30 成功，1,246个分块生成
3. **关键词测试** - keyhole 关键词成功匹配3篇

### ⏳ 进行中
**第1步：运行评测基线**
- 脚本：`baseline_evaluation_30papers.py`
- 位置：`c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\`
- 命令：`python baseline_evaluation_30papers.py`

### 📊 评测设置
- 8个查询（激光焊接领域相关）
- 指标：Recall@1/5/10, MRR, 综合评分
- 输出：`laser_welding_30_baseline_evaluation.json`

### 🎯 三步计划确定顺序
1. **评测基线**（当前） - 了解30篇知识库性能
2. **扩展109篇** - 验证可扩展性，重新评测
3. **优化参数** - 基于评测结果改进检索

### 📁 关键文件位置
- 知识库：`output/doc_store/laser_welding_30.json`
- 分块索引：`output/chunk_store/laser_welding_30_chunks.json`
- 论文选择：`output/zotero_30papers_selection.json`
- 入库结果：`output/laser_welding_30_ingest_results.json`
- Pipeline输出：`output/batch_test_30papers/`

### 💡 预期结果
- Recall@5 预期：0.3-0.5（初步系统）
- MRR 预期：0.2-0.4
- 基于结果决定优化方向

### 下一步命令
```bash
python baseline_evaluation_30papers.py
```
