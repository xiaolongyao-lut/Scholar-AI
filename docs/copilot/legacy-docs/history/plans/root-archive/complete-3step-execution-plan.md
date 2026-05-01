# 🚀 完整的3步执行计划（2026-04-17）

## 📊 进度总结

### ✅ 已完成
1. **第1步：评测基线（30篇）** - DONE ✓
   - 30/30论文成功入库
   - 基线评测完成
   - 结果：Recall@5=0.1931, 综合评分=0.3446 (一般)
   - 文件：`output/laser_welding_30_baseline_evaluation.json`

2. **第2步第1阶段：论文选择（109篇）** - DONE ✓
   - 从287篇中选出216篇激光焊接论文
   - 选择文件：`output/zotero_109papers_selection.json`
   - 取前109篇进行处理

### ⏳ 即将执行
3. **第2步第2阶段：Pipeline处理（109篇）** - READY
4. **第2步第3阶段：批量入库（109篇）** - READY
5. **第2步第4阶段：基线评测（109篇）** - READY
6. **第3步：参数优化** - PENDING

---

## 📋 可执行脚本清单

### 脚本1：选择论文（已执行）
```bash
python select_109papers_for_testing.py
```
- 输出：`output/zotero_109papers_selection.json` (216篇)
- 状态：✅ 完成

### 脚本2：Pipeline提取 (准备就绪)
```bash
python batch_process_109papers.py
```
- 作用：运行pipeline_core提取特征
- 输出：`output/batch_test_109papers/` + `output/batch_process_109papers_results.json`
- 预期时间：30-60分钟
- 状态：⏳ 准备执行

**代码位置**：`batch_process_109papers.py` (已创建)

### 脚本3：批量入库 (准备就绪)
```bash
python batch_ingest_109papers.py
```
- 作用：将提取内容写入doc_store和chunk_store
- 输入：`output/batch_test_109papers/**/*01_full_extract.json`
- 输出：
  - `output/doc_store/laser_welding_109.json` (109材料)
  - `output/chunk_store/laser_welding_109_chunks.json` (~4000分块)
  - `output/laser_welding_109_ingest_results.json`
- 状态：⏳ 准备执行

**代码位置**：`batch_ingest_109papers.py` (已创建，需修复导入)

### 脚本4：基线评测 (准备就绪)
```bash
python baseline_evaluation_109papers.py
```
- 作用：计算109篇知识库的Recall@K和MRR
- 输入：`output/chunk_store/laser_welding_109_chunks.json`
- 输出：`output/laser_welding_109_baseline_evaluation.json`
- 包含：8个查询, Recall@1/5/10, 对比30篇基线
- 状态：⏳ 准备执行

**代码位置**：`baseline_evaluation_109papers.py` (已创建)

---

## 🎯 执行指令序列

**推荐执行顺序**：

### 命令1（估时30-60分钟）
```
cd c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
python batch_process_109papers.py
```
等待完成后查看：`output/batch_process_109papers_results.json`

### 命令2（估时5-10分钟，需修复导入bug）
```
python batch_ingest_109papers.py
```
等待完成后查看：
- `output/laser_welding_109_ingest_results.json`
- `output/chunk_store/laser_welding_109_chunks.json`

### 命令3（估时2-5分钟）
```
python baseline_evaluation_109papers.py
```
结果文件：`output/laser_welding_109_baseline_evaluation.json`

---

## 📊 预期对比结果

| 指标 | 30篇 | 109篇预期 | 改进 |
|------|------|---------|------|
| Recall@1 | 0.0386 | 0.05-0.10 | +30% |
| Recall@5 | 0.1931 | 0.25-0.35 | +50% |
| Recall@10 | 0.3753 | 0.45-0.55 | +50% |
| 综合评分 | 0.3446 | 0.40-0.50 | +30% |

---

## 🔧 已知问题和修复

### 脚本需修复
1. `batch_ingest_109papers.py` - 导入错误
   - 修复：检查ResourcesRouter类名和方法调用
   - 参考：`batch_ingest_30papers.py` (已验证工作)

2. 所有脚本 - f-string emoji警告
   - 影响：无，仅是linting警告

### 快速修复方案
复制已验证工作的batch_ingest_30papers.py逻辑，修改项目ID为laser_welding_109

---

## 💾 关键数据点
- Zotero源路径：`D:/zotero/zoterodate/storage`
- 总论文数：287 PDFs
- 关键词匹配：216 papers
- 处理数：109 papers
- 预期chunk数：~4000个

---

## ✨ 第3步准备（参数优化）

基于第2步结果，如果Recall仍<0.35@5，启动优化：

### 优化选项
1. **reranker模型** - 提升排序精度
2. **query expansion** - 扩展查询词汇
3. **embedding模型升级** - 使用领域特定模型
4. **分块策略调整** - chunk_size从800→600，overlap调整

### 优化验证方式
- 在laser_welding_109上运行optimization_test.py
- 对比优化前后的Recall@5/MRR
- 如果改进>20%，应用到检索系统

---

## 🎓 总结
三步计划已做好准备，脚本齐全。第2步可立即执行，预计2-3小时内完成全流程。
