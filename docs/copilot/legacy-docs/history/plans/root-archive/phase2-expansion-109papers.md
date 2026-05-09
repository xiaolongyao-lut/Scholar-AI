# 🎯 第2步执行指南：扩展到109篇论文（2026-04-17）

## 快速概览
- **目标**：从216篇中取109篇，处理提取并评测
- **预期时间**：30-60分钟
- **预期结果**：109篇知识库 + 新的基线评测结果

## ✅ 已完成
1. 论文选择：216篇激光焊接论文（预期109+）
   - 文件：`output/zotero_109papers_selection.json`
   - 关键词：laser, welding, melt pool等
2. 批处理脚本已创建：
   - 论文选择拓展：`select_109papers_for_testing.py` ✅
   - Pipeline提取：`batch_process_109papers.py` ✅
   - Batch入库：`batch_ingest_109papers.py` ⏳
   - 基线评测：`baseline_evaluation_109papers.py` ⏳

## 📋 下一步命令序列

### 步骤1：等待Pipeline处理完成
```bash
python batch_process_109papers.py
```
**预期输出**：
- 创建 `output/batch_test_109papers/` 目录
- 每篇论文生成提取文件（01_full_extract.json等）
- 保存结果到 `output/batch_process_109papers_results.json`

### 步骤2：批量入库到chunk_store
```bash
python batch_ingest_109papers.py
```
**预期输出**：
- 创建项目：`laser_welding_109`
- doc_store：`output/doc_store/laser_welding_109.json` (109材料)
- chunk_store：`output/chunk_store/laser_welding_109_chunks.json` (~4000分块)

### 步骤3：评测基线
```bash
python baseline_evaluation_109papers.py
```
**预期输出**：
- 结果文件：`output/laser_welding_109_baseline_evaluation.json`
- 对比指标：Recall@1/5/10, MRR

## 📊 30篇vs109篇对比基准

| 指标 | 30篇论文 | 109篇预期 | 改进目标 |
|------|---------|---------|---------|
| Recall@1 | 0.0386 | 0.05-0.08 | +30% |
| Recall@5 | 0.1931 | 0.25-0.35 | +50% |
| Recall@10 | 0.3753 | 0.45-0.55 | +50% |
| MRR | 1.0000 | 0.95-1.0 | 保持 |
| 综合评分 | 0.3446 | 0.40-0.50 | +30% |

## 关键文件位置
- Zotero源：D:/zotero/zoterodate/storage (287 PDFs)
- 选择列表：`output/zotero_109papers_selection.json` (216条)
- Pipeline输出：`output/batch_test_109papers/`
- 知识库：
  - 30篇：`output/doc_store/laser_welding_30.json`
  - 109篇：`output/doc_store/laser_welding_109.json` (即将生成)

## 优化建议（第3步准备）

基于第2步结果，如果Recall仍然偏低(<0.3@5)，则第3步优化方向：
1. **升级嵌入模型** - 使用领域特定embedding
2. **加入reranker** - 提高排序精度
3. **Query expansion** - 扩展查询词汇
4. **分块优化** - 调整分块大小/重叠

## 🎯 成功标准
- Recall@5 > 0.25（相比30篇提升25%+）
- 综合评分 > 0.40（相比30篇提升20%+）
- 109篇知识库成功入库且可查询
