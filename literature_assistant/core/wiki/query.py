from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from literature_assistant.core.wiki.page_store import WikiPageStore


@dataclass(frozen=True)
class WikiRetrievalStatus:
    index_hash: str
    page_count: int
    stale: bool
    last_indexed: str


@dataclass(frozen=True)
class WikiSearchResult:
    page_path: Path
    title: str
    score: float
    snippet: str


class WikiQueryIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def initialize(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_pages_fts
            USING fts5(page_path, title, body, tokenize='unicode61')
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wiki_index_status (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    def index_page(self, page_path: Path, title: str, body: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO wiki_pages_fts (page_path, title, body) VALUES (?, ?, ?)",
            (str(page_path), title, body),
        )
        conn.commit()

    def search(self, query: str, limit: int = 10) -> list[WikiSearchResult]:
        if not query or not query.strip():
            return []
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT page_path, title, snippet(wiki_pages_fts, 2, '<b>', '</b>', '...', 64) as snippet, rank
            FROM wiki_pages_fts
            WHERE wiki_pages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        results: list[WikiSearchResult] = []
        for row in cursor:
            results.append(
                WikiSearchResult(
                    page_path=Path(row["page_path"]),
                    title=row["title"],
                    score=-row["rank"],
                    snippet=row["snippet"],
                )
            )
        return results

    def get_status(self) -> WikiRetrievalStatus:
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) as count FROM wiki_pages_fts")
        page_count = cursor.fetchone()["count"]
        cursor = conn.execute("SELECT value FROM wiki_index_status WHERE key = 'index_hash'")
        row = cursor.fetchone()
        index_hash = row["value"] if row else "none"
        cursor = conn.execute("SELECT value FROM wiki_index_status WHERE key = 'last_indexed'")
        row = cursor.fetchone()
        last_indexed = row["value"] if row else "never"
        return WikiRetrievalStatus(
            index_hash=index_hash,
            page_count=page_count,
            stale=False,
            last_indexed=last_indexed,
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def build_wiki_index(page_store: WikiPageStore, index: WikiQueryIndex) -> None:
    import json

    index.initialize()
    pages = page_store.list_pages()
    for page_path in pages:
        content = page_store.read_page(page_path)
        if content:
            lines = content.split("\n")
            title = "Untitled"
            body_start = 0
            in_frontmatter = False
            frontmatter_lines: list[str] = []
            for i, line in enumerate(lines):
                if i == 0 and line.strip() == "---json":
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    if line.strip() == "---":
                        in_frontmatter = False
                        body_start = i + 1
                        try:
                            fm = json.loads("\n".join(frontmatter_lines))
                            if "title" in fm:
                                title = fm["title"]
                        except json.JSONDecodeError:
                            pass
                        continue
                    frontmatter_lines.append(line)
                if not in_frontmatter and line.startswith("# "):
                    if title == "Untitled":
                        title = line[2:].strip()
                    body_start = i + 1
                    break
            body = "\n".join(lines[body_start:])
            index.index_page(page_path, title, body)


def wiki_first_search(
    query: str,
    index: WikiQueryIndex,
    *,
    enabled: bool = False,
    limit: int = 5,
) -> tuple[list[WikiSearchResult], bool]:
    if not enabled:
        return [], False
    results = index.search(query, limit=limit)
    return results, len(results) > 0


def expand_linked_pages(
    primary_results: list[WikiSearchResult],
    page_store: WikiPageStore,
    *,
    max_linked: int = 3,
) -> list[WikiSearchResult]:
    import json
    import re

    linked_pages: dict[Path, float] = {}
    for result in primary_results:
        content = page_store.read_page(result.page_path)
        if not content:
            continue
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        for link in wikilinks:
            link_path = Path(link.strip())
            if link_path not in linked_pages:
                linked_pages[link_path] = 0.0
            linked_pages[link_path] += result.score * 0.5

    sorted_linked = sorted(linked_pages.items(), key=lambda x: x[1], reverse=True)
    expanded: list[WikiSearchResult] = []
    for link_path, score in sorted_linked[:max_linked]:
        content = page_store.read_page(link_path)
        if content:
            lines = content.split("\n")
            title = "Untitled"
            in_frontmatter = False
            frontmatter_lines: list[str] = []
            for i, line in enumerate(lines):
                if i == 0 and line.strip() == "---json":
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    if line.strip() == "---":
                        in_frontmatter = False
                        try:
                            fm = json.loads("\n".join(frontmatter_lines))
                            if "title" in fm:
                                title = fm["title"]
                        except json.JSONDecodeError:
                            pass
                        break
                    frontmatter_lines.append(line)
            snippet = content[:100].replace("\n", " ")
            expanded.append(
                WikiSearchResult(
                    page_path=link_path,
                    title=title,
                    score=score,
                    snippet=snippet,
                )
            )
    return expanded


@dataclass(frozen=True)
class WikiQueryResult:
    wiki_hits: list[WikiSearchResult]
    linked_hits: list[WikiSearchResult]
    fallback_used: bool
    fallback_reason: str


def wiki_query_with_fallback(
    query: str,
    index: WikiQueryIndex,
    page_store: WikiPageStore,
    *,
    enabled: bool = False,
    limit: int = 5,
    expand_links: bool = True,
    max_linked: int = 3,
) -> WikiQueryResult:
    primary_results, found = wiki_first_search(query, index, enabled=enabled, limit=limit)
    if not found:
        return WikiQueryResult(
            wiki_hits=[],
            linked_hits=[],
            fallback_used=True,
            fallback_reason="no wiki hits",
        )
    linked_results: list[WikiSearchResult] = []
    if expand_links:
        linked_results = expand_linked_pages(primary_results, page_store, max_linked=max_linked)
    return WikiQueryResult(
        wiki_hits=primary_results,
        linked_hits=linked_results,
        fallback_used=False,
        fallback_reason="",
    )
