from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from literature_assistant.core.wiki.source_registry import WikiRegistry


@dataclass(frozen=True)
class NormalizedEvidence:
    chunk_id: str | None
    source_id: str | None
    text: str
    quote: str | None = None
    page: str | None = None
    rank: int | None = None
    source_labels: list[str] | None = None
    query_overlap_tokens: int | None = None


def coerce_evidence_reference(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "__dict__"):
        return vars(raw)
    if hasattr(raw, "_asdict"):
        return raw._asdict()
    raise TypeError(f"Cannot coerce {type(raw)} to evidence reference")


def normalize_evidence(raw: Any) -> NormalizedEvidence:
    evidence = coerce_evidence_reference(raw)
    chunk_id = evidence.get("chunk_id") or evidence.get("material_id")
    source_id = evidence.get("source_id")
    text = evidence.get("text") or evidence.get("compressed") or ""
    quote = evidence.get("quote")
    page = evidence.get("page")
    rank = evidence.get("rank")
    source_labels = evidence.get("source_labels")
    query_overlap_tokens = evidence.get("query_overlap_tokens")
    return NormalizedEvidence(
        chunk_id=chunk_id,
        source_id=source_id,
        text=text,
        quote=quote,
        page=page,
        rank=rank,
        source_labels=source_labels,
        query_overlap_tokens=query_overlap_tokens,
    )


def lookup_source_for_evidence(
    evidence: NormalizedEvidence,
    registry: WikiRegistry,
) -> str | None:
    if evidence.chunk_id and registry.verify_chunk_exists(evidence.chunk_id):
        return evidence.chunk_id
    if evidence.source_id:
        source = registry.get_source(evidence.source_id)
        if source:
            return evidence.source_id
    return None


def render_citation(evidence: NormalizedEvidence) -> str:
    if evidence.chunk_id:
        return f"[{evidence.chunk_id}]"
    if evidence.source_id:
        if evidence.page:
            return f"[[{evidence.source_id}#page-{evidence.page}]]"
        return f"[[{evidence.source_id}]]"
    return ""


def evidence_to_wiki_citation(
    raw: Any,
    registry: WikiRegistry,
    *,
    fallback_mode: str = "draft",
) -> tuple[str, bool]:
    evidence = normalize_evidence(raw)
    target = lookup_source_for_evidence(evidence, registry)
    if not target:
        if fallback_mode == "draft":
            return "", False
        raise ValueError(f"Evidence target not found in registry: {evidence}")
    citation = render_citation(evidence)
    return citation, True


def parse_prompt_evidence(prompt_line: str) -> dict[str, str]:
    if not isinstance(prompt_line, str):
        raise TypeError("prompt_line must be a string")
    parts = prompt_line.split("/")
    if len(parts) < 2:
        raise ValueError("Invalid prompt evidence format")
    result: dict[str, str] = {}
    for i, part in enumerate(parts):
        if i == 0:
            result["source_id"] = part.strip()
        elif "MATERIAL" in part.upper():
            result["material_id"] = part.split(":")[-1].strip()
        elif "QUOTE" in part.upper():
            result["quote"] = part.split(":", 1)[-1].strip()
        elif "BODY" in part.upper():
            result["body"] = part.split(":", 1)[-1].strip()
    return result


def last_answer_to_synthesis_draft(
    last_answer: Mapping[str, Any],
    registry: WikiRegistry,
) -> dict[str, Any]:
    if not isinstance(last_answer, Mapping):
        raise TypeError("last_answer must be a mapping")
    question = last_answer.get("query") or last_answer.get("question", "")
    answer = last_answer.get("answer", "")
    evidence_refs = last_answer.get("evidence_refs", [])
    citations: list[str] = []
    for ref in evidence_refs:
        citation, found = evidence_to_wiki_citation(ref, registry, fallback_mode="draft")
        if found and citation:
            citations.append(citation)
    body = f"{answer}\n\n## Evidence\n\n" + "\n".join(f"- {cit}" for cit in citations)
    frontmatter = {
        "id": f"synthesis-{hash(question) & 0xFFFFFFFF:08x}",
        "kind": "synthesis",
        "title": question[:100],
        "status": "draft",
    }
    return {"frontmatter": frontmatter, "body": body}
