"""Wiki service layer for page CRUD operations (G14 2026-05-26).

Provides high-level operations on WikiPage objects backed by WikiPageStore.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from literature_assistant.core.wiki.models import WikiPage, WikiPageKind, WikiPageStatus, make_stable_slug
from literature_assistant.core.wiki.page_store import (
    PageRevisionConflictError,
    WikiPageStore,
    render_frontmatter,
    render_page,
)
from literature_assistant.core.wiki.permissions import (
    DEFAULT_WIKI_OWNER,
    PERMISSIONS_KEY,
    WikiPagePermissions,
    set_permissions,
)


WIKI_RETENTION_METADATA_KEY = "wiki_retention"
WIKI_RETENTION_SCHEMA_VERSION = "scholar-ai-wiki-retention/v1"


_VERSION_LOCKS_GUARD = RLock()
_VERSION_LOCKS: dict[Path, RLock] = {}


def _version_lock(path: Path) -> RLock:
    resolved = path.expanduser().resolve()
    with _VERSION_LOCKS_GUARD:
        lock = _VERSION_LOCKS.get(resolved)
        if lock is None:
            lock = RLock()
            _VERSION_LOCKS[resolved] = lock
        return lock


class WikiService:
    """Service layer for wiki page operations."""

    def __init__(self, page_store: WikiPageStore) -> None:
        self.page_store = page_store

    def get_page(self, slug: str, *, include_archived: bool = False) -> WikiPage | None:
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
                page = self._parse_page(page_path, content, frontmatter)
                if page.status is WikiPageStatus.archived and not include_archived:
                    return None
                return page

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
        self._record_version(updated_page, action="update_extra")

    def list_page_versions(self, slug: str) -> list[dict[str, Any]]:
        """Return metadata snapshots for a wiki page's local version history."""
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("slug cannot be empty")
        path = self._version_history_path(slug.strip())
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        versions = payload.get("versions") if isinstance(payload, dict) else None
        if not isinstance(versions, list):
            return []
        return [dict(item) for item in versions if isinstance(item, dict)]

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
        """Write WikiPage back to its slug-derived store path."""
        # Determine relative path from kind and slug
        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"
        self._write_page_at_path(relative_path, page)

    def _write_page_at_path(
        self,
        relative_path: Path,
        page: WikiPage,
        *,
        expected_current_hash: str | None = None,
    ) -> None:
        """Write a WikiPage to a known relative path without moving it."""
        if not isinstance(relative_path, Path):
            relative_path = Path(relative_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("relative_path must stay inside the wiki root")

        # Build frontmatter from page
        frontmatter = page.to_dict()
        frontmatter.pop("body")  # Body goes in body section, not frontmatter

        # Add 'id' field for backward compatibility with render_frontmatter
        frontmatter["id"] = frontmatter["stable_slug"]

        # Render and write
        rendered = render_page(relative_path, frontmatter, page.body)
        self.page_store.write_rendered(
            rendered,
            allow_overwrite=True,
            expected_current_hash=expected_current_hash,
        )

    def update_page_by_path(
        self,
        page_path: Path,
        *,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        source_hashes: list[str] | None = None,
        extra: dict[str, Any] | None = None,
        action: str = "graph_review_update",
        expected_current_hash: str | None = None,
    ) -> WikiPage:
        """Update one wiki page in place using its relative page-store path.

        Args:
            page_path: Relative markdown path inside the wiki root.
            title: Optional replacement title.
            body: Optional replacement body.
            status: Optional lifecycle status.
            evidence_refs: Optional replacement evidence refs.
            source_hashes: Optional replacement source hashes.
            extra: Optional replacement extra metadata.
            action: Version-history action label.
            expected_current_hash: Optional SHA-256 compare-and-set token for
                the exact rendered page revision read by the caller.

        Returns:
            Updated page snapshot.

        Raises:
            ValueError: If the path is invalid or the page cannot be read.
        """
        if not isinstance(page_path, Path):
            page_path = Path(page_path)
        if page_path.is_absolute() or ".." in page_path.parts:
            raise ValueError("page_path must stay inside the wiki root")
        content = self.page_store.read_page(page_path)
        if content is None:
            raise ValueError(f"Page not found: {page_path.as_posix()}")
        frontmatter, _body = self._split_frontmatter(str(content))
        page = self._parse_page(page_path, str(content), frontmatter)
        updates: dict[str, Any] = {
            "updated_at_iso": datetime.now(timezone.utc).isoformat(),
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
        self._write_page_at_path(
            page_path,
            updated_page,
            expected_current_hash=expected_current_hash,
        )
        self._record_version(updated_page, action=action)
        return updated_page

    def update_page_status_by_path(
        self,
        page_path: Path,
        *,
        expected_page_id: str,
        expected_status: str,
        status: str,
        action: str,
        expected_current_hash: str,
        updated_at_iso: str | None = None,
        operation_id: str | None = None,
    ) -> WikiPage:
        """Update only page frontmatter while preserving the Markdown body bytes.

        Args:
            page_path: Relative Markdown path inside the Wiki root.
            expected_page_id: Stable frontmatter identity observed when the
                review target was created.
            expected_status: Lifecycle status observed by the reviewer.
            status: Replacement lifecycle status.
            action: Version-history action label.
            expected_current_hash: SHA-256 of the exact page text observed by
                the reviewer.
            updated_at_iso: Optional fixed timestamp used by recoverable
                operations to render the same replacement after a restart.
            operation_id: Optional idempotency key for version-history repair.

        Returns:
            Updated page snapshot.

        Raises:
            ValueError: If identity, status, path, or frontmatter is invalid.
            PageRevisionConflictError: If the exact page content changed.

        The body suffix is reused verbatim so status promotion cannot nest
        generated markers or absorb manual content outside those markers.
        """

        if not isinstance(action, str) or not action.strip():
            raise ValueError("action cannot be empty")
        if operation_id is not None and not str(operation_id).strip():
            raise ValueError("operation_id cannot be empty")
        normalized_updated_at = updated_at_iso or datetime.now(timezone.utc).isoformat()
        updated_page, replacement = self.preview_page_status_update_by_path(
            page_path,
            expected_page_id=expected_page_id,
            expected_status=expected_status,
            status=status,
            expected_current_hash=expected_current_hash,
            updated_at_iso=normalized_updated_at,
        )
        self.page_store.replace_text(
            page_path,
            replacement,
            expected_current_hash=expected_current_hash,
        )
        self._record_version(
            updated_page,
            action=action,
            operation_id=operation_id,
            content_hash=self._hash_text(replacement),
        )
        return updated_page

    def preview_page_status_update_by_path(
        self,
        page_path: Path,
        *,
        expected_page_id: str,
        expected_status: str,
        status: str,
        expected_current_hash: str,
        updated_at_iso: str,
    ) -> tuple[WikiPage, str]:
        """Render a deterministic status-only update without writing files.

        Args:
            page_path: Relative Markdown path inside the Wiki root.
            expected_page_id: Stable page identity observed by the reviewer.
            expected_status: Lifecycle status observed by the reviewer.
            status: Replacement lifecycle status.
            expected_current_hash: SHA-256 of the exact current page text.
            updated_at_iso: Fixed timezone-aware timestamp for deterministic
                retry rendering.

        Returns:
            Parsed updated page and the exact replacement Markdown text.
        """

        if not isinstance(page_path, Path):
            page_path = Path(page_path)
        if page_path.is_absolute() or ".." in page_path.parts:
            raise ValueError("page_path must stay inside the wiki root")
        normalized_page_id = str(expected_page_id or "").strip()
        if not normalized_page_id:
            raise ValueError("expected_page_id cannot be empty")
        if any(ord(char) < 32 for char in normalized_page_id):
            raise ValueError("expected_page_id contains control characters")
        normalized_expected_hash = str(expected_current_hash or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized_expected_hash) is None:
            raise ValueError("expected_current_hash must be a SHA-256 hex digest")
        normalized_updated_at = str(updated_at_iso or "").strip()
        try:
            parsed_updated_at = datetime.fromisoformat(normalized_updated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("updated_at_iso must be a valid ISO-8601 timestamp") from exc
        if parsed_updated_at.tzinfo is None or parsed_updated_at.utcoffset() is None:
            raise ValueError("updated_at_iso must include a timezone offset")

        content = self.page_store.read_page(page_path)
        if content is None:
            raise ValueError(f"Page not found: {page_path.as_posix()}")
        original_content = str(content)
        if self._hash_text(original_content) != normalized_expected_hash:
            raise PageRevisionConflictError("wiki page revision changed before status preview")
        frontmatter, raw_body = self._split_frontmatter(original_content)
        if not frontmatter:
            raise ValueError("wiki page must include JSON frontmatter")
        current_page_id = str(frontmatter.get("stable_slug") or frontmatter.get("id") or "").strip()
        if current_page_id != normalized_page_id:
            raise ValueError("wiki page identity changed before status update")
        current_status = str(frontmatter.get("status") or "").strip()
        if current_status != str(expected_status or "").strip():
            raise ValueError("wiki page status changed before status update")

        updated_frontmatter = dict(frontmatter)
        updated_frontmatter["status"] = WikiPageStatus(status).value
        updated_frontmatter["updated_at_iso"] = normalized_updated_at
        replacement = f"{render_frontmatter(updated_frontmatter)}{raw_body}"
        return self._parse_page(page_path, replacement, updated_frontmatter), replacement

    def ensure_page_version_by_path(
        self,
        page_path: Path,
        *,
        expected_page_id: str,
        expected_status: str,
        expected_current_hash: str,
        action: str,
        operation_id: str,
    ) -> WikiPage:
        """Idempotently record a version for an already-applied page update."""

        if not isinstance(page_path, Path):
            page_path = Path(page_path)
        if page_path.is_absolute() or ".." in page_path.parts:
            raise ValueError("page_path must stay inside the wiki root")
        content = self.page_store.read_page(page_path)
        if content is None:
            raise ValueError(f"Page not found: {page_path.as_posix()}")
        rendered = str(content)
        normalized_hash = str(expected_current_hash or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized_hash) is None:
            raise ValueError("expected_current_hash must be a SHA-256 hex digest")
        if self._hash_text(rendered) != normalized_hash:
            raise PageRevisionConflictError("wiki page revision changed before version repair")
        frontmatter, _raw_body = self._split_frontmatter(rendered)
        if not frontmatter:
            raise ValueError("wiki page must include JSON frontmatter")
        current_page_id = str(frontmatter.get("stable_slug") or frontmatter.get("id") or "").strip()
        if current_page_id != str(expected_page_id or "").strip():
            raise ValueError("wiki page identity changed before version repair")
        if str(frontmatter.get("status") or "").strip() != str(expected_status or "").strip():
            raise ValueError("wiki page status changed before version repair")
        page = self._parse_page(page_path, rendered, frontmatter)
        self._record_version(
            page,
            action=action,
            operation_id=operation_id,
            content_hash=normalized_hash,
        )
        return page

    def replace_page_content_by_path(
        self,
        page_path: Path,
        content: str,
        *,
        action: str = "graph_review_undo",
        expected_current_hash: str | None = None,
    ) -> WikiPage:
        """Restore exact rendered Markdown content at a relative wiki path.

        Args:
            page_path: Relative markdown path inside the wiki root.
            content: Full rendered Markdown page content to restore.
            action: Version-history action label.
            expected_current_hash: Optional SHA-256 compare-and-set token for
                the currently stored rendered page.

        Returns:
            Restored page snapshot.
        """
        if not isinstance(page_path, Path):
            page_path = Path(page_path)
        if page_path.is_absolute() or ".." in page_path.parts:
            raise ValueError("page_path must stay inside the wiki root")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content cannot be empty")
        frontmatter, _body = self._split_frontmatter(content)
        if not frontmatter:
            raise ValueError("restored page content must include JSON frontmatter")
        self.page_store.replace_text(
            page_path,
            content,
            expected_current_hash=expected_current_hash,
        )
        restored_page = self._parse_page(page_path, content, frontmatter)
        self._record_version(restored_page, action=action)
        return restored_page

    def _version_history_path(self, slug: str) -> Path:
        safe_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug.strip()).strip("-")
        if not safe_slug:
            raise ValueError("slug cannot be empty")
        return self.page_store.wiki_root / ".versions" / f"{safe_slug}.json"

    def _record_version(
        self,
        page: WikiPage,
        *,
        action: str,
        operation_id: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        if not isinstance(page, WikiPage):
            raise TypeError("page must be a WikiPage")
        if not action.strip():
            raise ValueError("action cannot be empty")
        normalized_operation_id = str(operation_id or "").strip()
        if operation_id is not None and not normalized_operation_id:
            raise ValueError("operation_id cannot be empty")
        normalized_content_hash = str(content_hash or "").strip().lower()
        if content_hash is not None and re.fullmatch(r"[0-9a-f]{64}", normalized_content_hash) is None:
            raise ValueError("content_hash must be a SHA-256 hex digest")
        path = self._version_history_path(page.stable_slug)
        with _version_lock(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            current_versions = self.list_page_versions(page.stable_slug)
            if normalized_operation_id:
                prior = next(
                    (
                        entry
                        for entry in current_versions
                        if str(entry.get("operation_id") or "").strip() == normalized_operation_id
                    ),
                    None,
                )
                if prior is not None:
                    if (
                        str(prior.get("action") or "") != action.strip()
                        or str(prior.get("status") or "") != page.status.value
                        or (
                            normalized_content_hash
                            and str(prior.get("content_hash") or "") != normalized_content_hash
                        )
                    ):
                        raise ValueError("operation_id is already bound to a different wiki version")
                    return
            version_index = len(current_versions) + 1
            entry = {
                "version": version_index,
                "action": action.strip(),
                "stable_slug": page.stable_slug,
                "kind": page.kind.value,
                "status": page.status.value,
                "title": page.title,
                "body_hash": self._hash_text(page.body),
                "created_at_iso": page.created_at_iso,
                "updated_at_iso": page.updated_at_iso,
                "recorded_at_iso": datetime.now(timezone.utc).isoformat(),
            }
            if normalized_operation_id:
                entry["operation_id"] = normalized_operation_id
            if normalized_content_hash:
                entry["content_hash"] = normalized_content_hash
            payload = {
                "schema_version": 1,
                "stable_slug": page.stable_slug,
                "versions": [*current_versions, entry],
            }
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

    @staticmethod
    def _hash_text(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

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
        existing = self.get_page(slug, include_archived=True)
        if existing is not None:
            raise ValueError(f"Page already exists: {slug}")

        now_iso = datetime.now(timezone.utc).isoformat()

        page_extra = dict(extra or {})
        if PERMISSIONS_KEY not in page_extra:
            page_extra = set_permissions(page_extra, WikiPagePermissions.default(DEFAULT_WIKI_OWNER))

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
            extra=page_extra,
        )

        self._write_page(page)
        self._record_version(page, action="create")
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
        self._record_version(updated_page, action="update")
        return updated_page

    def get_page_retention(self, slug: str) -> dict[str, Any] | None:
        """Return the persisted archive/restore receipt and current CAS hash."""

        page = self.get_page(slug, include_archived=True)
        if page is None:
            return None
        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"
        content = self.page_store.read_page(relative_path)
        if content is None:
            return None
        retention = page.extra.get(WIKI_RETENTION_METADATA_KEY)
        if not isinstance(retention, dict):
            return None
        payload = json.loads(json.dumps(retention, ensure_ascii=False))
        payload["current_content_hash"] = self._hash_text(str(content))
        payload["page_path"] = relative_path.as_posix()
        return payload

    def archive_page(
        self,
        slug: str,
        *,
        expected_current_hash: str | None = None,
        archived_by: str | None = None,
    ) -> WikiPage:
        """Persist an archived page tombstone with a strong content CAS check."""

        page = self.get_page(slug, include_archived=True)
        if page is None:
            raise ValueError(f"Page not found: {slug}")
        if page.status is WikiPageStatus.archived:
            raise PageRevisionConflictError("wiki page is already archived")

        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"
        content = self.page_store.read_page(relative_path)
        if content is None:
            raise ValueError(f"Page not found: {slug}")
        current_hash = self._hash_text(str(content))
        normalized_expected = str(expected_current_hash or "").strip().lower()
        if expected_current_hash is not None:
            if re.fullmatch(r"[0-9a-f]{64}", normalized_expected) is None:
                raise ValueError("expected_current_hash must be a SHA-256 hex digest")
            if normalized_expected != current_hash:
                raise PageRevisionConflictError("wiki page revision changed before archive")

        archived_at = datetime.now(timezone.utc).isoformat()
        archive_receipt = {
            "receipt_id": f"wiki_archive_{os.urandom(8).hex()}",
            "operation": "archive",
            "stable_slug": page.stable_slug,
            "page_path": relative_path.as_posix(),
            "previous_status": page.status.value,
            "before_content_hash": current_hash,
            "archived_at": archived_at,
            "archived_by": str(archived_by or DEFAULT_WIKI_OWNER).strip() or DEFAULT_WIKI_OWNER,
        }
        prior_raw = page.extra.get(WIKI_RETENTION_METADATA_KEY)
        retention = dict(prior_raw) if isinstance(prior_raw, dict) else {}
        history_raw = retention.get("receipt_history")
        history = [dict(item) for item in history_raw if isinstance(item, dict)] if isinstance(history_raw, list) else []
        retention.update(
            {
                "schema_version": WIKI_RETENTION_SCHEMA_VERSION,
                "state": WikiPageStatus.archived.value,
                "archive_receipt": archive_receipt,
                "receipt_history": [*history, archive_receipt],
            }
        )
        archived = page.evolve(
            status=WikiPageStatus.archived,
            updated_at_iso=archived_at,
            extra={**page.extra, WIKI_RETENTION_METADATA_KEY: retention},
        )
        self._write_page_at_path(relative_path, archived, expected_current_hash=current_hash)
        rendered = self.page_store.read_page(relative_path)
        self._record_version(
            archived,
            action="archive",
            content_hash=self._hash_text(str(rendered)) if rendered is not None else None,
        )
        return archived

    def restore_page(
        self,
        slug: str,
        *,
        expected_archive_receipt_id: str,
        expected_current_hash: str,
        restored_by: str | None = None,
    ) -> WikiPage:
        """Restore an archived page only when receipt and content CAS match."""

        receipt_id = str(expected_archive_receipt_id or "").strip()
        if not receipt_id:
            raise ValueError("expected_archive_receipt_id cannot be empty")
        normalized_expected = str(expected_current_hash or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized_expected) is None:
            raise ValueError("expected_current_hash must be a SHA-256 hex digest")
        page = self.get_page(slug, include_archived=True)
        if page is None:
            raise ValueError(f"Page not found: {slug}")
        if page.status is not WikiPageStatus.archived:
            raise PageRevisionConflictError("wiki page is not archived")
        retention_raw = page.extra.get(WIKI_RETENTION_METADATA_KEY)
        retention = dict(retention_raw) if isinstance(retention_raw, dict) else {}
        archive_raw = retention.get("archive_receipt")
        archive_receipt = dict(archive_raw) if isinstance(archive_raw, dict) else {}
        if str(archive_receipt.get("receipt_id") or "") != receipt_id:
            raise PageRevisionConflictError("wiki page archive receipt changed before restore")

        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"
        content = self.page_store.read_page(relative_path)
        if content is None:
            raise ValueError(f"Page not found: {slug}")
        current_hash = self._hash_text(str(content))
        if current_hash != normalized_expected:
            raise PageRevisionConflictError("wiki page revision changed before restore")

        previous_status_raw = str(archive_receipt.get("previous_status") or WikiPageStatus.draft.value)
        try:
            previous_status = WikiPageStatus(previous_status_raw)
        except ValueError:
            previous_status = WikiPageStatus.draft
        if previous_status is WikiPageStatus.archived:
            previous_status = WikiPageStatus.draft
        restored_at = datetime.now(timezone.utc).isoformat()
        restore_receipt = {
            "receipt_id": f"wiki_restore_{os.urandom(8).hex()}",
            "operation": "restore",
            "stable_slug": page.stable_slug,
            "archive_receipt_id": receipt_id,
            "restored_at": restored_at,
            "restored_by": str(restored_by or DEFAULT_WIKI_OWNER).strip() or DEFAULT_WIKI_OWNER,
            "expected_current_hash": current_hash,
        }
        history_raw = retention.get("receipt_history")
        history = [dict(item) for item in history_raw if isinstance(item, dict)] if isinstance(history_raw, list) else []
        retention.update({"state": "active", "restore_receipt": restore_receipt, "receipt_history": [*history, restore_receipt]})
        restored = page.evolve(
            status=previous_status,
            updated_at_iso=restored_at,
            extra={**page.extra, WIKI_RETENTION_METADATA_KEY: retention},
        )
        self._write_page_at_path(relative_path, restored, expected_current_hash=current_hash)
        rendered = self.page_store.read_page(relative_path)
        self._record_version(
            restored,
            action="restore",
            content_hash=self._hash_text(str(rendered)) if rendered is not None else None,
        )
        return restored

    def purge_page(self, slug: str) -> None:
        """Physically remove a page for explicit same-transaction rollback only."""

        page = self.get_page(slug, include_archived=True)
        if page is None:
            raise ValueError(f"Page not found: {slug}")
        relative_path = Path(page.kind.value) / f"{page.stable_slug}.md"
        full_path = self.page_store.resolve(relative_path)
        if full_path.exists():
            full_path.unlink()
        self._record_version(page, action="purge")

    def delete_page(
        self,
        slug: str,
        *,
        expected_current_hash: str | None = None,
        archived_by: str | None = None,
    ) -> WikiPage:
        """Archive a wiki page; retained as the ordinary-delete compatibility alias.

        Args:
            slug: Page slug

        Raises:
            ValueError: If page not found
        """
        return self.archive_page(
            slug,
            expected_current_hash=expected_current_hash,
            archived_by=archived_by,
        )


def get_wiki_service() -> WikiService:
    """Get singleton wiki service instance."""
    from literature_assistant.core.project_paths import wiki_generated_root

    page_store = WikiPageStore(wiki_generated_root(), create=False)
    return WikiService(page_store)
