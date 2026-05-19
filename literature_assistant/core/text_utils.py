"""Text helpers for retrieval-oriented tokenization."""

from __future__ import annotations

import re


_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def _flush_segment(tokens: list[str], segment: list[str], is_cjk: bool) -> None:
    text = "".join(segment)
    if not text:
        return
    if is_cjk:
        if len(text) == 1:
            tokens.append(text)
            return
        tokens.extend(text[index:index + 2] for index in range(len(text) - 1))
        return
    tokens.extend(_WORD_RE.findall(text))


def cjk_aware_tokenize(text: str) -> list[str]:
    """对 CJK 字符按 2-gram 拆分，对 ASCII 按空白拆分；保留原顺序，去重交给上层。"""
    tokens: list[str] = []
    segment: list[str] = []
    in_cjk: bool | None = None

    for char in text or "":
        is_cjk = bool(_CJK_CHAR_RE.fullmatch(char))
        if in_cjk is None:
            segment.append(char)
            in_cjk = is_cjk
            continue
        if is_cjk == in_cjk:
            segment.append(char)
            continue
        _flush_segment(tokens, segment, in_cjk)
        segment = [char]
        in_cjk = is_cjk

    if segment:
        _flush_segment(tokens, segment, bool(in_cjk))

    return tokens
