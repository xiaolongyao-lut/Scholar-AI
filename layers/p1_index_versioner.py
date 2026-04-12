import json
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger("P1_IndexVersioner")

class IndexVersionManager:
    """
    索引版本管理器 (P1 核心组件)
    功能:
    - 自动备份索引 (至 legacy_archive/index_backups)
    - 记录版本变更日志
    - 支持从旧版本恢复
    """
    
    def __init__(self, 
                 index_dir: str = ".",
                 archive_dir: str = "legacy_archive/index_backups"):
        
        self.index_dir = Path(index_dir)
        self.archive_dir = Path(archive_dir)
        self.version_log_path = self.archive_dir / "index_version_history.json"
        
        # 确保目录存在
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        if not self.version_log_path.exists():
            self.version_log_path.write_text(json.dumps({"versions": []}, indent=2, ensure_ascii=False))
    
    def save_index_version(self, version_name: str, description: str = ""):
        """
        保存当前索引为新版本
        """
        backup_path = self.archive_dir / version_name
        
        if backup_path.exists():
            logger.warning(f"Version {version_name} already exists. Overwriting...")
            shutil.rmtree(backup_path)
            
        backup_path.mkdir(parents=True)
        
        # 复制所有主索引文件
        files_saved = {}
        for file in self.index_dir.glob("05_master_global_index*.json"):
            shutil.copy2(file, backup_path)
            files_saved[file.name] = file.stat().st_size
            
        # 记录版本信息
        try:
            log_data = json.loads(self.version_log_path.read_text(encoding='utf-8'))
        except:
            log_data = {"versions": []}
            
        new_version = {
            "version": version_name,
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "files": files_saved
        }
        log_data["versions"].append(new_version)
        
        self.version_log_path.write_text(json.dumps(log_data, indent=2, ensure_ascii=False), encoding='utf-8')
        logger.info(f"Successfully saved index version: {version_name}")
        return new_version

    def list_versions(self) -> List[Dict]:
        """列出所有已保存的版本"""
        try:
            log_data = json.loads(self.version_log_path.read_text(encoding='utf-8'))
            return log_data.get("versions", [])
        except:
            return []

    def restore_index_version(self, version_name: str):
        """
        回滚索引到指定版本
        """
        backup_path = self.archive_dir / version_name
        if not backup_path.exists():
            raise FileNotFoundError(f"Version {version_name} not found in archive.")
            
        logger.info(f"Restoring index to version: {version_name}...")
        
        for file in backup_path.glob("*.json"):
            shutil.copy2(file, self.index_dir)
            logger.info(f"Restored: {file.name}")
            
        return True

if __name__ == "__main__":
    # 简易测试
    manager = IndexVersionManager()
    print("Available versions:", manager.list_versions())
