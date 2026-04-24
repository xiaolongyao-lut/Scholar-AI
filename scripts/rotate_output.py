#!/usr/bin/env python3
"""
Output rotation script for cost tracking files.

Rotates output/llm_cost.jsonl and output/rerank_cost.jsonl when they exceed
64 MB, archiving them to output/archive/YYYY-MM/ with timestamp.

Usage:
    python scripts/rotate_output.py

Typically run manually by operations team every Monday.
"""

import sys
from pathlib import Path
from datetime import datetime
import shutil


def should_rotate(file_path: Path, threshold_mb: int = 64) -> bool:
    """Check if file exists and exceeds threshold."""
    if not file_path.exists():
        return False
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    return file_size_mb > threshold_mb


def rotate_file(file_path: Path, output_dir: Path) -> Path:
    """
    Archive file to output/archive/YYYY-MM/ with timestamp.
    
    Returns path to archived file.
    """
    # Create archive directory with YYYY-MM structure
    year_month = datetime.now().strftime("%Y-%m")
    archive_dir = output_dir / "archive" / year_month
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Generate archive filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = file_path.stem  # e.g., "llm_cost" or "rerank_cost"
    suffix = file_path.suffix  # e.g., ".jsonl"
    archive_name = f"{stem}_{timestamp}{suffix}"
    archive_path = archive_dir / archive_name

    # Move file to archive
    shutil.move(str(file_path), str(archive_path))
    
    return archive_path


def main():
    """Main rotation logic."""
    # Determine output directory (relative to script location)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    output_dir = repo_root / "output"

    if not output_dir.exists():
        print(f"Output directory not found: {output_dir}")
        return 1

    # Files to check for rotation
    files_to_check = [
        output_dir / "llm_cost.jsonl",
        output_dir / "rerank_cost.jsonl",
    ]

    threshold_mb = 64
    rotated_count = 0

    print(f"Checking files for rotation (threshold: {threshold_mb} MB)...")
    
    for file_path in files_to_check:
        if should_rotate(file_path, threshold_mb):
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            print(f"  {file_path.name}: {file_size_mb:.2f} MB > {threshold_mb} MB, rotating...")
            archive_path = rotate_file(file_path, output_dir)
            print(f"    Archived to: {archive_path.relative_to(repo_root)}")
            rotated_count += 1
        else:
            if file_path.exists():
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                print(f"  {file_path.name}: {file_size_mb:.2f} MB ≤ {threshold_mb} MB, skipping")
            else:
                print(f"  {file_path.name}: not found, skipping")

    print(f"\nRotation complete: {rotated_count} file(s) archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
