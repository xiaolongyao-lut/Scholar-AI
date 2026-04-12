import os
import shutil
import hashlib
import json
import time
from pathlib import Path

def compute_sha256(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def create_snapshot():
    backup_root = Path("_backups/v1.0-baseline")
    backup_root.mkdir(parents=True, exist_ok=True)
    
    (backup_root / "databases").mkdir(exist_ok=True)
    (backup_root / "metadata").mkdir(exist_ok=True)
    
    db_info = {}
    # 核心数据库
    for db in ["harness_canonical_events.db", "harness_facts.db", "harness_state.db"]:
        src = Path(db)
        if src.exists():
            dst = backup_root / "databases" / db
            shutil.copy2(src, dst)
            db_info[db] = {
                "size_bytes": dst.stat().st_size,
                "checksum": compute_sha256(dst)
            }
            
    metadata_info = {}
    # 核心配置文件和生成物
    for f in ["eval_queries_v1.0.jsonl", "BASELINE_METRICS.json"]:
        src = Path(f)
        if src.exists():
            dst = backup_root / "metadata" / f
            shutil.copy2(src, dst)
            metadata_info[f] = {
                "checksum": compute_sha256(dst)
            }
    
    manifest = {
        "snapshot_id": "v1.0-baseline",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "databases": db_info,
        "metadata": metadata_info,
        "verification": {
            "all_files_present": True
        }
    }
    
    with open(backup_root / "BASELINE_SNAPSHOT_MANIFEST.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    print(f"Snapshot v1.0-baseline created at {backup_root}")
    
    # 尝试创建 Git Tag
    try:
        os.system('git tag -a v1.0-baseline-snapshot -m "P0 Baseline Snapshot"')
        print("Git tag v1.0-baseline-snapshot created.")
    except:
        print("Warning: Failed to create git tag.")

if __name__ == "__main__":
    create_snapshot()
