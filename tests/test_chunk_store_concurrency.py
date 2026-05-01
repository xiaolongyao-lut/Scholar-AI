# -*- coding: utf-8 -*-
"""Focused regression for P2 L1: chunk-store read-modify-write thread safety.

Constructs two threads writing concurrently to the same project's chunk store
and asserts that chunk count does not get lost due to race conditions.
"""

import json
import tempfile
import threading
from pathlib import Path

import pytest

# Import the functions under test (they will be patched to use test dirs)
import routers.resources_router as rr


@pytest.fixture
def isolated_chunk_dir(monkeypatch, tmp_path):
    """Override chunk store directory to use isolated temp path."""
    test_chunk_dir = tmp_path / "chunk_store"
    test_chunk_dir.mkdir(parents=True, exist_ok=True)
    
    # Override the module-level _CHUNK_STORE_DIR
    monkeypatch.setattr(rr, "_CHUNK_STORE_DIR", test_chunk_dir)
    
    # Also override the resolution function to use test path
    original_resolve = rr._resolve_data_dir
    def patched_resolve(project_id):
        doc_dir, _ = original_resolve(project_id)
        return doc_dir, test_chunk_dir
    monkeypatch.setattr(rr, "_resolve_data_dir", patched_resolve)
    
    return test_chunk_dir


def test_concurrent_chunk_store_write_preserves_all_chunks(isolated_chunk_dir):
    """Race condition test: two threads concurrently add chunks to same project.
    
    Without thread safety, the read-modify-write pattern can lose updates:
    - Thread A reads store (empty)
    - Thread B reads store (empty)
    - Thread A writes {material_1: [chunk]}
    - Thread B writes {material_2: [chunk]} (overwrites A's work)
    - Result: material_1 lost!
    
    This test verifies that with proper locking, both materials are preserved.
    """
    project_id = "test_project_concurrent"
    
    # Prepare two distinct materials with different chunks
    material_1 = "paper_001"
    chunks_1 = [
        {
            "chunk_id": "c1",
            "text": "Content from paper 001",
            "title": "Paper 001",
            "material_id": material_1,
        }
    ]
    
    material_2 = "paper_002"
    chunks_2 = [
        {
            "chunk_id": "c2",
            "text": "Content from paper 002",
            "title": "Paper 002",
            "material_id": material_2,
        }
    ]
    
    errors = []
    
    def write_material(material_id, chunks):
        """Helper: read-modify-write pattern using atomic helper."""
        try:
            def updater(store):
                store[material_id] = chunks
                return store
            rr._update_chunk_store_atomic(project_id, updater)
        except Exception as e:
            errors.append(e)
    
    # Launch two threads that will race to write
    thread_1 = threading.Thread(target=write_material, args=(material_1, chunks_1))
    thread_2 = threading.Thread(target=write_material, args=(material_2, chunks_2))
    
    thread_1.start()
    thread_2.start()
    
    thread_1.join()
    thread_2.join()
    
    # Check for any errors during writes
    assert not errors, f"Errors during concurrent writes: {errors}"
    
    # Now read back and verify BOTH materials are present
    final_store = rr._load_chunk_store(project_id)
    
    assert material_1 in final_store, f"Material {material_1} lost during concurrent write"
    assert material_2 in final_store, f"Material {material_2} lost during concurrent write"
    
    # Verify chunk counts are correct
    assert len(final_store[material_1]) == 1, "Material 1 chunk count incorrect"
    assert len(final_store[material_2]) == 1, "Material 2 chunk count incorrect"
    
    # Verify chunk content integrity
    assert final_store[material_1][0]["chunk_id"] == "c1"
    assert final_store[material_2][0]["chunk_id"] == "c2"


def test_concurrent_chunk_store_update_same_material(isolated_chunk_dir):
    """Additional race test: two threads updating the same material.
    
    This tests a different race pattern where both threads modify the same key.
    With atomic updates, both operations should complete successfully.
    """
    project_id = "test_project_same_material"
    material_id = "paper_shared"
    
    # Initialize store with one chunk
    initial_chunks = [
        {
            "chunk_id": "c0",
            "text": "Initial content",
            "title": "Initial",
            "material_id": material_id,
        }
    ]
    rr._save_chunk_store(project_id, {material_id: initial_chunks})
    
    # Two threads will try to append different chunks
    chunk_a = {
        "chunk_id": "ca",
        "text": "Content from thread A",
        "title": "Thread A",
        "material_id": material_id,
    }
    chunk_b = {
        "chunk_id": "cb",
        "text": "Content from thread B",
        "title": "Thread B",
        "material_id": material_id,
    }
    
    errors = []
    
    def append_chunk(chunk):
        """Helper: load, append, save using atomic helper."""
        try:
            def updater(store):
                if material_id not in store:
                    store[material_id] = []
                store[material_id] = store[material_id] + [chunk]
                return store
            rr._update_chunk_store_atomic(project_id, updater)
        except Exception as e:
            errors.append(e)
    
    thread_a = threading.Thread(target=append_chunk, args=(chunk_a,))
    thread_b = threading.Thread(target=append_chunk, args=(chunk_b,))
    
    thread_a.start()
    thread_b.start()
    
    thread_a.join()
    thread_b.join()
    
    assert not errors, f"Errors during concurrent updates: {errors}"
    
    # Read final state
    final_store = rr._load_chunk_store(project_id)
    assert material_id in final_store
    
    # With proper locking, we should have all 3 chunks (initial + both appends)
    chunk_count = len(final_store[material_id])
    assert chunk_count == 3, f"Expected 3 chunks, got {chunk_count}"
    
    # Verify no corruption: all chunks should have valid chunk_ids
    chunk_ids = [c["chunk_id"] for c in final_store[material_id]]
    assert chunk_ids == ["c0", "ca", "cb"] or chunk_ids == ["c0", "cb", "ca"], \
        f"Expected ordered chunks, got {chunk_ids}"
