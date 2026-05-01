# Batch Pipeline Debug 状态

## 已确认问题
1. **April 13 批处理全部失败(0/13)** - 旧版代码不生成 `02_writing_material_pack.json`，当前版本已修复
2. **E-Layer 切片质量极差**: 
   - 所有 chunk 的 `section_title` 均为 `"Page Content"` （无 Abstract/Intro/Methods/Results/Conclusion 识别）
   - 无噪声过滤 (期刊头信息、页码、URL 都成了 chunk)
   - 最小长度过滤只有 10 字符，太低
3. **G-Layer scoring 不工作**: 所有写作点 `relevance_score: 0.2689` (固定值，LLM未介入)
   - `scoring_results` 里的 `writing_points` 包含垃圾内容如 "Contents lists available at ScienceDirect"

## 关键文件路径
- `layers/e_layer_multimodal.py` → `full_extract()` 函数，Line 163-200
- `layers/g_layer_academic_generator.py` → `AcademicScorer`
- `batch_controller.py` → `BatchProcessController`
- `routers/pipeline_router.py` → `/batch/submit` endpoint
- `routers/volume_router.py` → `/volumes` endpoint  
- `volume_analysis_service.py` → `_list_batch_output_roots()` 只扫描 `REPO_ROOT/batch_output*`

## 管线当前能成功运行
测试命令: `python pipeline_core.py "...pdf" --goal "..." --out "test_debug_output"`
- 成功生成: `01_full_extract.json`, `02_hybrid_retrieval.json`, `02_writing_material_pack.json`, `03_academic_scoring.json`, `04_causal_dag.json`, `human_view.md`, `project_view.json`, `.docx`

## 待查
- KnowledgeBase 文献导入时的向量化切片策略 (resources_router.py)
- G-Layer `AcademicScorer.analyze_bound_data` 是否真的调用 LLM
- `batch_output_wenxianku_fix/` 目录内容
