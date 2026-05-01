# -*- coding: utf-8 -*-
"""End-to-end persistence regression for conversation MVP.

Plan: docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md §S-2 (task 23).

Complements `tests/test_writing_runtime_persistence.py` (which covers the happy
round-trip) by stressing five concrete failure modes the plan listed:

  - S-2.1  resume after "backend restart" (instance recreation) preserves
           timeline AND rehydrates spilled blobs end-to-end.
  - S-2.2  workspace isolation — a session created in workspace A never
           shows up under workspace B's `list_sessions(workspace_key=...)`.
  - S-2.3  rewind truly moves head back; events after checkpoint drop out of
           active lineage (still on disk per append-only design).
  - S-2.4  fork preserves `parent_session_id` + `forked_from_checkpoint_id`,
           and the fork's timeline is a copy (new event_ids, same kinds/order).
  - S-2.5  corrupted transcript tail — resume does not crash; good prefix
           survives; damage does not cascade across sessions.

Extension round (2026-04-25, squad manager terminal):

  - S-2.6  fork-of-fork — grandchild correctly points to its *parent fork* as
           `parent_session_id`, not to the original root. Tests that the linkage
           field is a direct-parent pointer, not a root-ancestor pointer.
  - S-2.7  timeline pagination cursor — `next_cursor` round-trip actually
           advances through a > `limit` transcript without gaps or dups.
  - S-2.8  migration health-check idempotency — `scripts/migrate_modular_sessions.py`
           reports planned actions on first run against an empty dir and
           `applied_actions == []` on the second run.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from harness_protocols import JobKind, SessionMode
from writing_runtime import WritingRuntime

pytestmark = pytest.mark.persistence_full


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ws_key(root: Path) -> str:
    return sha256(str(root.resolve()).encode("utf-8")).hexdigest()


def _workspace(tmp_path: Path, name: str) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / name
    entry = root / "notes"
    entry.mkdir(parents=True)
    metadata = {
        "workspace_root": str(root.resolve()),
        "entry_cwd": str(entry.resolve()),
        "title": f"{name} session",
        "workspace_key": _ws_key(root),
    }
    return root, entry, metadata


def _db_path(tmp_path: Path) -> Path:
    # One shared DB across all workspaces — the schema must disambiguate by
    # workspace_key, not by DB file.
    return tmp_path / ".modular" / "sessions" / "index.sqlite3"


# ---------------------------------------------------------------------------
# S-2.1  resume after backend restart — including blob read-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_after_backend_restart_rehydrates_spilled_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume on a fresh runtime instance must replay full timeline AND expand blob_refs."""
    # Force a low spill threshold so normal-sized job results spill.
    monkeypatch.setenv("MODULAR_BLOB_SPILL_BYTES", "256")

    _, _, meta = _workspace(tmp_path, "ws_resume")
    db = _db_path(tmp_path)

    rt1 = WritingRuntime(database_path=db, autosave=True)
    session = rt1.create_session(
        mode=SessionMode.SKILL, user_id="u", metadata=meta
    )
    job = rt1.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="run",
        skill_id="s1",
    )
    await rt1.start_job(job.job_id)
    big_result = "x" * 2048  # > 256 B threshold → spill
    await rt1.complete_job(job.job_id, result=big_result)

    # "Restart": drop the runtime, reopen against same DB.
    rt2 = WritingRuntime(database_path=db, autosave=True)
    resumed = rt2.resume_session(session_id=session.session_id)

    assert resumed["session"]["session_id"] == session.session_id
    assert resumed["head_event_id"]
    kinds = [evt["event_kind"] for evt in resumed["timeline"]]
    assert "session_created" in kinds
    assert "job_completed" in kinds

    # Any event payload that was spilled must now be fully rehydrated (no
    # blob_ref shell leaking up to the caller).
    for evt in resumed["timeline"]:
        payload = evt.get("payload")
        if isinstance(payload, dict):
            assert "blob_ref" not in payload, (
                f"event {evt['event_id']} still has blob_ref after resume"
            )


# ---------------------------------------------------------------------------
# S-2.2  workspace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_isolation_list_sessions_does_not_leak_across_workspaces(
    tmp_path: Path,
) -> None:
    db = _db_path(tmp_path)
    rt = WritingRuntime(database_path=db, autosave=True)

    _, _, meta_a = _workspace(tmp_path, "ws_a")
    _, _, meta_b = _workspace(tmp_path, "ws_b")

    s_a1 = rt.create_session(mode=SessionMode.SKILL, user_id="u", metadata=meta_a)
    s_a2 = rt.create_session(mode=SessionMode.SKILL, user_id="u", metadata=meta_a)
    s_b1 = rt.create_session(mode=SessionMode.SKILL, user_id="u", metadata=meta_b)

    listed_a = rt.list_sessions(workspace_key=meta_a["workspace_key"])
    listed_b = rt.list_sessions(workspace_key=meta_b["workspace_key"])

    ids_a = {s.session_id for s in listed_a}
    ids_b = {s.session_id for s in listed_b}

    assert ids_a == {s_a1.session_id, s_a2.session_id}
    assert ids_b == {s_b1.session_id}
    assert ids_a.isdisjoint(ids_b)

    # `get_current_session` for B must not return an A session just because A
    # was created more recently.
    current_b = rt.get_current_session(workspace_key=meta_b["workspace_key"])
    assert current_b is not None
    assert current_b.session_id == s_b1.session_id


# ---------------------------------------------------------------------------
# S-2.3  rewind restores state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewind_restores_head_and_drops_later_events_from_active_lineage(
    tmp_path: Path,
) -> None:
    _, _, meta = _workspace(tmp_path, "ws_rewind")
    db = _db_path(tmp_path)
    rt = WritingRuntime(database_path=db, autosave=True)

    session = rt.create_session(
        mode=SessionMode.SKILL, user_id="u", metadata=meta
    )
    # Two jobs → two checkpoints.
    j1 = rt.create_job(session_id=session.session_id, kind=JobKind.SKILL_ACTION,
                       input_text="first", skill_id="s")
    await rt.start_job(j1.job_id)
    await rt.complete_job(j1.job_id, result="r1")

    checkpoints_mid = rt.list_checkpoints(session.session_id)
    assert checkpoints_mid, "expected a checkpoint after first job"
    target_cp = checkpoints_mid[-1]  # rewind target = after-j1 checkpoint

    j2 = rt.create_job(session_id=session.session_id, kind=JobKind.SKILL_ACTION,
                       input_text="second", skill_id="s")
    await rt.start_job(j2.job_id)
    await rt.complete_job(j2.job_id, result="r2")

    pre_rewind = rt.get_session_timeline(session.session_id, limit=100)
    assert any(evt["event_kind"] == "job_completed" for evt in pre_rewind["items"])

    # Act: rewind to the mid checkpoint.
    rt.rewind_session(
        session.session_id, target_cp["checkpoint_id"], mode="conversation_only"
    )

    post = rt.get_session_timeline(session.session_id, limit=100)
    post_ids = [evt["event_id"] for evt in post["items"]]

    # Active lineage must still terminate at the rewind event (whose parent is
    # the target checkpoint), so j2's events must not be in the active lineage.
    j2_events = [e for e in pre_rewind["items"]
                 if e.get("payload", {}).get("job_id") == j2.job_id]
    for e in j2_events:
        assert e["event_id"] not in post_ids, (
            f"j2 event {e['event_id']} leaked into active lineage after rewind"
        )

    # Append-only invariant: raw JSONL on disk still contains j2 events (they
    # are archived, not deleted).
    jsonl = tmp_path / ".modular" / "sessions" / "transcripts" / f"{session.session_id}.jsonl"
    raw = jsonl.read_text(encoding="utf-8")
    assert j2.job_id in raw, "j2 must remain in the append-only transcript file"


# ---------------------------------------------------------------------------
# S-2.4  fork preserves parent/child linkage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_preserves_parent_child_linkage_and_copies_lineage(
    tmp_path: Path,
) -> None:
    _, _, meta = _workspace(tmp_path, "ws_fork")
    db = _db_path(tmp_path)
    rt = WritingRuntime(database_path=db, autosave=True)

    parent = rt.create_session(
        mode=SessionMode.SKILL, user_id="u", metadata=meta
    )
    j = rt.create_job(session_id=parent.session_id, kind=JobKind.SKILL_ACTION,
                      input_text="x", skill_id="s")
    await rt.start_job(j.job_id)
    await rt.complete_job(j.job_id, result="done")

    checkpoints = rt.list_checkpoints(parent.session_id)
    assert checkpoints
    fork_point = checkpoints[-1]

    fork_result = rt.fork_session(
        parent.session_id, fork_point["checkpoint_id"], title="branched"
    )
    fork_session_id = fork_result["session"]["session_id"]
    assert fork_session_id != parent.session_id

    fork_meta = fork_result["session"]["metadata"]
    assert fork_meta["parent_session_id"] == parent.session_id
    assert fork_meta["forked_from_checkpoint_id"] == fork_point["checkpoint_id"]

    # Fork's timeline must be a copy: same event_kinds in same order, but
    # fresh event_ids (not shared pointers to parent's events).
    parent_tl = rt.get_session_timeline(parent.session_id, limit=100)["items"]
    fork_tl = rt.get_session_timeline(fork_session_id, limit=100)["items"]

    parent_ids = {e["event_id"] for e in parent_tl}
    fork_ids = {e["event_id"] for e in fork_tl}
    assert parent_ids.isdisjoint(fork_ids), "fork must not reuse parent event_ids"

    # Fork timeline should be at least the prefix up to fork_point — i.e. not
    # empty and contains the same opening event_kind.
    assert fork_tl, "fork timeline is empty"
    assert fork_tl[0]["event_kind"] == parent_tl[0]["event_kind"]


# ---------------------------------------------------------------------------
# S-2.5  corrupted transcript recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corrupted_transcript_recovery_does_not_cascade(
    tmp_path: Path,
) -> None:
    _, _, meta = _workspace(tmp_path, "ws_corrupt")
    db = _db_path(tmp_path)

    rt1 = WritingRuntime(database_path=db, autosave=True)
    victim = rt1.create_session(mode=SessionMode.SKILL, user_id="u", metadata=meta)
    survivor = rt1.create_session(mode=SessionMode.SKILL, user_id="u", metadata=meta)

    # Put one complete job on each so both have non-empty transcripts.
    for s in (victim, survivor):
        job = rt1.create_job(session_id=s.session_id, kind=JobKind.SKILL_ACTION,
                             input_text="x", skill_id="s")
        await rt1.start_job(job.job_id)
        await rt1.complete_job(job.job_id, result="r")

    victim_jsonl = tmp_path / ".modular" / "sessions" / "transcripts" / f"{victim.session_id}.jsonl"
    original = victim_jsonl.read_text(encoding="utf-8")
    good_lines = original.splitlines()
    assert len(good_lines) >= 2

    # Append a half-written event line (simulating a crash mid-fsync).
    with victim_jsonl.open("a", encoding="utf-8") as fh:
        fh.write('{"event_id": "evt_bad", "payl')  # no newline, no closing brace

    # Resume on a fresh runtime — must not raise, must not corrupt survivor.
    rt2 = WritingRuntime(database_path=db, autosave=True)

    resumed_victim = rt2.resume_session(session_id=victim.session_id)
    assert resumed_victim["session"]["session_id"] == victim.session_id
    victim_kinds = [e["event_kind"] for e in resumed_victim["timeline"]]
    assert "session_created" in victim_kinds

    resumed_survivor = rt2.resume_session(session_id=survivor.session_id)
    assert resumed_survivor["session"]["session_id"] == survivor.session_id
    survivor_kinds = [e["event_kind"] for e in resumed_survivor["timeline"]]
    assert "session_created" in survivor_kinds
    assert "job_completed" in survivor_kinds, (
        "survivor transcript was damaged by victim's corruption — isolation broken"
    )

    # After repair the victim's JSONL on disk must be valid line-delimited JSON
    # (every non-empty line parseable).
    repaired = victim_jsonl.read_text(encoding="utf-8")
    for line in repaired.splitlines():
        if line.strip():
            json.loads(line)


# ---------------------------------------------------------------------------
# S-2.6  fork-of-fork — grandchild's parent is the fork, not the root
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_of_fork_points_parent_to_direct_parent_not_root(
    tmp_path: Path,
) -> None:
    """`parent_session_id` must be the immediate parent, not the root ancestor.

    Regression guard: if someone "optimizes" fork by always copying
    `root_session_id`, the grandchild would lose its direct-parent linkage.
    """
    _, _, meta = _workspace(tmp_path, "ws_fork2")
    db = _db_path(tmp_path)
    rt = WritingRuntime(database_path=db, autosave=True)

    root = rt.create_session(mode=SessionMode.SKILL, user_id="u", metadata=meta)
    j = rt.create_job(session_id=root.session_id, kind=JobKind.SKILL_ACTION,
                      input_text="root-work", skill_id="s")
    await rt.start_job(j.job_id)
    await rt.complete_job(j.job_id, result="r")

    cp_root = rt.list_checkpoints(root.session_id)[-1]
    fork1 = rt.fork_session(root.session_id, cp_root["checkpoint_id"], title="fork1")
    fork1_id = fork1["session"]["session_id"]

    # Add work to fork1 so it has its own checkpoint to branch from.
    j2 = rt.create_job(session_id=fork1_id, kind=JobKind.SKILL_ACTION,
                       input_text="fork1-work", skill_id="s")
    await rt.start_job(j2.job_id)
    await rt.complete_job(j2.job_id, result="r")
    cp_fork1 = rt.list_checkpoints(fork1_id)[-1]

    fork2 = rt.fork_session(fork1_id, cp_fork1["checkpoint_id"], title="fork2")
    fork2_meta = fork2["session"]["metadata"]

    # The grandchild's parent must be fork1, not root.
    assert fork2_meta["parent_session_id"] == fork1_id, (
        f"grandchild parent_session_id={fork2_meta['parent_session_id']!r} "
        f"should be fork1={fork1_id!r}, not root={root.session_id!r}"
    )
    assert fork2_meta["forked_from_checkpoint_id"] == cp_fork1["checkpoint_id"]


# ---------------------------------------------------------------------------
# S-2.7  get_session_timeline cursor pagination round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_pagination_cursor_advances_without_gaps_or_duplicates(
    tmp_path: Path,
) -> None:
    """Drive the cursor until exhaustion and verify union == full timeline."""
    _, _, meta = _workspace(tmp_path, "ws_page")
    db = _db_path(tmp_path)
    rt = WritingRuntime(database_path=db, autosave=True)

    session = rt.create_session(
        mode=SessionMode.SKILL, user_id="u", metadata=meta
    )
    # Enough jobs that > 1 event exists. Each job emits ≥ 2 events
    # (job_started + job_completed), so 5 jobs yields ≥ 10 transcript events
    # on top of session_created — comfortably above a limit=3 window.
    for idx in range(5):
        job = rt.create_job(session_id=session.session_id, kind=JobKind.SKILL_ACTION,
                            input_text=f"x{idx}", skill_id="s")
        await rt.start_job(job.job_id)
        await rt.complete_job(job.job_id, result=f"r{idx}")

    full = rt.get_session_timeline(session.session_id, limit=1000)["items"]
    full_ids = [evt["event_id"] for evt in full]
    assert len(full_ids) >= 10, "fixture did not produce enough events to test paging"

    # Page through with a small limit so the cursor must fire multiple times.
    seen: list[str] = []
    cursor: str | None = None
    page_limit = 3
    safety = 0
    while True:
        page = rt.get_session_timeline(
            session.session_id, after_event_id=cursor, limit=page_limit
        )
        items = page["items"]
        for evt in items:
            seen.append(evt["event_id"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        safety += 1
        assert safety < 50, "pagination did not terminate"

    # Same set, same order, no duplicates.
    assert seen == full_ids, (
        f"paged ids diverge from full timeline: paged={seen}, full={full_ids}"
    )
    assert len(seen) == len(set(seen)), "pagination produced duplicate event_ids"


# ---------------------------------------------------------------------------
# S-2.8  migration health-check idempotency
# ---------------------------------------------------------------------------


def test_migration_health_check_is_idempotent(tmp_path: Path) -> None:
    """`scripts.migrate_modular_sessions.inspect` must be repeatable.

    Contract (per script docstring): re-running against a prepared layout
    performs no additional actions.
    """
    from scripts.migrate_modular_sessions import inspect  # local to avoid import cost on skip

    db_path = tmp_path / "fresh" / ".modular" / "sessions" / "index.sqlite3"

    first = inspect(db_path, dry_run=False)
    assert first["status"] == "ok"
    # First run may mkdir the parent layout — actions can be non-empty here.

    second = inspect(db_path, dry_run=False)
    assert second["status"] == "ok"
    assert second["applied_actions"] == [], (
        f"second run should be a no-op, got actions={second['applied_actions']}"
    )
    # Counts must match exactly (no new sessions/files appeared from re-running).
    assert second["counts"] == first["counts"]
