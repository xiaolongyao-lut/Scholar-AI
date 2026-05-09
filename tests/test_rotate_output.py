"""Tests for scripts/rotate_output.py rotation logic."""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime

import pytest


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory structure."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


def test_rotate_when_file_exceeds_threshold(temp_output_dir):
    """Test rotation when file exceeds 64 MB threshold."""
    # Import after fixture creates directories
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from rotate_output import should_rotate, rotate_file

    # Create a file exceeding threshold (use smaller threshold for testing)
    cost_file = temp_output_dir / "llm_cost.jsonl"
    threshold_mb = 1  # Use 1 MB for faster testing
    # Write > 1 MB of data
    line = json.dumps({"event": "test", "cost": 0.001}) + "\n"
    target_bytes = int((threshold_mb + 0.1) * 1024 * 1024)
    with open(cost_file, "w") as f:
        bytes_written = 0
        while bytes_written < target_bytes:
            f.write(line)
            bytes_written += len(line)

    file_size_mb = cost_file.stat().st_size / (1024 * 1024)
    assert file_size_mb > threshold_mb, f"Test file should exceed {threshold_mb} MB, got {file_size_mb:.2f} MB"

    # Check should_rotate returns True
    assert should_rotate(cost_file, threshold_mb)

    # Perform rotation
    archive_path = rotate_file(cost_file, temp_output_dir)

    # Verify archive created in YYYY-MM format
    year_month = datetime.now().strftime("%Y-%m")
    expected_dir = temp_output_dir / "archive" / year_month
    assert expected_dir.exists()
    assert archive_path.parent == expected_dir
    assert archive_path.name.startswith("llm_cost_")
    assert archive_path.suffix == ".jsonl"

    # Verify original file no longer exists
    assert not cost_file.exists()


def test_preserve_when_file_below_threshold(temp_output_dir):
    """Test file is preserved when below 64 MB threshold."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from rotate_output import should_rotate

    # Create a small file
    cost_file = temp_output_dir / "rerank_cost.jsonl"
    with open(cost_file, "w") as f:
        for _ in range(100):
            f.write(json.dumps({"event": "test", "tokens": 100}) + "\n")

    # Verify below threshold
    file_size_mb = cost_file.stat().st_size / (1024 * 1024)
    assert file_size_mb < 64, "Test file should be below 64 MB"

    # Check should_rotate returns False
    assert not should_rotate(cost_file, threshold_mb=64)


def test_rotate_multiple_files(temp_output_dir):
    """Test rotating both llm_cost and rerank_cost files."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from rotate_output import should_rotate, rotate_file

    threshold_mb = 1  # Use 1 MB for faster testing
    files_to_rotate = []

    # Create two files exceeding threshold
    line = json.dumps({"event": "test"}) + "\n"
    target_bytes = int((threshold_mb + 0.1) * 1024 * 1024)
    for filename in ["llm_cost.jsonl", "rerank_cost.jsonl"]:
        cost_file = temp_output_dir / filename
        with open(cost_file, "w") as f:
            bytes_written = 0
            while bytes_written < target_bytes:
                f.write(line)
                bytes_written += len(line)
        files_to_rotate.append(cost_file)

    # Rotate both
    archive_paths = []
    for cost_file in files_to_rotate:
        if should_rotate(cost_file, threshold_mb):
            archive_path = rotate_file(cost_file, temp_output_dir)
            archive_paths.append(archive_path)

    # Verify both archived
    assert len(archive_paths) == 2
    assert all(p.exists() for p in archive_paths)
    assert not any(f.exists() for f in files_to_rotate)


def test_skip_nonexistent_file(temp_output_dir):
    """Test gracefully skips non-existent files."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from rotate_output import should_rotate

    nonexistent = temp_output_dir / "nonexistent.jsonl"
    assert not should_rotate(nonexistent, threshold_mb=64)
