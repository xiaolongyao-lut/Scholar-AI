# -*- coding: utf-8 -*-
"""Regression tests for writing-runtime blob spill + read-through.

Drives D-plan §10.3 (docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md).

Covers three behaviours:
  1. Large transcript payloads spill to an external blob file (on-disk JSONL
     keeps a blob_ref placeholder, not the full payload).
  2. `load_transcript` reads blob contents back so the in-memory event looks
     identical to what was originally appended.
  3. `MODULAR_BLOB_SPILL_BYTES` env override lowers the spill threshold so
     smaller payloads also spill.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repositories.writing_runtime_repository import WritingRuntimeRepository


def _make_event(session_id: str, payload: dict) -> dict:
    return {
        "event_id": "evt_test_0001",
        "session_id": session_id,
        "event_kind": "tool_result",
        "timestamp": "2026-04-25T00:00:00Z",
        "workspace_key": "ws_test",
        "parent_event_id": None,
        "payload": payload,
    }


def test_large_tool_result_spills_to_blob(tmp_path: Path) -> None:
    """Payloads above threshold must land in an external blob, not inline JSONL."""
    repo = WritingRuntimeRepository(tmp_path / "runtime.sqlite3")
    session_id = "sess_spill_big"

    big_payload = {"chunks": ["x" * 1024 for _ in range(80)]}  # ~80 KB > 64 KB
    event = _make_event(session_id, big_payload)
    repo.append_transcript_event(session_id, event)

    transcript_path = tmp_path / "transcripts" / f"{session_id}.jsonl"
    assert transcript_path.exists()

    raw_line = transcript_path.read_text(encoding="utf-8").strip()
    on_disk = json.loads(raw_line)

    # On-disk representation must be a blob reference, not the inline payload.
    assert on_disk["payload"].get("inlined") is False
    assert "blob_ref" in on_disk["payload"]
    blob_ref = on_disk["payload"]["blob_ref"]
    assert Path(blob_ref["blob_path"]).exists()
    assert blob_ref["size_bytes"] > 64 * 1024

    # Sanity: the big content is NOT present inline on the JSONL line.
    assert "x" * 500 not in raw_line


def test_blob_read_through_rehydrates_transcript(tmp_path: Path) -> None:
    """load_transcript must hydrate blob_ref entries back to the original payload."""
    repo = WritingRuntimeRepository(tmp_path / "runtime.sqlite3")
    session_id = "sess_spill_roundtrip"

    original_payload = {"chunks": ["y" * 1024 for _ in range(80)], "marker": "sentinel"}
    event = _make_event(session_id, original_payload)
    repo.append_transcript_event(session_id, event)

    loaded = repo.load_transcript(session_id)
    assert len(loaded) == 1
    loaded_payload = loaded[0]["payload"]

    # After rehydration the payload must match the original dict exactly —
    # no blob_ref wrapper, no `inlined: false` leak.
    assert loaded_payload == original_payload
    assert "blob_ref" not in loaded_payload


def test_blob_spill_threshold_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MODULAR_BLOB_SPILL_BYTES must lower the threshold so small payloads spill."""
    monkeypatch.setenv("MODULAR_BLOB_SPILL_BYTES", "64")

    repo = WritingRuntimeRepository(tmp_path / "runtime.sqlite3")
    session_id = "sess_spill_envknob"

    small_but_over = {"data": "z" * 200}  # 200 B > 64 B threshold
    event = _make_event(session_id, small_but_over)
    repo.append_transcript_event(session_id, event)

    transcript_path = tmp_path / "transcripts" / f"{session_id}.jsonl"
    on_disk = json.loads(transcript_path.read_text(encoding="utf-8").strip())
    assert on_disk["payload"].get("inlined") is False
    assert "blob_ref" in on_disk["payload"]

    # Read-through still works under the overridden threshold.
    loaded = repo.load_transcript(session_id)
    assert loaded[0]["payload"] == small_but_over
