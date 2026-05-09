import hashlib
import json
import shutil
from pathlib import Path

from sqlite_maintenance import restore_report


BASELINE_ROOT = Path("_backups/v1.0-baseline")


def compute_sha256(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def restore():
    snapshot_dir = BASELINE_ROOT
    manifest_path = snapshot_dir / "BASELINE_SNAPSHOT_MANIFEST.json"
    
    if not manifest_path.exists():
        print("Error: Snapshot manifest not found.")
        return

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"Restoring from snapshot {manifest['snapshot_id']} (created at {manifest['created_at']})...")

    restore_result = restore_report(snapshot_dir, target_scope="both")
    if not restore_result.get("ok", False):
        print("Error: SQLite restore completed with integrity issues.")
        return

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
