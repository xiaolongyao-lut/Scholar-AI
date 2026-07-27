"""Tokenizer helpers shared by embedding / rerank length guards.

Uses a BGE-m3 (XLM-R family) tokenizer as a **conservative** token estimator —
BGE-m3 tokenizes Chinese tighter than most SentencePiece/BBPE variants, so the
produced counts overestimate for looser tokenizers like Qwen3's BBPE. That is
the safe side: if the guard says "fits", it almost surely fits downstream.

Falls back to `len(text) * 0.75` when the HF tokenizer can't be loaded (offline
first-run, firewalled runners, etc.) — a measured CJK char→token ratio.

Offline override:
    Set ``LITASSIST_TOKEN_UTILS_OFFLINE=1`` to skip the HF tokenizer load entirely
    and go straight to the char-ratio fallback. Useful in offline / airgapped /
    CI environments where the HuggingFace HTTP retry hang is unacceptable.
    Default is unset = original online-first behavior preserved.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, TypeGuard

logger = logging.getLogger(__name__)

_TOKENIZER_MODEL = "BAAI/bge-m3"
_CJK_CHAR_RATIO = 0.75  # conservative lower bound for Chinese-heavy text
_OFFLINE_ENV_VAR = "LITASSIST_TOKEN_UTILS_OFFLINE"

class _Tokenizer(Protocol):
    """Small tokenizer surface used by the length guards."""

    def __call__(
        self,
        text: str,
        *,
        add_special_tokens: bool,
        truncation: bool,
    ) -> object: ...

    def decode(
        self,
        token_ids: Sequence[int],
        *,
        skip_special_tokens: bool,
    ) -> object: ...


_tokenizer: _Tokenizer | None = None
_tokenizer_loaded = False


def _is_offline_forced() -> bool:
    """Return True iff the user explicitly forced offline mode via env var.

    Accepts "1" / "true" / "yes" (case-insensitive) as truthy. Any other value
    (including "0" / "false" / unset) keeps the original online-first behavior.
    """
    val = os.environ.get(_OFFLINE_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes")


def _is_tokenizer(value: object) -> TypeGuard[_Tokenizer]:
    """Check the callable and decoder capabilities consumed by this module."""

    return callable(value) and callable(getattr(value, "decode", None))


def _token_ids(tokenizer: _Tokenizer, text: str) -> list[int]:
    """Encode text and validate the tokenizer response shape."""

    encoded = tokenizer(text, add_special_tokens=False, truncation=False)
    if not isinstance(encoded, Mapping):
        raise TypeError("tokenizer output must be a mapping")
    raw_ids = encoded.get("input_ids")
    if not isinstance(raw_ids, list) or any(
        isinstance(token_id, bool) or not isinstance(token_id, int)
        for token_id in raw_ids
    ):
        raise TypeError("tokenizer input_ids must be a list of integers")
    return raw_ids


def _decode_tokens(tokenizer: _Tokenizer, token_ids: Sequence[int]) -> str:
    """Decode token ids while preserving the historical string coercion."""

    decoded = tokenizer.decode(token_ids, skip_special_tokens=True)
    return decoded.strip() if isinstance(decoded, str) else str(decoded).strip()


def _get_tokenizer() -> _Tokenizer | None:
    global _tokenizer, _tokenizer_loaded
    if _tokenizer_loaded:
        return _tokenizer
    _tokenizer_loaded = True
    # Offline override: skip HF tokenizer load entirely. char-ratio fallback.
    # Logged once at INFO so operators can confirm it's intentional.
    if _is_offline_forced():
        logger.info(
            "token_utils: %s=1 set; skipping HF tokenizer load, using char-ratio estimator",
            _OFFLINE_ENV_VAR,
        )
        _tokenizer = None
        return _tokenizer
    try:
        from transformers import AutoTokenizer

        candidate: object = AutoTokenizer.from_pretrained(
            _TOKENIZER_MODEL,
            trust_remote_code=False,
        )
        if not _is_tokenizer(candidate):
            raise TypeError("loaded tokenizer does not expose call and decode")
        _tokenizer = candidate
    except Exception as exc:  # pragma: no cover - offline / install-missing
        logger.warning("token_utils: tokenizer load failed (%s); fallback to char-ratio estimator", exc)
        _tokenizer = None
    return _tokenizer


def count_tokens(text: str) -> int:
    if not text:
        return 0
    tok = _get_tokenizer()
    if tok is None:
        return max(1, int(len(text) * _CJK_CHAR_RATIO))
    ids = _token_ids(tok, text)
    return len(ids)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Head-truncate text so its token count is ≤ max_tokens."""
    if max_tokens <= 0 or not text:
        return ""
    tok = _get_tokenizer()
    if tok is None:
        # char-ratio fallback: conservative upper bound on chars we can keep
        safe_chars = max(1, int(max_tokens / _CJK_CHAR_RATIO))
        return text[:safe_chars]
    ids = _token_ids(tok, text)
    if len(ids) <= max_tokens:
        return text
    return _decode_tokens(tok, ids[:max_tokens])


_PARA_SPLIT = re.compile(r"\n\s*\n+")
_SENT_SPLIT = re.compile(r"(?<=[。！？!?\.])\s+|(?<=[。！？])")


def _chunk_by_tokens(text: str, max_tokens: int) -> list[str]:
    """Fallback: cut by exact token windows when paragraph/sentence chunks still overrun."""
    tok = _get_tokenizer()
    if tok is None:
        safe_chars = max(1, int(max_tokens / _CJK_CHAR_RATIO))
        return [text[i : i + safe_chars] for i in range(0, len(text), safe_chars)] or [text]
    ids = _token_ids(tok, text)
    pieces: list[str] = []
    for i in range(0, len(ids), max_tokens):
        window = ids[i : i + max_tokens]
        pieces.append(_decode_tokens(tok, window))
    return [p for p in pieces if p] or [text]


def _pack_units(units: Iterable[str], max_tokens: int) -> list[str]:
    """Greedy: pack consecutive units into groups whose combined tokens ≤ max_tokens."""
    packed: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        n = count_tokens(unit)
        if n > max_tokens:
            if buf:
                packed.append("\n".join(buf))
                buf, buf_tokens = [], 0
            packed.extend(_chunk_by_tokens(unit, max_tokens))
            continue
        if buf_tokens + n > max_tokens and buf:
            packed.append("\n".join(buf))
            buf, buf_tokens = [], 0
        buf.append(unit)
        buf_tokens += n
    if buf:
        packed.append("\n".join(buf))
    return packed


def split_by_tokens(text: str, max_tokens: int) -> list[str]:
    """Split text so each piece has ≤ max_tokens tokens.

    Preference order: paragraph (\\n\\n) → sentence (中英句末) → fixed token window.
    """
    if max_tokens <= 0 or not text:
        return []
    if count_tokens(text) <= max_tokens:
        return [text]

    paragraphs = [p for p in _PARA_SPLIT.split(text) if p.strip()]
    if paragraphs:
        packed = _pack_units(paragraphs, max_tokens)
        if all(count_tokens(p) <= max_tokens for p in packed):
            return packed

    sentences = [s for s in _SENT_SPLIT.split(text) if s and s.strip()]
    if sentences:
        packed = _pack_units(sentences, max_tokens)
        if all(count_tokens(p) <= max_tokens for p in packed):
            return packed

    return _chunk_by_tokens(text, max_tokens)
