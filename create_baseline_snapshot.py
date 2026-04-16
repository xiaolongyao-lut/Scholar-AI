import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from datetime_utils import utc_now_iso_z
from sqlite_maintenance import backup_report


BASELINE_SNAPSHOT_ID = "v1.0-baseline"
BASELINE_ROOT = Path("_backups/v1.0-baseline")
LEGACY_METADATA_FILES = ("eval_queries_v1.0.jsonl", "BASELINE_METRICS.json")


def compute_sha256(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def _copy_metadata_files(backup_root: Path) -> dict[str, dict[str, Any]]:
    metadata_root = backup_root / "metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)

    metadata_info: dict[str, dict[str, Any]] = {}
    for filename in LEGACY_METADATA_FILES:
        src = Path(filename)
        if src.exists():
            dst = metadata_root / filename
            shutil.copy2(src, dst)
            metadata_info[filename] = {
                "checksum": compute_sha256(dst),
                "backup_path": str(dst),
                "size_bytes": dst.stat().st_size,
            }
    return metadata_info


def create_snapshot() -> dict[str, Any]:
    BASELINE_ROOT.mkdir(parents=True, exist_ok=True)

    database_manifest = backup_report(BASELINE_ROOT, target_scope="both", snapshot_id=BASELINE_SNAPSHOT_ID)
    metadata_info = _copy_metadata_files(BASELINE_ROOT)

    manifest = {
        "snapshot_id": BASELINE_SNAPSHOT_ID,
        "created_at": utc_now_iso_z(),
        "databases": database_manifest["databases"],
        "metadata": metadata_info,
        "verification": {
            "all_files_present": all(Path(entry["backup_path"]).exists() for entry in database_manifest["databases"].values())
            and all((BASELINE_ROOT / "metadata" / name).exists() for name in metadata_info),
        },
        "sqlite_manifest_path": database_manifest["manifest_path"],
        "managed_targets": database_manifest["targets"],
    }
    
    with open(BASELINE_ROOT / "BASELINE_SNAPSHOT_MANIFEST.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Snapshot {BASELINE_SNAPSHOT_ID} created at {BASELINE_ROOT}")
    return manifest
    
if __name__ == "__main__":
    create_snapshot()
