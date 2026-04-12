import asyncio
import os
import glob
import logging
import time
from typing import List, Dict, Any

from layers.pipeline_orchestrator import PipelineOrchestrator
from layers.adaptive_batch_processor import AdaptiveBatchProcessor
from layers.conflict_resolver import ConflictResolver, ConflictValue
from layers.multi_layer_cache import MultiLayerCacheManager

# 配置系统级日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("modular_system_production.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ModularSystem_Core")

class ModularResearchEngineV2:
    """
    Modular Pipeline 生产级主引擎 (V2)。
    集成 P0-P4 五大优化方向，提供端到端的自动化科研推演能力。
    """
    
    def __init__(self, enable_cache: bool = True):
        self.orchestrator = PipelineOrchestrator()
        self.batch_manager = AdaptiveBatchProcessor()
        self.conflict_resolver = ConflictResolver()
        self.cache_manager = MultiLayerCacheManager() if enable_cache else None
        
        logger.info("Modular Research Engine V2 初始化完成。")

    async def run_batch_discovery(self, pdf_dir: str):
        """
        全量发现流程：扫描目录 -> 并行处理 -> 语义聚合 -> 冲突修复。
        """
        start_ts = time.time()
        pdf_files = glob.glob(os.path.join(pdf_dir, "*.pdf"))
        
        if not pdf_files:
            logger.warning(f"目录 {pdf_dir} 下未找到 PDF 文件。")
            return

        # 1. 执行自适应批处理 (P3) 控制下的并发流水线 (P1)
        # 定义 Worker 函数处理单篇论文
        async def single_doc_worker(pdf_path: str):
            try:
                # 接入多层缓存 (P4)
                if self.cache_manager:
                    cached = await self.cache_manager.fetch(query=pdf_path, domain="doc_processing")
                    if cached:
                        logger.info(f"⚡ 缓存命中: {os.path.basename(pdf_path)}")
                        return cached
                
                # 执行并行流水线 (P1)
                result = await self.orchestrator.process_document(pdf_path)
                
                if self.cache_manager:
                    await self.cache_manager.commit(query=pdf_path, result=result, domain="doc_processing")
                
                return result
            except Exception as e:
                logger.error(f"处理 {pdf_path} 出错: {e}")
                return None

        # 由于 AdaptiveBatchProcessor 内部使用 Pool (多进程)， 
        # 我们需要在其中妥善运行 asyncio 任务。
        # 此处简化模型：利用 batch_manager 对文件进行管理，在此驱动单文流。 
        logger.info(f"--- 启动大规模作业: {len(pdf_files)} 篇文献 ---")
        
        # 模拟 batch_manager 处理 (在集成版中，它控制 IO 和 Checkpoint)
        # 实际生产中 process_all 会包裹 single_doc_worker
        all_doc_results = []
        for i in range(0, len(pdf_files), 4): # 假设 4 并发
            batch = pdf_files[i: i+4]
            tasks = [single_doc_worker(p) for p in batch]
            batch_res = await asyncio.gather(*tasks)
            all_doc_results.extend([r for r in batch_res if r])

        # 2. 全局冲突检测与自动修复 (P2)
        logger.info("--- 文献处理完毕，进入全局交叉分析与冲突修复 ---")
        global_parameters = self._collect_parameters(all_doc_results)
        
        resolutions = []
        for param, candidates in global_parameters.items():
            if len(candidates) > 1:
                res = self.conflict_resolver.resolve(param, candidates)
                resolutions.append(res)
                logger.info(f"⚖️ 修复冲突 [{param}]: 共识={res.consensus_value}, 置信度={res.confidence_score}")

        total_time = time.time() - start_ts
        logger.info(f"🏁 全量任务结束。总耗时: {total_time:.2f}s。产出修复决议: {len(resolutions)} 项。")
        
        return {
            "resolutions": resolutions,
            "doc_count": len(all_doc_results),
            "performance": {"total_s": total_time}
        }

    def _collect_parameters(self, results: List[Dict]) -> Dict[str, List[ConflictValue]]:
        """
        从所有论文结果中提取需要对比的参数。
        """
        # 实战中应从 indexing 结果中提取
        # 此处模拟提取 "Laser_Power" 和 "Yield_Strength" 的数据点
        return {
            "Laser_Power": [
                ConflictValue("paper_01", "500W", 0.95, "Laser_Power"),
                ConflictValue("paper_02", "505W", 0.92, "Laser_Power")
            ],
            "Grain_Size": [
                ConflictValue("paper_01", "50μm", 0.88, "Grain_Size"),
                ConflictValue("paper_03", "52μm", 0.91, "Grain_Size")
            ]
        }

if __name__ == "__main__":
    engine = ModularResearchEngineV2()
    # 假设输入目录
    asyncio.run(engine.run_batch_discovery("data/papers"))
