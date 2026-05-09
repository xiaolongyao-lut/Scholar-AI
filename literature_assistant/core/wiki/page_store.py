from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


AUTO_START = "<!-- literature-assistant:auto:start -->"
AUTO_END = "<!-- literature-assistant:auto:end -->"


@dataclass(frozen=True)
class RenderedPage:
    relative_path: Path
    text: str
    content_hash: str


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


def atomic_write_text(path: Path, text: str) -> None:
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(text, str):
        raise TypeError("text must be a string")
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

    def write_rendered(self, rendered: RenderedPage, *, allow_overwrite: bool = True) -> None:
        target = self.resolve(rendered.relative_path)
        if target.exists() and not allow_overwrite:
            raise FileExistsError(target)
        old_text = target.read_text(encoding="utf-8") if target.exists() else ""
        if old_text and AUTO_START not in old_text:
            raise ValueError(f"manual page lacks auto marker and will not be overwritten: {target}")
        atomic_write_text(target, rendered.text)

    def read_page(self, relative_path: Path) -> str | None:
        try:
            target = self.resolve(relative_path)
            if not target.exists():
                return None
            return target.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        base = self.wiki_root / kind_dir if kind_dir else self.wiki_root
        if not base.exists():
            return []
        return sorted(path.relative_to(self.wiki_root) for path in base.rglob("*.md"))
