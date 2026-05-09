from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_RAG_ONCE = REPO_ROOT / "tools" / "squad" / "run-rag-once.ps1"


def test_run_rag_once_has_utf8_bom_for_windows_powershell_file_mode() -> None:
    first_bytes = RUN_RAG_ONCE.read_bytes()[:3]
    assert first_bytes == b"\xef\xbb\xbf"
