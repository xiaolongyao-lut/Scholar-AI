"""Wiki service layer for page CRUD operations (G14 2026-05-26).

Provides high-level operations on WikiPage objects backed by WikiPageStore.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki.models import WikiPage, WikiPageKind, WikiPageStatus, make_stable_slug
from wiki.page_store import WikiPageStore


class WikiService:
    """Service layer for wiki page operations."""

    def __init__(self, page_store: WikiPageStore) -> None:
        self.page_store = page_store

    def get_page(self, slug: str) -> WikiPage | None:
        """Get a wiki page by slug.

        Args:
            slug: Page slug (e.g., "synthesis-my-topic")

        Returns:
            WikiPage instance or None if not found.
        """
        # Find page by slug in all kind directories
        for page_path in self.page_store.list_pages():
            content = self.page_store.read_page(page_path)
            if not content:
                continue

            # Parse frontmatter to get slug
            frontmatter, _ = self._split_frontmatter(content)
            if frontmatter.get("stable_slug") == slug or frontmatter.get("id") == slug:
                return self._parse_page(page_path, content, frontmatter)

        return None

    def update_page_extra(self, slug: str, new_extra: dict[str, Any]) -> None:
        """Update the extra field of a wiki page.

        Args:
            slug: Page slug
            new_extra: New extra dict to store

        Raises:
            ValueError: If page not found
        """
        page = self.get_page(slug)
        if page is None:
            raise ValueError(f"Page not found: {slug}")

        # Update page with new extra
        updated_page = page.evolve(extra=new_extra)

        # Write back to store
        self._write_page(updated_page)

    def _split_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """Split frontmatter and body from page content."""
        lines = content.split("\n")
        if not lines or not lines[0].startswith("---"):
            return {}, content

        frontmatter_lines = []
        for index, line in enumerate(lines[1:], start=1):
            if line.startswith("---"):
                # Parse frontmatter
                frontmatter_text = "\n".join(frontmatter_lines)
                try:
                    if lines[0] == "---json":
                        frontmatter = json.loads(frontmatter_text)
                    else:
                        # YAML-style frontmatter (not implemented, return empty)
                        frontmatter = {}
                except json.JSONDecodeError:
                    frontmatter = {}
                return frontmatter, "\n".join(lines[index + 1 :])
            frontmatter_lines.append(line)
        return {}, content

    def _parse_page(self, page_path: Path, content: str, frontmatter: dict[str, Any]) -> WikiPage:
        """Parse WikiPage from content and frontmatter."""
        from wiki.models import WikiPageKind, WikiPageStatus

        _, body = self._split_frontmatter(content)

        return WikiPage(
            stable_slug=frontmatter.get("stable_slug", frontmatter.get("id", "")),
            kind=WikiPageKind(frontmatter.get("kind", "synthesis")),
            status=WikiPageStatus(frontmatter.get("status", "draft")),
            title=frontmatter.get("title", ""),
            body=body.strip(),
            evidence_refs=tuple(frontmatter.get("evidence_refs", [])),
            source_hashes=tuple(frontmatter.get("source_hashes", [])),
            created_at_iso=frontmatter.get("created_at_iso", ""),
            updated_at_iso=frontmatter.get("updated_at_iso", ""),
            schema_version=int(frontmatter.get("schema_version", 1)),
            extra=dict(frontmatter.get("extra", {})),
        )

    def _write_page(self, page: WikiPage) -> None:
        """Write WikiPage back to store."""
        from wiki.page_store import render_page

        # Determine relative path from kind and slug
        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"

        # Build frontmatter from page
        frontmatter = page.to_dict()
        frontmatter.pop("body")  # Body goes in body section, not frontmatter

        # Add 'id' field for backward compatibility with render_frontmatter
        frontmatter["id"] = frontmatter["stable_slug"]

        # Render and write
        rendered = render_page(relative_path, frontmatter, page.body)
        self.page_store.write_rendered(rendered, allow_overwrite=True)

    def create_page(
        self,
        title: str,
        kind: str,
        body: str,
        status: str = "draft",
        evidence_refs: list[dict[str, Any]] | None = None,
        source_hashes: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> WikiPage:
        """Create a new wiki page (G2 2026-05-26).

        Args:
            title: Page title
            kind: Page kind (synthesis/concept/paper/etc)
            body: Page body content
            status: Page status (default: draft)
            evidence_refs: Evidence references
            source_hashes: Source hashes
            extra: Extra metadata

        Returns:
            Created WikiPage instance

        Raises:
            ValueError: If page with same slug already exists
        """
        kind_enum = WikiPageKind(kind)
        status_enum = WikiPageStatus(status)
        slug = make_stable_slug(title, kind_enum)

        # Check if page already exists
        existing = self.get_page(slug)
        if existing is not None:
            raise ValueError(f"Page already exists: {slug}")

        now_iso = datetime.now(timezone.utc).isoformat()

        page = WikiPage(
            stable_slug=slug,
            kind=kind_enum,
            status=status_enum,
            title=title,
            body=body,
            evidence_refs=tuple(evidence_refs or []),
            source_hashes=tuple(source_hashes or []),
            created_at_iso=now_iso,
            updated_at_iso=now_iso,
            schema_version=1,
            extra=extra or {},
        )

        self._write_page(page)
        return page

    def update_page(
        self,
        slug: str,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        source_hashes: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> WikiPage:
        """Update an existing wiki page (G2 2026-05-26).

        Args:
            slug: Page slug
            title: New title (optional)
            body: New body (optional)
            status: New status (optional)
            evidence_refs: New evidence refs (optional)
            source_hashes: New source hashes (optional)
            extra: New extra metadata (optional)

        Returns:
            Updated WikiPage instance

        Raises:
            ValueError: If page not found
        """
        page = self.get_page(slug)
        if page is None:
            raise ValueError(f"Page not found: {slug}")

        updates: dict[str, Any] = {
            "updated_at_iso": datetime.now(timezone.utc).isoformat()
        }

        if title is not None:
            updates["title"] = title
        if body is not None:
            updates["body"] = body
        if status is not None:
            updates["status"] = WikiPageStatus(status)
        if evidence_refs is not None:
            updates["evidence_refs"] = tuple(evidence_refs)
        if source_hashes is not None:
            updates["source_hashes"] = tuple(source_hashes)
        if extra is not None:
            updates["extra"] = extra

        updated_page = page.evolve(**updates)
        self._write_page(updated_page)
        return updated_page

    def delete_page(self, slug: str) -> None:
        """Delete a wiki page (G2 2026-05-26).

        Args:
            slug: Page slug

        Raises:
            ValueError: If page not found
        """
        page = self.get_page(slug)
        if page is None:
            raise ValueError(f"Page not found: {slug}")

        # Determine file path
        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"
        full_path = self.page_store.resolve(relative_path)

        # Delete file
        if full_path.exists():
            full_path.unlink()


def get_wiki_service() -> WikiService:
    """Get singleton wiki service instance."""
    from literature_assistant.core.runtime_env import wiki_generated_root

    page_store = WikiPageStore(wiki_generated_root(), create=False)
    return WikiService(page_store)
