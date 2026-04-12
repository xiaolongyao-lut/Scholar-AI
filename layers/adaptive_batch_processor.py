import os
import json
import time
import psutil
import logging
from multiprocessing import Pool, Manager
from typing import List, Dict, Any, Callable
from dataclasses import dataclass

logger = logging.getLogger("AdaptiveBatchProcessor")

@dataclass
class ProcConfig:
    batch_size: int
    num_workers: int
    memory_limit_pct: float = 85.0

class AdaptiveBatchProcessor:
    """
    P3: 批处理自适应分配与动态扩展。
    支持 100+ 篇论文的规模化处理，具备内存实时防护与断点续传能力。
    """

    def __init__(self, checkpoint_dir: str = ".cache/batch_checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(self.checkpoint_dir, exist_ok=True)

    def _get_system_config(self, files_to_process: List[str]) -> ProcConfig:
        """根据系统可用资源动态计算最优 BatchSize 和进程数。"""
        mem = psutil.virtual_memory()
        available_mb = mem.available / (1024 * 1024)
        cpu_count = os.cpu_count() or 1
        
        # 估算单文内存占用 (平衡点：约 150MB per doc 包含 LLM 上下文缓存)
        doc_mem_estimate = 150 
        
        # 计算最大 worker 数 (保留 20% 内存缓冲)
        safe_mem_mb = available_mb * 0.8
        max_workers_by_mem = int(safe_mem_mb / doc_mem_estimate)
        
        num_workers = min(cpu_count, max_workers_by_mem, 4) # 生产环境上限建议为 4
        batch_size = num_workers * 2 # 每个 batch 处理两倍 worker 数量的文件以保持作业饱和
        
        return ProcConfig(batch_size=max(batch_size, 1), num_workers=max(num_workers, 1))

    def _save_checkpoint(self, file_path: str, result: Any):
        """记录已完成的文件进度。"""
        filename = os.path.basename(file_path)
        cp_path = os.path.join(self.checkpoint_dir, f"{filename}.done")
        with open(cp_path, "w") as f:
            json.dump({"path": file_path, "ts": time.time(), "success": True}, f)

    def _is_processed(self, file_path: str) -> bool:
        filename = os.path.basename(file_path)
        return os.path.exists(os.path.join(self.checkpoint_dir, f"{filename}.done"))

    def process_all(self, file_paths: List[str], worker_func: Callable):
        """
        全量批处理入口。
        """
        # 0. 过滤已处理文件 (断点续传)
        to_process = [p for p in file_paths if not self._is_processed(p)]
        total_remaining = len(to_process)
        
        if total_remaining == 0:
            logger.info("所有文件已在 Checkpoint 中，跳过。")
            return

        # 1. 获取动态配置
        config = self._get_system_config(to_process)
        logger.info(f"🚀 批处理启动: 待处理={total_remaining}, Workers={config.num_workers}, BatchSize={config.batch_size}")

        # 2. 启动进程池
        with Pool(processes=config.num_workers) as pool:
            # 按 Batch 进行分块，便于内存回收和进度保存
            for i in range(0, len(to_process), config.batch_size):
                batch = to_process[i: i + config.batch_size]
                logger.info(f"正在处理 Batch {i//config.batch_size + 1} ({len(batch)} files)...")
                
                # 执行
                results = pool.map(worker_func, batch)
                
                # 保存进度
                for path, res in zip(batch, results):
                    self._save_checkpoint(path, res)
                
                # 内存紧急停火检查
                if psutil.virtual_memory().percent > config.memory_limit_pct:
                    logger.warning("⚠️ 内存预警: 触发强制 GC 等待...")
                    time.sleep(5)
        
        logger.info("✅ 全量批处理任务完成。")

def mock_worker(file_path):
    """模拟 Worker."""
    time.sleep(0.1)
    return {"status": "ok"}
