from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from literature_assistant.core.wiki.models import WikiPageKind, WikiPageStatus
from literature_assistant.core.wiki.page_store import (
    WikiPageStore,
    render_page,
    stable_slug,
)
from literature_assistant.core.wiki.source_registry import WikiRegistry


@dataclass(frozen=True)
class CompilePlan:
    pages_to_create: list[Path]
    pages_to_update: list[Path]
    pages_to_skip: list[Path]


@dataclass(frozen=True)
class CompileResult:
    created: int
    updated: int
    skipped: int
    errors: list[str]


class WikiCompiler:
    def __init__(self, registry: WikiRegistry, page_store: WikiPageStore) -> None:
        self.registry = registry
        self.page_store = page_store

    def compile_source(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        source = self.registry.get_source(source_id)
        if not source:
            return CompileResult(0, 0, 0, [f"Source not found: {source_id}"])
        chunks = self.registry.get_chunks_by_source(source_id)
        slug = stable_slug(source.title)
        relative_path = Path(f"sources/{slug}.md")
        frontmatter = {
            "id": source.source_id,
            "kind": "source",
            "title": source.title,
            "status": WikiPageStatus.final.value,
            "source_type": source.source_type,
            "source_hash": source.source_hash,
            "chunk_count": len(chunks),
        }
        body_lines = [
            f"# {source.title}",
            "",
            f"**Type:** {source.source_type}",
            f"**Path:** `{source.source_path}`",
            f"**Hash:** `{source.source_hash}`",
            f"**Chunks:** {len(chunks)}",
            "",
            "## Chunks",
            "",
        ]
        for chunk in chunks[:10]:
            body_lines.append(f"### Chunk {chunk['chunk_index']}")
            if chunk.get("page"):
                body_lines.append(f"**Page:** {chunk['page']}")
            text_preview = chunk["text"][:200]
            body_lines.append(f"\n{text_preview}...\n")
        body = "\n".join(body_lines)
        if dry_run:
            return CompileResult(1, 0, 0, [])
        rendered = render_page(relative_path, frontmatter, body)
        self.page_store.write_rendered(rendered)
        return CompileResult(1, 0, 0, [])

    def compile_paper(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        source = self.registry.get_source(source_id)
        if not source:
            return CompileResult(0, 0, 0, [f"Source not found: {source_id}"])
        if source.source_type != "paper":
            return CompileResult(0, 0, 1, [])
        slug = stable_slug(source.title)
        relative_path = Path(f"papers/{slug}.md")
        frontmatter = {
            "id": f"paper-{source.source_id}",
            "kind": WikiPageKind.paper.value,
            "title": source.title,
            "status": WikiPageStatus.draft.value,
            "source_id": source.source_id,
        }
        body = f"# {source.title}\n\nDraft paper page for [[sources/{slug}]].\n"
        if dry_run:
            return CompileResult(1, 0, 0, [])
        rendered = render_page(relative_path, frontmatter, body)
        self.page_store.write_rendered(rendered)
        return CompileResult(1, 0, 0, [])

    def compile_project(
        self,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        sources = self.registry.list_sources()
        created = 0
        updated = 0
        skipped = 0
        errors: list[str] = []
        for source in sources:
            result = self.compile_source(source.source_id, dry_run=dry_run)
            created += result.created
            updated += result.updated
            skipped += result.skipped
            errors.extend(result.errors)
        for source in sources:
            if source.source_type == "paper":
                result = self.compile_paper(source.source_id, dry_run=dry_run)
                created += result.created
                updated += result.updated
                skipped += result.skipped
                errors.extend(result.errors)
        return CompileResult(created, updated, skipped, errors)

    def plan_compile(self) -> CompilePlan:
        sources = self.registry.list_sources()
        to_create: list[Path] = []
        to_update: list[Path] = []
        to_skip: list[Path] = []
        for source in sources:
            slug = stable_slug(source.title)
            source_path = Path(f"sources/{slug}.md")
            if self.page_store.read_page(source_path):
                to_update.append(source_path)
            else:
                to_create.append(source_path)
            if source.source_type == "paper":
                paper_path = Path(f"papers/{slug}.md")
                if self.page_store.read_page(paper_path):
                    to_skip.append(paper_path)
                else:
                    to_create.append(paper_path)
        return CompilePlan(to_create, to_update, to_skip)
