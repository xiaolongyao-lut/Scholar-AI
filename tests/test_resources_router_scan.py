from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from routers.resources_router import (
    _extract_document_content,
    _iter_scan_batches,
    _iter_scan_files,
    _load_zotero_title_map,
    _resolve_scan_workers,
)


def test_iter_scan_files_recurses_and_skips_internal_dirs(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    nested = root / "A1B2C3D4"
    nested.mkdir(parents=True)
    (nested / "paper.pdf").write_bytes(b"%PDF-1.7")

    ignored = root / ".scholarai"
    ignored.mkdir(parents=True)
    (ignored / "ignored.pdf").write_bytes(b"%PDF-1.7")

    files = _iter_scan_files(root)
    rel_paths = sorted(p.relative_to(root).as_posix() for p in files)

    assert "A1B2C3D4/paper.pdf" in rel_paths
    assert ".scholarai/ignored.pdf" not in rel_paths


def test_extract_document_content_supports_notebook_ipynb() -> None:
    notebook = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\\n", "Notebook note"]},
            {"cell_type": "code", "source": ["def foo():\\n", "    return 42\\n"]},
        ]
    }
    raw = json.dumps(notebook, ensure_ascii=False).encode("utf-8")

    content = _extract_document_content("demo.ipynb", raw)

    assert "Notebook Markdown Cell" in content
    assert "Notebook note" in content
    assert "Notebook Code Cell" in content
    assert "def foo()" in content


def test_extract_document_content_includes_notebook_outputs() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["print('hello')\\n"],
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": ["hello\\n"]},
                    {"output_type": "execute_result", "data": {"text/plain": ["42"]}},
                ],
            }
        ]
    }
    raw = json.dumps(notebook, ensure_ascii=False).encode("utf-8")

    content = _extract_document_content("outputs.ipynb", raw)

    assert "Notebook Output Cell" in content
    assert "hello" in content
    assert "42" in content


def test_load_zotero_title_map_reads_zotero_sqlite(tmp_path: Path) -> None:
    data_root = tmp_path / "zotero-data"
    storage_root = data_root / "storage"
    storage_root.mkdir(parents=True)

    db_path = data_root / "zotero.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT)")
    cur.execute("CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT)")
    cur.execute("CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER)")

    cur.execute("INSERT INTO items (itemID, key) VALUES (1, 'AB12CD34')")
    cur.execute("INSERT INTO fields (fieldID, fieldName) VALUES (1, 'title')")
    cur.execute("INSERT INTO itemDataValues (valueID, value) VALUES (1, 'A Zotero Indexed Paper')")
    cur.execute("INSERT INTO itemData (itemID, fieldID, valueID) VALUES (1, 1, 1)")
    conn.commit()
    conn.close()

    title_map = _load_zotero_title_map(storage_root)
    assert title_map.get("AB12CD34") == "A Zotero Indexed Paper"


def test_load_zotero_title_map_supports_fields_combined_fallback(tmp_path: Path) -> None:
    data_root = tmp_path / "zotero-data"
    storage_root = data_root / "storage"
    storage_root.mkdir(parents=True)

    db_path = data_root / "zotero.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT)")
    cur.execute("CREATE TABLE fieldsCombined (fieldID INTEGER PRIMARY KEY, fieldName TEXT)")
    cur.execute("CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER)")

    cur.execute("INSERT INTO items (itemID, key) VALUES (1, 'ZXCVBN12')")
    cur.execute("INSERT INTO fieldsCombined (fieldID, fieldName) VALUES (1, 'title')")
    cur.execute("INSERT INTO itemDataValues (valueID, value) VALUES (1, 'Combined Field Title')")
    cur.execute("INSERT INTO itemData (itemID, fieldID, valueID) VALUES (1, 1, 1)")
    conn.commit()
    conn.close()

    title_map = _load_zotero_title_map(storage_root)
    assert title_map.get("ZXCVBN12") == "Combined Field Title"


def test_resolve_scan_workers_clamps_values() -> None:
    assert _resolve_scan_workers(1) == 1
    assert _resolve_scan_workers(128) == 64
    assert _resolve_scan_workers(8) == 8


def test_iter_scan_batches_splits_evenly() -> None:
    items = [{"idx": i} for i in range(7)]
    batches = _iter_scan_batches(items, 3)

    assert len(batches) == 3
    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert batches[0][0]["idx"] == 0
    assert batches[2][0]["idx"] == 6
