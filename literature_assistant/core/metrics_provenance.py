"""Metrics provenance validator.

When eval scripts write ``.metrics.json`` files, the filename frequently
encodes the rerank model slug (e.g. ``canary30-a2-gte-rerank-v2-...metrics.json``).
The 2026-05-11 v3.1 rerun exposed a drift where the filename promised
``gte-rerank-v2`` but the actual ``retrieval_config.rerank_model`` was
``qwen3-vl-rerank`` (because DashScope fallback kicked in mid-run).

This module provides a single fail-closed validator that eval scripts
should call before writing the metrics file:

    validate_metrics_filename_against_payload(
        output_path="workspace_artifacts/.../canary30-a2-gte-rerank-v2-20260510.metrics.json",
        payload=metrics_payload,
    )

If the filename embeds a known rerank-model slug AND the payload's
``retrieval_config.rerank_model`` does not contain that slug, the
validator raises :class:`MetricsProvenanceDriftError`.

The validator is permissive in the absence of evidence: filenames that
do not embed any recognised slug, or payloads that have ``use_rerank=False``
/ ``rerank_model=None``, are passed through without error. This keeps
the validator non-blocking for legacy non-rerank evals while catching
the specific drift class that 2026-05-11 found.

Known rerank-model slugs (registry — extend as new rerank models are added):

  * ``gte-rerank-v2``
  * ``qwen3-rerank`` / ``qwen3-vl-rerank``
  * ``bge-rerank-v2-m3``
  * ``cohere-rerank-v3``

Slug detection is intentionally substring-based and lowercases the path
basename. False negatives (file slug present but unrecognised) skip
validation; false positives (filename slug embedded by accident) are the
risk we accept for now. Slug registry is documented inline so the test
suite can iterate it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


# Public registry of (canonical_slug, regex_pattern) — patterns are case-
# insensitive substrings. New rerank models are added here.
KNOWN_RERANK_SLUGS: tuple[tuple[str, str], ...] = (
    ("gte-rerank-v2",       r"gte[-_]?rerank[-_]?v2"),
    ("gte-rerank",          r"gte[-_]?rerank(?![-_]v\d)"),
    ("qwen3-vl-rerank",     r"qwen3[-_]?vl[-_]?rerank"),
    ("qwen3-rerank",        r"qwen3[-_]?rerank(?![-_]?vl)"),
    ("bge-rerank-v2-m3",    r"bge[-_]?rerank[-_]?v2[-_]?m3"),
    ("bge-reranker",        r"bge[-_]?reranker"),
    ("cohere-rerank-v3",    r"cohere[-_]?rerank[-_]?v3"),
    ("jina-rerank",         r"jina[-_]?rerank"),
)


class MetricsProvenanceDriftError(ValueError):
    """Raised when filename-encoded rerank model slug disagrees with the
    actual ``retrieval_config.rerank_model`` in the payload.

    The message is structured so a release gate can parse it:

        "rerank model provenance drift: filename slug 'gte-rerank-v2' "
        "does not match payload rerank_model 'qwen3-vl-rerank' at <path>"
    """


def detect_filename_rerank_slug(path: str | Path) -> str | None:
    """Return the first matching canonical slug found in ``path`` basename,
    or ``None`` if no known slug is detected.

    Iteration order follows the order of ``KNOWN_RERANK_SLUGS`` (most
    specific first — e.g. ``gte-rerank-v2`` before ``gte-rerank``).
    """
    name = str(Path(path).name).lower()
    for canonical, pattern in KNOWN_RERANK_SLUGS:
        if re.search(pattern, name, re.IGNORECASE):
            return canonical
    return None


def payload_rerank_model(payload: dict[str, Any]) -> str | None:
    """Extract ``retrieval_config.rerank_model`` from the payload, lowercased.

    Returns ``None`` if absent, empty, or the payload structure does not
    contain ``retrieval_config``.
    """
    rc = payload.get("retrieval_config") if isinstance(payload, dict) else None
    if not isinstance(rc, dict):
        return None
    model = rc.get("rerank_model")
    if model is None:
        return None
    text = str(model).strip().lower()
    return text or None


def slug_matches_model(slug: str, rerank_model: str) -> bool:
    """Return True iff ``slug`` is consistent with the payload's
    ``rerank_model`` value.

    The relation is intentionally loose substring containment in BOTH
    directions to cover variants like ``Qwen/Qwen3-VL-Rerank-8B-Instruct``
    being matched by the ``qwen3-vl-rerank`` slug.
    """
    s = slug.lower().strip()
    m = rerank_model.lower().strip()
    if not s or not m:
        return False
    # Direction 1: slug appears in model name (e.g. "qwen3-vl-rerank" in
    # "qwen/qwen3-vl-rerank-8b-instruct"). Allow hyphen/underscore drift.
    s_relaxed = s.replace("-", "[-_]?").replace("_", "[-_]?")
    if re.search(s_relaxed, m):
        return True
    # Direction 2: model token appears in slug (rare but defensible).
    m_relaxed = m.replace("-", "[-_]?").replace("_", "[-_]?")
    if re.search(m_relaxed, s):
        return True
    return False


def validate_metrics_filename_against_payload(
    output_path: str | Path,
    payload: dict[str, Any],
    *,
    strict: bool = True,
) -> None:
    """Validate that the filename and payload agree on rerank model identity.

    Permissive cases (no error):
      * filename has no recognised rerank slug
      * payload has ``use_rerank=False`` (rerank intentionally disabled)
      * payload has ``rerank_model`` None / empty

    Failure case (raises if ``strict=True``, otherwise silently returns):
      * filename has slug X AND payload rerank_model exists AND does not
        match slug X

    Parameters
    ----------
    output_path
        The path the metrics file is about to be written to.
    payload
        The dict that will be json.dump()'d to ``output_path``.
    strict
        If True (default), raise ``MetricsProvenanceDriftError`` on drift.
        If False, return silently — used during gradual rollout.

    Raises
    ------
    MetricsProvenanceDriftError
        If the filename slug and payload rerank_model are both present
        and inconsistent.
    """
    slug = detect_filename_rerank_slug(output_path)
    if slug is None:
        return  # no slug in filename — nothing to check

    # If retrieval_config explicitly says rerank is off, skip — the slug
    # in filename is probably a leftover from a template; not a drift.
    rc = payload.get("retrieval_config") if isinstance(payload, dict) else None
    if isinstance(rc, dict) and rc.get("use_rerank") is False:
        return

    model = payload_rerank_model(payload)
    if model is None:
        return  # no rerank model recorded — out of scope

    if slug_matches_model(slug, model):
        return  # all consistent

    msg = (
        f"rerank model provenance drift: filename slug {slug!r} does not match "
        f"payload rerank_model {model!r} at {output_path}"
    )
    if strict:
        raise MetricsProvenanceDriftError(msg)


def iter_known_slugs() -> Iterable[str]:
    """Helper for tests / introspection — yields the canonical slug names."""
    for slug, _ in KNOWN_RERANK_SLUGS:
        yield slug


__all__ = [
    "KNOWN_RERANK_SLUGS",
    "MetricsProvenanceDriftError",
    "detect_filename_rerank_slug",
    "iter_known_slugs",
    "payload_rerank_model",
    "slug_matches_model",
    "validate_metrics_filename_against_payload",
]
