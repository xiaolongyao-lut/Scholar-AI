"""Capability matrix for the 8 AI entries (D-ID-P0-3 / D-ID-P0-4).

Each entry's capability flags are filled conservatively: anything not
verified by repo grep defaults to ``False``. The renderer consumes only
flags that are actively rendered; ``web_browsing`` was removed as a dead
field. ``json_strict`` stays because extractive wiki entries depend on it.

Grep evidence is recorded in inline comments next to each non-default value
so future audits can trace why a flag is ``True``. When a flag flips from
``False`` to ``True`` later, update both the value and the evidence note.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VisibilityModel = Literal["solo", "messages_only", "full"]


@dataclass(frozen=True)
class EntryCapabilities:
    """Per-entry capability bitmap consumed by ``identity_renderer``.

    Flags are advisory prose hints surfaced into the prompt header. The
    backend remains the source of truth for actual permission enforcement
    (per the MCP approval state machine, memory adapter availability, etc).
    """

    entry_id: str
    is_extractive: bool
    mcp_tools: bool
    cross_session_memory: bool
    long_term_memory: bool
    project_meta: bool
    multi_agent: bool
    visibility_model: VisibilityModel
    json_strict: bool


CAPABILITY_MATRIX: dict[str, EntryCapabilities] = {
    "generation": EntryCapabilities(
        entry_id="generation",
        is_extractive=False,
        mcp_tools=False,
        cross_session_memory=True,   # main_rag_workflow.py uses conv_manager.resume_session
        long_term_memory=True,       # memory_adapter injected for project recall
        project_meta=True,           # association_project_id is required
        multi_agent=False,
        visibility_model="solo",
        json_strict=True,            # generation template enforces structured JSON
    ),
    "discussion": EntryCapabilities(
        entry_id="discussion",
        is_extractive=False,
        mcp_tools=True,              # DiscussionMcpOverrides on models/discussion.py
        cross_session_memory=False,  # run_discussion is one-shot, no session_id
        long_term_memory=False,
        project_meta=True,
        multi_agent=True,            # multiple agents debate the same query
        visibility_model="messages_only",  # other agents see only public messages
        json_strict=False,           # free text answers; citations parsed separately
    ),
    "inspiration_fincot": EntryCapabilities(
        entry_id="inspiration_fincot",
        is_extractive=False,
        mcp_tools=False,
        cross_session_memory=False,
        long_term_memory=False,      # inspiration_router import of MempalaceAdapter currently broken; treat as unavailable until Evolution S1 fix lands
        project_meta=True,
        multi_agent=False,
        visibility_model="solo",
        json_strict=False,           # CoT free text + structured 灵感清单
    ),
    "inspiration_irac": EntryCapabilities(
        entry_id="inspiration_irac",
        is_extractive=False,
        mcp_tools=False,
        cross_session_memory=False,
        long_term_memory=False,      # same MempalaceAdapter import bug as inspiration_fincot
        project_meta=True,
        multi_agent=False,
        visibility_model="solo",
        json_strict=False,           # IRAC 4-段叙述式输出
    ),
    "wiki_paper_summary": EntryCapabilities(
        entry_id="wiki_paper_summary",
        is_extractive=True,
        mcp_tools=False,
        cross_session_memory=False,
        long_term_memory=False,
        project_meta=False,          # compiler does not pass project context to summary
        multi_agent=False,
        visibility_model="solo",
        json_strict=True,            # validate_json_response enforces schema
    ),
    "wiki_concept_extract": EntryCapabilities(
        entry_id="wiki_concept_extract",
        is_extractive=True,
        mcp_tools=False,
        cross_session_memory=False,
        long_term_memory=False,
        project_meta=False,
        multi_agent=False,
        visibility_model="solo",
        json_strict=True,
    ),
    "wiki_claim_extract": EntryCapabilities(
        entry_id="wiki_claim_extract",
        is_extractive=True,
        mcp_tools=False,
        cross_session_memory=False,
        long_term_memory=False,
        project_meta=False,
        multi_agent=False,
        visibility_model="solo",
        json_strict=True,
    ),
    "wiki_synthesis": EntryCapabilities(
        entry_id="wiki_synthesis",
        is_extractive=True,
        mcp_tools=False,
        cross_session_memory=False,
        long_term_memory=False,
        project_meta=False,
        multi_agent=False,
        visibility_model="solo",
        json_strict=True,
    ),
}


def get_capabilities(entry_id: str) -> EntryCapabilities:
    """Return capabilities for ``entry_id``.

    Raises ``KeyError`` with a clear message if the entry is unknown so
    that callers cannot silently render a header for an entry that was
    never audited.
    """
    try:
        return CAPABILITY_MATRIX[entry_id]
    except KeyError as exc:
        known = ", ".join(sorted(CAPABILITY_MATRIX))
        raise KeyError(
            f"Unknown identity entry_id={entry_id!r}; known entries: {known}"
        ) from exc
