from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from literature_assistant.core.project_paths import ensure_directory, wiki_trace_path
from literature_assistant.core.wiki.evidence_adapter import build_synthesis_body, coerce_evidence_refs
from literature_assistant.core.wiki.models import WikiPageKind, WikiPageStatus
from literature_assistant.core.wiki.observability import WikiObservabilitySink
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page, stable_slug


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
    source: str = "wiki_fts"


class WikiQueryIndex:
    def __init__(self, db_path: Path, *, observability_sink: WikiObservabilitySink | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._warmup_done = False
        self.observability_sink = observability_sink

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

    def warmup_common_queries(self, common_patterns: list[str] | None = None) -> None:
        """Pre-load FTS index for common query patterns to reduce first-query latency.

        Tier 1 optimization: Cache warmup (0.5-1s savings on first query).
        Runs once per index instance; subsequent calls are no-ops.

        Args:
            common_patterns: List of common search patterns. If None, uses defaults.
        """
        if self._warmup_done:
            return

        if common_patterns is None:
            common_patterns = ["research", "study", "analysis", "method", "data"]

        conn = self._get_conn()
        try:
            for pattern in common_patterns:
                if pattern and pattern.strip():
                    conn.execute(
                        "SELECT COUNT(*) FROM wiki_pages_fts WHERE wiki_pages_fts MATCH ?",
                        (pattern,),
                    )
            self._warmup_done = True
        except Exception:
            pass

    def index_page(self, page_path: Path, title: str, body: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO wiki_pages_fts (page_path, title, body) VALUES (?, ?, ?)",
            (str(page_path), title, body),
        )
        digest = hashlib.sha256(
            f"{Path(page_path).as_posix()}:{title}:{body}".encode("utf-8")
        ).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
            ("index_hash", digest),
        )
        conn.execute(
            "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
            ("last_indexed", datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
        )
        conn.commit()

    def search(self, query: str, limit: int = 10) -> list[WikiSearchResult]:
        if not query or not query.strip():
            return []
        if limit <= 0:
            return []
        span = (
            self.observability_sink.start_span("wiki.query.index.search", {"limit": limit})
            if self.observability_sink is not None
            else None
        )
        if span is not None:
            span.__enter__()
        conn = self._get_conn()
        span_error: BaseException | None = None
        try:
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
                        source="wiki_fts",
                    )
                )
            if self.observability_sink is not None:
                self.observability_sink.record_metric(
                    "wiki.query.index.hit_count",
                    len(results),
                    {"limit": limit, "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]},
                    unit="hits",
            )
            return results
        except Exception as exc:
            span_error = exc
            raise
        finally:
            if span is not None:
                if span_error is None:
                    span.__exit__(None, None, None)
                else:
                    span.__exit__(type(span_error), span_error, span_error.__traceback__)

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

    def build_wiki_index(self, page_store: WikiPageStore) -> None:
        """Build this index from a page store for legacy method callers."""

        build_wiki_index(page_store, self)


def build_wiki_index(page_store: WikiPageStore, index: WikiQueryIndex) -> None:
    index.initialize()
    conn = index._get_conn()
    conn.execute("DELETE FROM wiki_pages_fts")
    conn.commit()
    pages = page_store.list_pages()
    indexed_payload: list[str] = []
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
            indexed_payload.append(f"{page_path.as_posix()}:{title}:{hashlib.sha256(body.encode('utf-8')).hexdigest()}")
    index_hash = hashlib.sha256("\n".join(sorted(indexed_payload)).encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
        ("index_hash", index_hash),
    )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, datetime('now'))",
        ("last_indexed",),
    )
    conn.commit()


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
    import re

    if max_linked <= 0:
        return []
    linked_pages: dict[Path, float] = {}
    linked_sources: dict[Path, set[Path]] = {}
    primary_paths = {r.page_path for r in primary_results}

    def _candidate_paths(raw_link: str, source_path: Path) -> list[Path]:
        link_text = raw_link.strip()
        if not link_text:
            return []
        link_target = link_text.split("|", 1)[0].split("#", 1)[0].strip()
        if not link_target:
            return []
        normalized = Path(link_target)
        candidates: list[Path] = []
        if normalized.suffix.lower() != ".md":
            candidates.append(normalized.with_suffix(".md"))
        candidates.append(normalized)
        if len(normalized.parts) == 1:
            parent = source_path.parent
            for candidate in list(candidates):
                if parent != Path("."):
                    candidates.append(parent / candidate)
        unique: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate.is_absolute() or ".." in candidate.parts:
                continue
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

    def _first_existing_link(raw_link: str, source_path: Path) -> Path | None:
        for candidate in _candidate_paths(raw_link, source_path):
            if page_store.read_page(candidate):
                return candidate
        return None

    for result in primary_results:
        content = page_store.read_page(result.page_path)
        if not content:
            continue
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        for link in wikilinks:
            link_path = _first_existing_link(link, result.page_path)
            if link_path is None:
                continue
            if link_path in primary_paths:
                continue
            if link_path not in linked_pages:
                linked_pages[link_path] = 0.0
                linked_sources[link_path] = set()
            linked_pages[link_path] += result.score * 0.5
            linked_sources[link_path].add(result.page_path)

    sorted_linked = sorted(
        linked_pages.items(),
        key=lambda x: (x[1], len(linked_sources.get(x[0], set())), x[0].as_posix()),
        reverse=True,
    )
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
                    source="wiki_linked",
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


@dataclass(frozen=True)
class WikiContextPack:
    query: str
    primary_pages: list[str]
    linked_pages: list[str]
    total_tokens: int
    truncated: bool
    omitted_pages: list[str] | None = None
    max_tokens: int = 0


@dataclass(frozen=True)
class WikiQueryTrace:
    query: str
    enabled: bool
    fts_hits: int
    linked_hits: int
    fallback_used: bool
    fallback_reason: str
    total_pages: int
    context_tokens: int
    context_max_tokens: int
    context_truncated: bool
    omitted_pages: list[str]


def _strip_frontmatter(content: str) -> str:
    lines = content.split("\n")
    if lines and lines[0].strip() == "---json":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1 :])
    return content


def _fit_context_text(
    target: list[str],
    text: str,
    *,
    total_chars: int,
    max_chars: int,
) -> tuple[int, bool]:
    if not text:
        return total_chars, False
    remaining = max_chars - total_chars
    if remaining <= 0:
        return total_chars, False
    if len(text) <= remaining:
        target.append(text)
        return total_chars + len(text), True
    if remaining >= 80:
        target.append(text[: max(0, remaining - 24)].rstrip() + "\n\n...[truncated]")
        return max_chars, True
    return total_chars, False


def render_context_pack(
    query: str,
    query_result: WikiQueryResult,
    page_store: WikiPageStore,
    *,
    max_tokens: int = 4000,
    tokens_per_char: float = 0.25,
) -> WikiContextPack:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query cannot be empty")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if tokens_per_char <= 0:
        raise ValueError("tokens_per_char must be positive")
    primary_pages: list[str] = []
    linked_pages: list[str] = []
    omitted_pages: list[str] = []
    total_chars = 0
    max_chars = int(max_tokens / tokens_per_char)
    truncated = False

    for result in query_result.wiki_hits:
        content = page_store.read_page(result.page_path)
        if not content:
            omitted_pages.append(result.page_path.as_posix())
            continue
        body = _strip_frontmatter(content)
        header = f"## {result.title}\n\nSource: {result.page_path.as_posix()}\nScore: {result.score:.4f}\n\n"
        page_text = header + body
        next_total, included = _fit_context_text(
            primary_pages,
            page_text,
            total_chars=total_chars,
            max_chars=max_chars,
        )
        if not included:
            truncated = True
            omitted_pages.append(result.page_path.as_posix())
            break
        total_chars = next_total
        if total_chars >= max_chars and len(page_text) > max_chars:
            truncated = True
            omitted_pages.extend(
                hit.page_path.as_posix()
                for hit in query_result.wiki_hits
                if hit.page_path != result.page_path
            )
            break

    for result in query_result.linked_hits:
        if total_chars >= max_chars:
            truncated = True
            omitted_pages.append(result.page_path.as_posix())
            break
        content = page_store.read_page(result.page_path)
        if not content:
            omitted_pages.append(result.page_path.as_posix())
            continue
        body = _strip_frontmatter(content)
        header = f"### {result.title} (linked)\n\nSource: {result.page_path.as_posix()}\nScore: {result.score:.4f}\n\n"
        page_text = header + body
        next_total, included = _fit_context_text(
            linked_pages,
            page_text,
            total_chars=total_chars,
            max_chars=max_chars,
        )
        if not included:
            truncated = True
            omitted_pages.append(result.page_path.as_posix())
            break
        total_chars = next_total

    return WikiContextPack(
        query=query,
        primary_pages=primary_pages,
        linked_pages=linked_pages,
        omitted_pages=omitted_pages,
        total_tokens=int(total_chars * tokens_per_char),
        truncated=truncated,
        max_tokens=max_tokens,
    )


def build_query_trace(
    query: str,
    query_result: WikiQueryResult,
    context_pack: WikiContextPack | None = None,
    *,
    enabled: bool = False,
) -> WikiQueryTrace:
    return WikiQueryTrace(
        query=query,
        enabled=enabled,
        fts_hits=len(query_result.wiki_hits),
        linked_hits=len(query_result.linked_hits),
        fallback_used=query_result.fallback_used,
        fallback_reason=query_result.fallback_reason,
        total_pages=len(query_result.wiki_hits) + len(query_result.linked_hits),
        context_tokens=context_pack.total_tokens if context_pack else 0,
        context_max_tokens=context_pack.max_tokens if context_pack else 0,
        context_truncated=context_pack.truncated if context_pack else False,
        omitted_pages=list(context_pack.omitted_pages or []) if context_pack else [],
    )


def write_query_trace(trace: WikiQueryTrace, *, trace_dir: Path | None = None) -> Path:
    """Persist a sanitized wiki query trace under workspace runtime artifacts."""

    if not isinstance(trace, WikiQueryTrace):
        raise TypeError("trace must be a WikiQueryTrace")
    target_dir = ensure_directory(trace_dir or wiki_trace_path())
    digest = hashlib.sha256(trace.query.encode("utf-8")).hexdigest()[:12]
    target = target_dir / f"wiki-query-{digest}.json"
    payload = {
        "query_hash": digest,
        "enabled": trace.enabled,
        "fts_hits": trace.fts_hits,
        "linked_hits": trace.linked_hits,
        "fallback_used": trace.fallback_used,
        "fallback_reason": trace.fallback_reason,
        "total_pages": trace.total_pages,
        "context_tokens": trace.context_tokens,
        "context_max_tokens": trace.context_max_tokens,
        "context_truncated": trace.context_truncated,
        "omitted_pages": trace.omitted_pages,
    }
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target


@dataclass(frozen=True)
class ExplorationSaveResult:
    """Result of saving an exploration page (LMWR-353)."""

    success: bool
    relative_path: Path | None
    content_hash: str | None
    error: str | None = None


def save_exploration(
    query: str,
    answer: str,
    evidence_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    page_store: WikiPageStore,
    *,
    source_ids: tuple[str, ...] = (),
) -> ExplorationSaveResult:
    """Save query answer as exploration page (LMWR-353).

    Generates exploration page with:
      - kind=exploration
      - status=draft (requires citation validation before finalization per LMWR-357)
      - frontmatter with id, kind, title, status
      - body with question, answer, and evidence section

    Args:
        query: Query question
        answer: Answer text
        evidence_refs: List of evidence reference dicts
        page_store: WikiPageStore instance for atomic write
        source_ids: Optional tuple of source IDs for frontmatter

    Returns:
        ExplorationSaveResult with success flag, path, and hash or error.

    Raises:
        ValueError: If query/answer empty or no evidence refs.
    """
    try:
        # Coerce and validate evidence refs
        refs = coerce_evidence_refs(evidence_refs)

        # Build body using synthesis pattern
        body = build_synthesis_body(query, answer, refs)

        # Generate stable slug from query
        slug = stable_slug(query)

        # Build page ID and relative path
        page_id = f"{WikiPageKind.exploration.value}/{slug}"
        relative_path = Path(WikiPageKind.exploration.value) / f"{slug}.md"

        # Build frontmatter
        frontmatter = {
            "id": page_id,
            "kind": WikiPageKind.exploration.value,
            "title": query.strip(),
            "status": WikiPageStatus.draft.value,
        }
        if source_ids:
            frontmatter["source_ids"] = list(source_ids)

        # Render page (atomic write pattern from Blueprint C)
        rendered = render_page(relative_path, frontmatter, body)

        # Write atomically
        page_store.write_rendered(rendered, allow_overwrite=True)

        return ExplorationSaveResult(
            success=True,
            relative_path=relative_path,
            content_hash=rendered.content_hash,
        )

    except (ValueError, TypeError) as e:
        return ExplorationSaveResult(
            success=False,
            relative_path=None,
            content_hash=None,
            error=str(e),
        )
    except Exception as e:
        return ExplorationSaveResult(
            success=False,
            relative_path=None,
            content_hash=None,
            error=f"Unexpected error: {str(e)}",
        )
