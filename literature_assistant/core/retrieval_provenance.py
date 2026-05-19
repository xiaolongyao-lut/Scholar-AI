from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


_LABEL_SPLIT_RE = re.compile(r"[+,|;]+")
_LABEL_SAFE_RE = re.compile(r"[^a-z0-9_.:-]+")


def normalize_source_labels(value: Any) -> List[str]:
    """Return deterministic source labels for retrieval provenance.

    Args:
        value: A string label, delimiter-separated string, or iterable of labels.

    Returns:
        Ordered, de-duplicated labels normalized to lowercase ASCII tokens.

    Raises:
        TypeError: If an iterable label container contains a non-string scalar.
    """
    labels: List[str] = []

    def _append(raw_label: str) -> None:
        label = _LABEL_SAFE_RE.sub("_", raw_label.strip().lower()).strip("_")
        if label and label not in labels:
            labels.append(label)

    if value is None:
        return labels
    if isinstance(value, str):
        for part in _LABEL_SPLIT_RE.split(value):
            _append(part)
        return labels
    if isinstance(value, set):
        iterable: Iterable[Any] = sorted(value, key=lambda item: str(item))
    elif isinstance(value, (list, tuple)):
        iterable = value
    else:
        raise TypeError("source labels must be a string or iterable of strings")

    for item in iterable:
        if item is None:
            continue
        if isinstance(item, str):
            labels.extend(
                label
                for label in normalize_source_labels(item)
                if label not in labels
            )
            continue
        raise TypeError("source label entries must be strings")
    return labels


def merge_source_labels(*values: Any) -> List[str]:
    """Merge several source-label payloads without losing rank provenance.

    Args:
        *values: Strings or iterables accepted by `normalize_source_labels`.

    Returns:
        Ordered, de-duplicated source labels.
    """
    merged: List[str] = []
    for value in values:
        for label in normalize_source_labels(value):
            if label not in merged:
                merged.append(label)
    return merged


def attach_source_labels(
    item: Dict[str, Any],
    labels: Any,
    *,
    source_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Copy a retrieval hit and attach stable provenance labels.

    Args:
        item: Retrieval hit dictionary. It is copied before modification.
        labels: Additional labels to merge into `source_labels`.
        source_hint: Optional explicit display/debug hint. When omitted, the
            hint is derived from the merged labels.

    Returns:
        A copied retrieval hit containing `source_labels` and `source_hint`.

    Raises:
        TypeError: If `item` is not a dictionary or labels are malformed.
    """
    if not isinstance(item, dict):
        raise TypeError("retrieval hit must be a dictionary")

    merged = merge_source_labels(item.get("source_labels"), labels)
    updated = dict(item)
    if merged:
        updated["source_labels"] = merged
        updated["source_hint"] = str(source_hint).strip() if source_hint else "+".join(merged)
    return updated
