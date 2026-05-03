from __future__ import annotations

import json
from pathlib import Path

import pytest

from literature_assistant.core.wiki.page_store import (
    AUTO_END,
    AUTO_START,
    RenderedPage,
    WikiPageStore,
    atomic_write_text,
    render_frontmatter,
    render_page,
    stable_slug,
)


class TestStableSlug:
    def test_basic(self) -> None:
        result = stable_slug("Test Title")
        assert result == "test-title"

    def test_deterministic(self) -> None:
        assert stable_slug("Same Title") == stable_slug("Same Title")

    def test_normalizes_whitespace(self) -> None:
        assert stable_slug("  Multiple   Spaces  ") == "multiple-spaces"

    def test_replaces_special_chars(self) -> None:
        result = stable_slug("Test / Paper: 2024")
        assert result == "test-paper-2024"
        assert "/" not in result
        assert ":" not in result

    def test_collapses_consecutive_dashes(self) -> None:
        result = stable_slug("Test---Title")
        assert result == "test-title"

    def test_truncates_long_titles(self) -> None:
        long_title = "a" * 200
        result = stable_slug(long_title)
        assert len(result) <= 96

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            stable_slug("")

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a string"):
            stable_slug(123)  # type: ignore

    def test_fallback_hash_for_non_alnum(self) -> None:
        result = stable_slug("///")
        assert len(result) == 16
        assert result.isalnum()


class TestRenderFrontmatter:
    def test_basic(self) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        result = render_frontmatter(fm)
        assert result.startswith("---json\n")
        assert result.endswith("\n---\n")
        payload = result[8:-5]
        parsed = json.loads(payload)
        assert parsed["id"] == "test-id"
        assert parsed["kind"] == "paper"

    def test_sorted_keys(self) -> None:
        fm = {"title": "Test", "id": "test-id", "kind": "paper"}
        result = render_frontmatter(fm)
        payload = result[8:-5]
        parsed = json.loads(payload)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_missing_id_raises(self) -> None:
        fm = {"kind": "paper", "title": "Test"}
        with pytest.raises(ValueError, match="requires id, kind, and title"):
            render_frontmatter(fm)

    def test_missing_kind_raises(self) -> None:
        fm = {"id": "test-id", "title": "Test"}
        with pytest.raises(ValueError, match="requires id, kind, and title"):
            render_frontmatter(fm)

    def test_missing_title_raises(self) -> None:
        fm = {"id": "test-id", "kind": "paper"}
        with pytest.raises(ValueError, match="requires id, kind, and title"):
            render_frontmatter(fm)

    def test_non_mapping_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a mapping"):
            render_frontmatter("not a dict")  # type: ignore


class TestRenderPage:
    def test_basic(self) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        body = "This is the body."
        result = render_page(Path("test.md"), fm, body)
        assert isinstance(result, RenderedPage)
        assert result.relative_path == Path("test.md")
        assert AUTO_START in result.text
        assert AUTO_END in result.text
        assert "This is the body." in result.text
        assert len(result.content_hash) == 64

    def test_strips_body_whitespace(self) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        body = "\n\n  Body text  \n\n"
        result = render_page(Path("test.md"), fm, body)
        assert result.text.count("Body text") == 1
        assert "  Body text  " not in result.text

    def test_absolute_path_raises(self, tmp_path: Path) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        absolute = tmp_path / "test.md"
        with pytest.raises(ValueError, match="stay inside the wiki root"):
            render_page(absolute, fm, "body")

    def test_parent_traversal_raises(self) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        with pytest.raises(ValueError, match="stay inside the wiki root"):
            render_page(Path("../escape.md"), fm, "body")

    def test_empty_body_raises(self) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        with pytest.raises(ValueError, match="body cannot be empty"):
            render_page(Path("test.md"), fm, "")

    def test_whitespace_only_body_raises(self) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        with pytest.raises(ValueError, match="body cannot be empty"):
            render_page(Path("test.md"), fm, "   \n\n  ")


class TestAtomicWriteText:
    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        atomic_write_text(target, "content")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "content"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "nested" / "file.txt"
        atomic_write_text(target, "content")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_temp_file_left_behind(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        atomic_write_text(target, "content")
        temp_files = list(tmp_path.glob(".test.txt.*.tmp"))
        assert len(temp_files) == 0

    def test_non_string_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        with pytest.raises(TypeError, match="must be a string"):
            atomic_write_text(target, 123)  # type: ignore


class TestWikiPageStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> WikiPageStore:
        wiki_root = tmp_path / "wiki"
        return WikiPageStore(wiki_root)

    def test_creates_wiki_root(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        store = WikiPageStore(wiki_root)
        assert wiki_root.exists()
        assert wiki_root.is_dir()

    def test_resolve_valid_path(self, store: WikiPageStore) -> None:
        result = store.resolve(Path("papers/test.md"))
        assert result.is_absolute()
        assert store.wiki_root in result.parents

    def test_resolve_rejects_absolute(self, store: WikiPageStore) -> None:
        with pytest.raises(ValueError, match="escapes wiki root"):
            store.resolve(Path("/absolute/path.md"))

    def test_resolve_rejects_parent_traversal(self, store: WikiPageStore) -> None:
        with pytest.raises(ValueError, match="escapes wiki root"):
            store.resolve(Path("../escape.md"))

    def test_write_rendered_creates_new(self, store: WikiPageStore) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        rendered = render_page(Path("test.md"), fm, "Body text")
        store.write_rendered(rendered)
        target = store.wiki_root / "test.md"
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "Body text" in content
        assert AUTO_START in content

    def test_write_rendered_overwrites_auto_page(self, store: WikiPageStore) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        rendered1 = render_page(Path("test.md"), fm, "Old body")
        store.write_rendered(rendered1)
        rendered2 = render_page(Path("test.md"), fm, "New body")
        store.write_rendered(rendered2)
        target = store.wiki_root / "test.md"
        content = target.read_text(encoding="utf-8")
        assert "New body" in content
        assert "Old body" not in content

    def test_write_rendered_rejects_manual_page(self, store: WikiPageStore) -> None:
        target = store.wiki_root / "manual.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Manual content without auto marker", encoding="utf-8")
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        rendered = render_page(Path("manual.md"), fm, "Auto body")
        with pytest.raises(ValueError, match="manual page lacks auto marker"):
            store.write_rendered(rendered)

    def test_write_rendered_respects_allow_overwrite(self, store: WikiPageStore) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        rendered1 = render_page(Path("test.md"), fm, "First")
        store.write_rendered(rendered1)
        rendered2 = render_page(Path("test.md"), fm, "Second")
        with pytest.raises(FileExistsError):
            store.write_rendered(rendered2, allow_overwrite=False)

    def test_read_page_returns_content(self, store: WikiPageStore) -> None:
        fm = {"id": "test-id", "kind": "paper", "title": "Test"}
        rendered = render_page(Path("test.md"), fm, "Body text")
        store.write_rendered(rendered)
        content = store.read_page(Path("test.md"))
        assert content is not None
        assert "Body text" in content

    def test_read_page_returns_none_when_not_found(self, store: WikiPageStore) -> None:
        result = store.read_page(Path("nonexistent.md"))
        assert result is None

    def test_list_pages_empty(self, store: WikiPageStore) -> None:
        result = store.list_pages()
        assert result == []

    def test_list_pages_returns_all(self, store: WikiPageStore) -> None:
        fm1 = {"id": "id1", "kind": "paper", "title": "Paper 1"}
        fm2 = {"id": "id2", "kind": "paper", "title": "Paper 2"}
        rendered1 = render_page(Path("papers/p1.md"), fm1, "Body 1")
        rendered2 = render_page(Path("papers/p2.md"), fm2, "Body 2")
        store.write_rendered(rendered1)
        store.write_rendered(rendered2)
        result = store.list_pages()
        assert len(result) == 2
        assert Path("papers/p1.md") in result
        assert Path("papers/p2.md") in result

    def test_list_pages_filters_by_kind_dir(self, store: WikiPageStore) -> None:
        fm1 = {"id": "id1", "kind": "paper", "title": "Paper"}
        fm2 = {"id": "id2", "kind": "concept", "title": "Concept"}
        rendered1 = render_page(Path("papers/p1.md"), fm1, "Body 1")
        rendered2 = render_page(Path("concepts/c1.md"), fm2, "Body 2")
        store.write_rendered(rendered1)
        store.write_rendered(rendered2)
        result = store.list_pages(kind_dir="papers")
        assert len(result) == 1
        assert Path("papers/p1.md") in result
