"""Tokenizer helpers shared by embedding / rerank length guards.

Uses a BGE-m3 (XLM-R family) tokenizer as a **conservative** token estimator —
BGE-m3 tokenizes Chinese tighter than most SentencePiece/BBPE variants, so the
produced counts overestimate for looser tokenizers like Qwen3's BBPE. That is
the safe side: if the guard says "fits", it almost surely fits downstream.

Falls back to `len(text) * 0.75` when the HF tokenizer can't be loaded (offline
first-run, firewalled runners, etc.) — a measured CJK char→token ratio.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

_TOKENIZER_MODEL = "BAAI/bge-m3"
_CJK_CHAR_RATIO = 0.75  # conservative lower bound for Chinese-heavy text

_tokenizer = None
_tokenizer_loaded = False


def _get_tokenizer():
    global _tokenizer, _tokenizer_loaded
    if _tokenizer_loaded:
        return _tokenizer
    _tokenizer_loaded = True
    try:
        from transformers import AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained(_TOKENIZER_MODEL, trust_remote_code=False)
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
    ids = tok(text, add_special_tokens=False, truncation=False)["input_ids"]
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
    ids = tok(text, add_special_tokens=False, truncation=False)["input_ids"]
    if len(ids) <= max_tokens:
        return text
    return tok.decode(ids[:max_tokens], skip_special_tokens=True).strip()


_PARA_SPLIT = re.compile(r"\n\s*\n+")
_SENT_SPLIT = re.compile(r"(?<=[。！？!?\.])\s+|(?<=[。！？])")


def _chunk_by_tokens(text: str, max_tokens: int) -> list[str]:
    """Fallback: cut by exact token windows when paragraph/sentence chunks still overrun."""
    tok = _get_tokenizer()
    if tok is None:
        safe_chars = max(1, int(max_tokens / _CJK_CHAR_RATIO))
        return [text[i : i + safe_chars] for i in range(0, len(text), safe_chars)] or [text]
    ids = tok(text, add_special_tokens=False, truncation=False)["input_ids"]
    pieces: list[str] = []
    for i in range(0, len(ids), max_tokens):
        window = ids[i : i + max_tokens]
        pieces.append(tok.decode(window, skip_special_tokens=True).strip())
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
