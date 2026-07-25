from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping


AUTO_START = "<!-- literature-assistant:auto:start -->"
AUTO_END = "<!-- literature-assistant:auto:end -->"
GENERATED_BASE_PREFIX = "<!-- literature-assistant:generated-base-sha256:"
_GENERATED_BASE_PATTERN = re.compile(
    rf"^{re.escape(GENERATED_BASE_PREFIX)}([0-9a-f]{{64}}) -->\n",
    re.MULTILINE,
)
_PAGE_LOCKS_GUARD = RLock()
_PAGE_LOCKS: dict[Path, RLock] = {}


class PageRevisionConflictError(ValueError):
    """Raised when a page compare-and-set precondition no longer matches."""


def _page_lock(path: Path) -> RLock:
    resolved = path.expanduser().resolve()
    with _PAGE_LOCKS_GUARD:
        lock = _PAGE_LOCKS.get(resolved)
        if lock is None:
            lock = RLock()
            _PAGE_LOCKS[resolved] = lock
        return lock


@dataclass(frozen=True)
class RenderedPage:
    relative_path: Path
    text: str
    content_hash: str

    @property
    def body(self) -> str:
        """Return the rendered Markdown body for legacy review tests."""

        return self.text


class PageText(str):
    """String page payload with a legacy `.body` alias."""

    @property
    def body(self) -> str:
        return str(self)


def stable_slug(title: str) -> str:
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    value = title.strip().lower()
    if not value:
        raise ValueError("title cannot be empty")
    chars: list[str] = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_", ".", "/"}:
            chars.append("-")
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug[:96] or hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]


def render_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    if not isinstance(frontmatter, Mapping):
        raise TypeError("frontmatter must be a mapping")
    if "id" not in frontmatter or "kind" not in frontmatter or "title" not in frontmatter:
        raise ValueError("frontmatter requires id, kind, and title")
    payload = json.dumps(dict(sorted(frontmatter.items())), ensure_ascii=False, indent=2)
    return f"---json\n{payload}\n---\n"


def render_page(relative_path: Path, frontmatter: Mapping[str, Any], body: str) -> RenderedPage:
    if not isinstance(relative_path, Path):
        relative_path = Path(relative_path)
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body cannot be empty")
    if relative_path.is_absolute():
        raise ValueError("relative_path must stay inside the wiki root")
    if ".." in relative_path.parts:
        raise ValueError("relative_path must stay inside the wiki root")
    text = f"{render_frontmatter(frontmatter)}\n{AUTO_START}\n{body.strip()}\n{AUTO_END}\n"
    return RenderedPage(
        relative_path=relative_path,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def render_generated_page(
    relative_path: Path,
    frontmatter: Mapping[str, Any],
    body: str,
) -> RenderedPage:
    """Render a compiler-owned page with an in-band last-generated baseline.

    The baseline hashes the exact page text with only the baseline marker
    removed. Keeping the marker in the same atomic file lets later compiles
    detect any intervening manual edit without a second sidecar transaction.
    """

    rendered = render_page(relative_path, frontmatter, body)
    frontmatter_end = rendered.text.find("---\n")
    if frontmatter_end < 0:
        raise ValueError("rendered page is missing its frontmatter terminator")
    insert_at = frontmatter_end + len("---\n")
    baseline_hash = hashlib.sha256(rendered.text.encode("utf-8")).hexdigest()
    marker = f"{GENERATED_BASE_PREFIX}{baseline_hash} -->\n"
    text = f"{rendered.text[:insert_at]}{marker}{rendered.text[insert_at:]}"
    return RenderedPage(
        relative_path=rendered.relative_path,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _generated_page_matches_baseline(text: str) -> bool | None:
    """Return baseline validity, or ``None`` when no unique marker exists."""

    matches = tuple(_GENERATED_BASE_PATTERN.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    without_marker = f"{text[:match.start()]}{text[match.end():]}"
    actual_hash = hashlib.sha256(without_marker.encode("utf-8")).hexdigest()
    return actual_hash == match.group(1)


def atomic_write_text(path: Path, text: str) -> None:
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    with _page_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


class WikiPageStore:
    def __init__(self, wiki_root: Path, *, create: bool = True) -> None:
        """Create a page store rooted at ``wiki_root``.

        Args:
            wiki_root: Directory that contains generated Wiki Markdown pages.
            create: When false, read-only callers must not create missing
                directories just by constructing the store.
        """

        self.wiki_root = Path(wiki_root)
        if create:
            self.wiki_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: Path) -> Path:
        candidate = (self.wiki_root / relative_path).resolve()
        root = self.wiki_root.resolve()
        if root not in {candidate, *candidate.parents}:
            raise ValueError(f"path escapes wiki root: {relative_path}")
        return candidate

    def write_rendered(
        self,
        rendered: RenderedPage,
        *,
        allow_overwrite: bool = True,
        expected_current_hash: str | None = None,
    ) -> None:
        """Write a rendered page, optionally using a full-content hash CAS.

        Args:
            rendered: Fully rendered Markdown page.
            allow_overwrite: Whether an existing generated page may be replaced.
            expected_current_hash: SHA-256 of the exact UTF-8 page text the
                caller read. A mismatch raises before any write.

        Raises:
            PageRevisionConflictError: If the expected revision drifted.
        """

        target = self.resolve(rendered.relative_path)
        normalized_expected = _normalize_optional_sha256(expected_current_hash)
        with _page_lock(target):
            rendered_hash = hashlib.sha256(rendered.text.encode("utf-8")).hexdigest()
            if rendered_hash != rendered.content_hash:
                raise ValueError("rendered page content_hash does not match its text")
            incoming_baseline = _generated_page_matches_baseline(rendered.text)
            if incoming_baseline is False:
                raise ValueError("generated page baseline does not match rendered text")
            if target.exists() and not allow_overwrite:
                raise FileExistsError(target)
            old_text = target.read_text(encoding="utf-8") if target.exists() else ""
            if normalized_expected is not None:
                current_hash = hashlib.sha256(old_text.encode("utf-8")).hexdigest()
                if current_hash != normalized_expected:
                    raise PageRevisionConflictError("wiki page revision changed before write")
            if old_text and AUTO_START not in old_text:
                raise ValueError(f"manual page lacks auto marker and will not be overwritten: {target}")
            if old_text and incoming_baseline is not None:
                current_baseline = _generated_page_matches_baseline(old_text)
                if current_baseline is None:
                    raise PageRevisionConflictError(
                        "existing wiki page has no trusted generated baseline"
                    )
                if current_baseline is False:
                    raise PageRevisionConflictError(
                        "wiki page contains manual edits since its last compile"
                    )
            atomic_write_text(target, rendered.text)

    def read_page(self, relative_path: Path) -> str | None:
        try:
            target = self.resolve(relative_path)
            if not target.exists():
                return None
            return PageText(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def replace_text(
        self,
        relative_path: Path,
        text: str,
        *,
        expected_current_hash: str | None = None,
    ) -> None:
        """Replace exact page text with an optional current-revision CAS."""

        if not isinstance(text, str) or not text.strip():
            raise ValueError("text cannot be empty")
        target = self.resolve(relative_path)
        normalized_expected = _normalize_optional_sha256(expected_current_hash)
        with _page_lock(target):
            if not target.exists():
                raise FileNotFoundError(target)
            current_text = target.read_text(encoding="utf-8")
            if normalized_expected is not None:
                current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
                if current_hash != normalized_expected:
                    raise PageRevisionConflictError("wiki page revision changed before replace")
            atomic_write_text(target, text)

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        base = self.wiki_root / kind_dir if kind_dir else self.wiki_root
        if not base.exists():
            return []
        return sorted(path.relative_to(self.wiki_root) for path in base.rglob("*.md"))


def _normalize_optional_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("expected_current_hash must be a string")
    normalized = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError("expected_current_hash must be a SHA-256 hex digest")
    return normalized
