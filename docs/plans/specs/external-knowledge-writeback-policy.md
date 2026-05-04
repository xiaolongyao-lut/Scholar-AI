# External Knowledge Write-Back Policy

> LMWR-467 · Zotero / EndNote / Obsidian write-back boundary

## Decision

External knowledge-base write-back is not part of the current LLM-Wiki/RAG
runtime. Zotero, EndNote, Obsidian, PDF folders, and downloaded reference
repositories remain read-only sources unless the user explicitly authorizes a
future write-back feature by target, field, scope, and rollback plan.

The current implementation must keep `ConnectorSpec.read_only=true`,
`ConnectorSpec.writes_user_library=false`, and `ConnectorScanReport.would_write=false`.
No connector may write user libraries, vault files, attachment folders, local
manager databases, cloud APIs, sync state, qrels/goldset, or default RAG chain
configuration.

## Mature References

| Source | Link | Policy borrowed |
| --- | --- | --- |
| Zotero Web API write requests | `https://www.zotero.org/support/dev/web_api/v3/write_requests` | Write operations need official API write access and version/conflict handling; direct local SQLite writes are out of scope. |
| Zotero Web API basics | `https://www.zotero.org/support/dev/web_api/v3/basics` | Use official API surfaces for remote writes; local read-only connectors must not bypass sync semantics. |
| Obsidian plugin API `Vault` | `https://docs.obsidian.md/Reference/TypeScript+API/Vault` | Obsidian mutations are application/plugin-level operations; external automation should not silently rewrite vault files. |
| Obsidian `Vault.modify` | `https://docs.obsidian.md/Reference/TypeScript+API/Vault/modify` | If future Obsidian writes exist, they should be explicit file-level modifications through supported APIs and user-reviewed diffs. |
| Existing connector runbook | `docs/plans/runbooks/llmwiki-slice-LMWR-419-433-wave13-connectors.md` | Current connectors are read-only, path-guarded, error-sanitized, and no-write. |
| Project decision PD-013 | `docs/plans/active/2026-04-27-full-project-build-master-plan.md` | External academic connectors are read-only by default; write-back requires a separate confirmation. |

## Non-Goals

- No Zotero local SQLite writes.
- No Zotero Web API write client.
- No EndNote `.enl` / `.Data` mutation.
- No Obsidian vault rewrite, rename, delete, tag edit, or frontmatter mutation.
- No attachment/PDF modification.
- No background sync daemon.
- No auto-finalize of wiki drafts into external tools.
- No writes to `github/` or `C:\Users\xiao\Downloads\llmwiki借鉴库`.

## Write-Back Levels

| Level | Status | Description | Allowed now |
| --- | --- | --- | --- |
| L0 Read-only scan | Implemented | List/read metadata or local Markdown/PDF bodies under explicit roots. | Yes |
| L1 Project-local export | Partly implemented elsewhere | Write only under `workspace_artifacts/` as a dry-run report, backup, or user-reviewed export file. | Yes, with focused task |
| L2 User-mediated import package | Design-only | Create RIS/BibTeX/Markdown/JSON under `workspace_artifacts/` for the user to import manually. | Not yet |
| L3 Direct external write | Blocked | Write through Zotero API, Obsidian plugin API, EndNote supported import flow, or any external app state. | No |
| L4 Destructive sync | Forbidden | Delete/rename/overwrite external items or attachment files automatically. | No |

## Future Trigger Conditions

Direct write-back may be designed only when all conditions are true:

1. The user explicitly asks for write-back to a named target, for example
   "write these tags to Zotero collection X".
2. A fresh rollback checkpoint exists.
3. Official or mature documentation for that target write API has been read.
4. The operation is expressible as a dry-run diff with previous values and new
   values.
5. The target supports conflict detection, version checks, or an equivalent
   compare-before-write guard.
6. The operation has a project-local operation journal under
   `workspace_artifacts/runtime_state/wiki/writeback/`.
7. The target has a backup or export plan that can be verified before write.
8. The user confirms the exact dry-run diff after seeing risk and restore limits.

If any condition is missing, the only allowed output is a project-local export
or a runbook telling the user how to perform the import manually.

## Allowed Future Field Surface

Future L3 writes, if separately approved, may only start with low-risk metadata:

| Target | Candidate fields | Forbidden fields |
| --- | --- | --- |
| Zotero | tags, collections, link-to-local wiki draft, note created by this app | item deletion, attachment deletion, original PDF edits, creator/title/year overwrite without diff |
| Obsidian | new note under an app-owned folder, app-owned frontmatter keys | modifying arbitrary user notes, renaming files, deleting files, rewriting links globally |
| EndNote | user-mediated export package only until an official safe write path is chosen | direct `.enl` / `.Data` mutation, attachment edits |

## Required Future Data Contract

The future write-back module should use typed, dry-run-first records similar to
this shape. This is a contract sketch, not an implemented API.

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

WriteBackTarget = Literal["zotero", "obsidian", "endnote"]
WriteBackMode = Literal["dry_run", "write"]


@dataclass(frozen=True)
class WriteBackChange:
    """One proposed external mutation with previous/new values for review."""

    target: WriteBackTarget
    external_id: str
    field_name: str
    previous_value: object
    new_value: object
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class WriteBackPlan:
    """Dry-run-first write-back plan; `would_write` is false until user approval."""

    mode: WriteBackMode
    would_write: bool
    changes: tuple[WriteBackChange, ...]
    backup_paths: tuple[Path, ...]
    official_reference_urls: tuple[str, ...]
    warnings: tuple[str, ...]
    metadata: Mapping[str, object]


def validate_write_back_plan(plan: WriteBackPlan) -> None:
    """Reject unsafe external write plans before any target-specific adapter runs."""

    if plan.mode == "write" and not plan.would_write:
        raise ValueError("write mode requires would_write=true after explicit approval")
    if plan.mode == "dry_run" and plan.would_write:
        raise ValueError("dry-run plans must not write")
    if not plan.official_reference_urls:
        raise ValueError("official target write documentation is required")
    if not plan.backup_paths:
        raise ValueError("external write-back requires a verified backup/export path")
    if any(not change.evidence_refs for change in plan.changes):
        raise ValueError("each write-back change requires provenance evidence")
```

## Rollback Boundary

Code rollback and external data rollback are separate. Restoring a Codex
checkpoint can revert project files, but it cannot automatically undo changes
already synced into Zotero, EndNote, Obsidian, or cloud services.

Any future external write feature therefore needs:

- pre-write backup or export artifact
- operation journal with target id, field, previous value, new value, timestamp,
  and official write API version
- inverse dry-run plan where the target supports reversal
- explicit user review before both write and restore
- no automatic restore

## Acceptance Criteria

- Existing connectors remain read-only.
- No code path for external writes is introduced by LMWR-467.
- Future write-back work has trigger conditions, allowed fields, forbidden
  fields, and rollback limits.
- All instructions include checkpoint and mature-solution search before write
  design or implementation.
