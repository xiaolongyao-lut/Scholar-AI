from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-']+")
CN_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

STOPWORDS = {
    'the','and','for','with','that','this','from','were','was','are','into','under','than','when','where','while','been','their','which',
    'using','used','study','results','result','paper','article','analysis','different','effect','effects','based','shown','show','shows','figure',
    'table','weld','laser','steel','alloy','material','materials','sample','samples','data','method','methods','process','processed',
    'significant','significantly','provide','provides','revealed','reveal','found','indicate','indicates','performed','page','journal'
}

GOAL_MAP = {
    '工艺参数': ['parameter', 'parameters', 'power', 'speed', 'frequency', 'heat input', 'composition', 'ratio', 'modulation', 'welding direction'],
    '熔池流动': ['molten pool', 'flow', 'convection', 'dynamics', 'keyhole', 'spatter'],
    '氮传输': ['nitrogen', 'nitriding', 'nitride', 'tin', 'transfer', 'transport'],
    '组织': ['microstructure', 'grain', 'phase', 'precipitate', 'texture', 'dendrite', 'equiaxed', 'columnar'],
    '应力': ['stress', 'residual stress', 'tensile', 'compressive'],
    '性能': ['hardness', 'wear', 'corrosion', 'tensile', 'mechanical', 'friction', 'performance', 'accuracy'],
}


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\xa0', ' ')).strip()


def en_tokens(text: str) -> list[str]:
    return [t.lower() for t in EN_TOKEN_RE.findall(text or '') if t.lower() not in STOPWORDS]


def cn_tokens(text: str) -> list[str]:
    return [t for t in CN_TOKEN_RE.findall(text or '')]


def expand_goal_terms(goal: str) -> tuple[Counter, list[str]]:
    goal = normalize_text(goal)
    phrase_terms: list[str] = []
    raw_terms = en_tokens(goal) + [t.lower() for t in cn_tokens(goal)]
    for cn, mapped in GOAL_MAP.items():
        if cn in goal:
            phrase_terms.extend(mapped)
            raw_terms.append(cn.lower())
    weights = Counter(raw_terms)
    for p in phrase_terms:
        weights[p.lower()] += 2
    return weights, sorted(set(phrase_terms))


def _score_overlap(text: str, goal_terms: Counter, phrase_terms: list[str]) -> float:
    low = text.lower()
    score = 0.0
    tok_counts = Counter(en_tokens(text) + [t.lower() for t in cn_tokens(text)])
    for term, weight in goal_terms.items():
        if ' ' in term:
            if term in low:
                score += 2.0 * weight
        else:
            if tok_counts.get(term, 0):
                score += min(tok_counts[term], 3) * 0.9 * weight
    for phrase in phrase_terms:
        if phrase.lower() in low:
            score += 1.6
    return score


def _bm25_manual(query_terms: list[str], docs_terms: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n_docs = len(docs_terms)
    if n_docs == 0:
        return []
    avgdl = sum(len(d) for d in docs_terms) / max(1, n_docs)
    df: dict[str, int] = defaultdict(int)
    for terms in docs_terms:
        for t in set(terms):
            df[t] += 1

    scores: list[float] = [0.0] * n_docs
    for i, doc in enumerate(docs_terms):
        tf = Counter(doc)
        dl = len(doc)
        for q in query_terms:
            if q not in tf:
                continue
            idf = math.log(1 + (n_docs - df.get(q, 0) + 0.5) / (df.get(q, 0) + 0.5))
            num = tf[q] * (k1 + 1)
            den = tf[q] + k1 * (1 - b + b * (dl / max(avgdl, 1e-6)))
            scores[i] += idf * (num / max(den, 1e-6))
    return scores


def bm25_rank(chunks: list[dict[str, Any]], goal: str, text_key: str = 'text') -> list[dict[str, Any]]:
    goal_terms, phrase_terms = expand_goal_terms(goal)
    query_terms = list(goal_terms.keys())
    docs_terms = [en_tokens(c.get(text_key, '')) + [t.lower() for t in cn_tokens(c.get(text_key, ''))] for c in chunks]

    try:
        from rank_bm25 import BM25Okapi  # type: ignore
        bm25 = BM25Okapi(docs_terms)
        bm25_scores = bm25.get_scores(query_terms)
    except Exception:
        bm25_scores = _bm25_manual(query_terms, docs_terms)

    max_bm25 = max(bm25_scores) if len(bm25_scores) > 0 else 1.0
    ranked = []
    for chunk, bm25_s in zip(chunks, bm25_scores):
        overlap = _score_overlap(chunk.get(text_key, ''), goal_terms, phrase_terms)
        bm25_norm = (bm25_s / max_bm25) if max_bm25 > 0 else 0.0
        score = min(1.0, 0.65 * bm25_norm + 0.35 * min(overlap / 12.0, 1.0))
        item = dict(chunk)
        item['hybrid_score'] = round(score, 4)
        item['bm25_score'] = float(bm25_s)
        item['overlap_score'] = round(overlap, 4)
        ranked.append(item)

    ranked.sort(key=lambda x: x['hybrid_score'], reverse=True)
    return ranked


def hybrid_search(raw_extract: dict[str, Any], query: str, top_k: int = 12) -> list[dict[str, Any]]:
    """R-Layer entry point: Executes hybrid BM25 + keyword overlap search."""
    chunks = raw_extract.get('chunks', [])
    if not chunks:
        return []
        
    # Performs BM25 ranking internally
    results = bm25_rank(chunks, query)
    return results[:top_k]
