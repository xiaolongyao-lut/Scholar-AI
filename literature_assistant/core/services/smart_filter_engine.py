# -*- coding: utf-8 -*-
"""Smart source filtering for batch literature ingestion."""

from __future__ import annotations

import inspect
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


EmbedTextsFn = Callable[[list[str]], Awaitable[list[list[float]]] | list[list[float]]]


@dataclass(frozen=True)
class SmartFilterMetadata:
    """Lightweight metadata extracted from a local source file.

    Args:
        title: Human-readable file stem or embedded title.
        abstract: Extracted abstract text. Empty when no abstract-like section
            can be detected.
    """

    title: str
    abstract: str = ""


@dataclass(frozen=True)
class SmartFilterDecision:
    """One file-level filtering decision.

    Args:
        source_path: Local source path evaluated by the filter.
        accepted: Whether the file should continue to ingestion.
        stage: Decision stage, currently ``keyword`` or ``vector``.
        reason: Stable machine-readable reason string.
        keyword_score: Token-overlap score in the range [0, 1].
        vector_score: Cosine similarity when embeddings are available.
    """

    source_path: Path
    accepted: bool
    stage: str
    reason: str
    keyword_score: float
    vector_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for API responses."""

        return {
            "source_path": str(self.source_path),
            "accepted": self.accepted,
            "stage": self.stage,
            "reason": self.reason,
            "keyword_score": round(self.keyword_score, 6),
            "vector_score": round(self.vector_score, 6) if self.vector_score is not None else None,
        }


@dataclass(frozen=True)
class SmartFilterReport:
    """Aggregate filtering report returned with batch ingestion results.

    Args:
        embedding_available: Whether vector scoring completed successfully.
        total_files: Number of source paths evaluated.
        keyword_passed: Number of files that reached the post-keyword stage.
        vector_passed: Number of files scored by the vector stage.
        selected_files: Number of accepted files.
        decisions: Per-file decisions.
    """

    embedding_available: bool
    total_files: int
    keyword_passed: int
    vector_passed: int
    selected_files: int
    decisions: list[SmartFilterDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe report payload for API responses."""

        return {
            "embedding_available": self.embedding_available,
            "total_files": self.total_files,
            "keyword_passed": self.keyword_passed,
            "vector_passed": self.vector_passed,
            "selected_files": self.selected_files,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class SmartFilterResult:
    """Accepted source paths plus the detailed filtering report."""

    selected_paths: list[Path]
    report: SmartFilterReport


@dataclass(frozen=True)
class _Candidate:
    source_path: Path
    text: str
    keyword_score: float


class SmartFilterEngine:
    """Filter local source paths before expensive extraction and indexing."""

    _MAX_TEXT_CHARS = 24000
    _ABSTRACT_PATTERN = re.compile(
        r"(?is)(?:^|\n)\s*(?:abstract|摘要)\s*[:：]?\s*(.+?)(?=\n\s*(?:keywords?|关键词|introduction|引言|1[\.\s])\b|\Z)"
    )

    def __init__(
        self,
        *,
        keyword_threshold: float = 0.08,
        high_confidence_threshold: float = 0.72,
        borderline_threshold: float = 0.40,
        embed_texts: EmbedTextsFn | None = None,
    ) -> None:
        """Create a filter engine.

        Args:
            keyword_threshold: Minimum lexical overlap required before a file
                can be selected or vector-scored.
            high_confidence_threshold: Vector similarity required for direct
                acceptance when embeddings are available.
            borderline_threshold: Lower vector bound accepted only when lexical
                evidence is already strong.
            embed_texts: Optional embedding callback. It receives
                ``[goal, *candidate_texts]`` and returns same-length vectors.
        """

        self.keyword_threshold = self._validate_threshold(keyword_threshold, "keyword_threshold")
        self.high_confidence_threshold = self._validate_threshold(
            high_confidence_threshold,
            "high_confidence_threshold",
        )
        self.borderline_threshold = self._validate_threshold(borderline_threshold, "borderline_threshold")
        if self.borderline_threshold > self.high_confidence_threshold:
            raise ValueError("borderline_threshold must be <= high_confidence_threshold")
        if embed_texts is not None and not callable(embed_texts):
            raise TypeError("embed_texts must be callable")
        self.embed_texts = embed_texts

    async def filter_paths(
        self,
        paths: Sequence[str | Path],
        goal: str,
    ) -> SmartFilterResult:
        """Filter existing local files against a user goal.

        Args:
            paths: Non-empty sequence of local file paths.
            goal: Non-empty natural-language ingestion goal.

        Returns:
            Accepted paths in the original input order plus a structured report.
        """

        normalized_paths = self._validate_paths(paths)
        goal_text = self._require_non_empty(goal, "goal")

        candidates: list[_Candidate] = []
        rejected: list[SmartFilterDecision] = []
        for path in normalized_paths:
            text = self._read_text_for_filter(path)
            keyword_score = self._keyword_score(goal_text, text)
            if keyword_score < self.keyword_threshold:
                rejected.append(
                    SmartFilterDecision(
                        source_path=path,
                        accepted=False,
                        stage="keyword",
                        reason="keyword_below_threshold",
                        keyword_score=keyword_score,
                    )
                )
                continue
            candidates.append(_Candidate(source_path=path, text=text, keyword_score=keyword_score))

        if not candidates:
            decisions = self._order_decisions(rejected)
            return SmartFilterResult(
                selected_paths=[],
                report=SmartFilterReport(
                    embedding_available=False,
                    total_files=len(normalized_paths),
                    keyword_passed=0,
                    vector_passed=0,
                    selected_files=0,
                    decisions=decisions,
                ),
            )

        if self.embed_texts is None:
            accepted = [
                SmartFilterDecision(
                    source_path=candidate.source_path,
                    accepted=True,
                    stage="keyword",
                    reason="embedding_unavailable_keyword_fallback",
                    keyword_score=candidate.keyword_score,
                )
                for candidate in candidates
            ]
            selected_paths = [candidate.source_path for candidate in candidates]
            decisions = self._order_decisions([*rejected, *accepted])
            return SmartFilterResult(
                selected_paths=selected_paths,
                report=SmartFilterReport(
                    embedding_available=False,
                    total_files=len(normalized_paths),
                    keyword_passed=len(candidates),
                    vector_passed=0,
                    selected_files=len(selected_paths),
                    decisions=decisions,
                ),
            )

        vector_result = await self._try_vector_decisions(goal_text, candidates)
        if vector_result is None:
            accepted = [
                SmartFilterDecision(
                    source_path=candidate.source_path,
                    accepted=True,
                    stage="keyword",
                    reason="embedding_unavailable_keyword_fallback",
                    keyword_score=candidate.keyword_score,
                )
                for candidate in candidates
            ]
            selected_paths = [candidate.source_path for candidate in candidates]
            decisions = self._order_decisions([*rejected, *accepted])
            return SmartFilterResult(
                selected_paths=selected_paths,
                report=SmartFilterReport(
                    embedding_available=False,
                    total_files=len(normalized_paths),
                    keyword_passed=len(candidates),
                    vector_passed=0,
                    selected_files=len(selected_paths),
                    decisions=decisions,
                ),
            )

        vector_decisions, selected_paths = vector_result
        decisions = self._order_decisions([*rejected, *vector_decisions])
        return SmartFilterResult(
            selected_paths=selected_paths,
            report=SmartFilterReport(
                embedding_available=True,
                total_files=len(normalized_paths),
                keyword_passed=len(candidates),
                vector_passed=len(candidates),
                selected_files=len(selected_paths),
                decisions=decisions,
            ),
        )

    def extract_metadata(self, source_path: str | Path) -> SmartFilterMetadata:
        """Extract a small metadata envelope from a local source file.

        Args:
            source_path: Existing local source path.

        Returns:
            Title and abstract-like text. Binary or unreadable files return an
            empty abstract with a filename-derived title.
        """

        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"source_path does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"source_path must be a file: {path}")
        title = path.stem.strip() or path.name
        text = self._read_text_for_filter(path)
        match = self._ABSTRACT_PATTERN.search(text)
        abstract = ""
        if match:
            abstract = re.sub(r"\s+", " ", match.group(1)).strip()
        return SmartFilterMetadata(title=title, abstract=abstract[:2000])

    async def _try_vector_decisions(
        self,
        goal: str,
        candidates: list[_Candidate],
    ) -> tuple[list[SmartFilterDecision], list[Path]] | None:
        if self.embed_texts is None:
            return None
        texts = [goal, *[candidate.text for candidate in candidates]]
        try:
            raw_vectors = self.embed_texts(texts)
            vectors = await raw_vectors if inspect.isawaitable(raw_vectors) else raw_vectors
            normalized_vectors = self._validate_vectors(vectors, expected=len(texts))
        except Exception:
            return None

        query_vector = normalized_vectors[0]
        decisions: list[SmartFilterDecision] = []
        selected_paths: list[Path] = []
        for candidate, vector in zip(candidates, normalized_vectors[1:], strict=True):
            vector_score = self._cosine_similarity(query_vector, vector)
            accepted = False
            reason = "vector_below_threshold"
            if vector_score >= self.high_confidence_threshold:
                accepted = True
                reason = "vector_high_confidence"
            elif vector_score >= self.borderline_threshold and candidate.keyword_score >= self.high_confidence_threshold:
                accepted = True
                reason = "vector_borderline_keyword_support"

            if accepted:
                selected_paths.append(candidate.source_path)
            decisions.append(
                SmartFilterDecision(
                    source_path=candidate.source_path,
                    accepted=accepted,
                    stage="vector",
                    reason=reason,
                    keyword_score=candidate.keyword_score,
                    vector_score=vector_score,
                )
            )
        return decisions, selected_paths

    @staticmethod
    def _validate_threshold(value: float, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise TypeError(f"{name} must be a number")
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        return numeric

    @staticmethod
    def _require_non_empty(value: str, name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} must be non-empty")
        return normalized

    @staticmethod
    def _validate_paths(paths: Sequence[str | Path]) -> list[Path]:
        if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence):
            raise TypeError("paths must be a sequence of paths")
        if not paths:
            raise ValueError("paths must be non-empty")
        normalized: list[Path] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(f"path does not exist: {path}")
            if not path.is_file():
                raise ValueError(f"path must be a file: {path}")
            normalized.append(path)
        return normalized

    def _read_text_for_filter(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[: self._MAX_TEXT_CHARS]
        except OSError:
            return path.name

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        normalized = text.lower().strip()
        if not normalized:
            return set()
        latin_tokens = re.findall(r"[a-z0-9_]+", normalized)
        cjk_chars = [ch for ch in normalized if "\u4e00" <= ch <= "\u9fff"]
        cjk_bigrams = ["".join(cjk_chars[index : index + 2]) for index in range(len(cjk_chars) - 1)]
        return set(latin_tokens + (cjk_bigrams or cjk_chars))

    def _keyword_score(self, goal: str, text: str) -> float:
        goal_tokens = self._tokenize(goal)
        if not goal_tokens:
            return 0.0
        text_tokens = self._tokenize(text)
        if not text_tokens:
            return 0.0
        return len(goal_tokens & text_tokens) / len(goal_tokens)

    @staticmethod
    def _validate_vectors(vectors: list[list[float]], expected: int) -> list[list[float]]:
        if not isinstance(vectors, list):
            raise TypeError("embedding callback must return a list")
        if len(vectors) != expected:
            raise ValueError("embedding callback returned an unexpected vector count")
        normalized: list[list[float]] = []
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding vectors must be non-empty lists")
            coerced: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (float, int)):
                    raise TypeError("embedding vector values must be numeric")
                coerced.append(float(value))
            normalized.append(coerced)
        return normalized

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise ValueError("embedding vectors must have matching dimensions")
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))

    @staticmethod
    def _order_decisions(decisions: list[SmartFilterDecision]) -> list[SmartFilterDecision]:
        return sorted(decisions, key=lambda item: (item.accepted, str(item.source_path).lower()))
