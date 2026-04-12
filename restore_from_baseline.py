import os
import shutil
import hashlib
import json
from pathlib import Path

def compute_sha256(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def restore():
    snapshot_dir = Path("_backups/v1.0-baseline")
    manifest_path = snapshot_dir / "BASELINE_SNAPSHOT_MANIFEST.json"
    
    if not manifest_path.exists():
        print("Error: Snapshot manifest not found.")
        return

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"Restoring from snapshot {manifest['snapshot_id']} (created at {manifest['created_at']})...")

    # 1. 验证数据库
    for db_name, info in manifest["databases"].items():
        src = snapshot_dir / "databases" / db_name
        current = Path(db_name)
        
        # 校验备份文件是否完好
        if compute_sha256(src) != info["checksum"]:
            print(f"Error: Checksum mismatch for backup {db_name}. Corruption detected!")
            return
            
        # 还原
        shutil.copy2(src, current)
        print(f"Restored database: {db_name}")

    # 2. 验证元数据
    for f_name, info in manifest["metadata"].items():
        src = snapshot_dir / "metadata" / f_name
        current = Path(f_name)
        
        if compute_sha256(src) != info["checksum"]:
             print(f"Error: Checksum mismatch for backup {f_name}.")
             return

        shutil.copy2(src, current)
        print(f"Restored metadata: {f_name}")

    print("Restore completed successfully. Environment is now at baseline state.")

if __name__ == "__main__":
    restore()
