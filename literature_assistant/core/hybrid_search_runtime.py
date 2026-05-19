from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from layers.r_layer_hybrid_retriever import bm25_rank


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump_json(obj: Any, path: str | Path) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def run_hybrid_retrieval(bound_or_analysis: dict[str, Any], goal: str, topk: int = 20) -> dict[str, Any]:
    chunks = bound_or_analysis.get('chunks', [])
    ranked_chunks = bm25_rank(chunks, goal=goal, text_key='text')
    selected = ranked_chunks[:topk]
    return {
        'status': 'hybrid_retrieval_ready',
        'goal': goal,
        'topk': topk,
        'ranked_chunks': ranked_chunks,
        'selected_chunks': selected,
        'stats': {
            'chunk_count': len(chunks),
            'ranked_chunk_count': len(ranked_chunks),
            'selected_chunk_count': len(selected),
        },
    }


class HybridSearchRuntime:
    """Legacy synchronous project chunk-search facade.

    The class preserves the historical test contract while delegating to the
    current Resources router search helper so migration does not fork ranking
    behavior.
    """

    def search(self, query: str, project_id: str, top_k: int = 10) -> dict[str, Any]:
        """Search project chunks and return the legacy `hits` envelope."""
        normalized_query = str(query or "").strip()
        normalized_project_id = str(project_id or "").strip()
        if not normalized_query:
            raise ValueError("query must be a non-empty string")
        if not normalized_project_id:
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")

        from routers.resources_router import _search_chunks_hybrid

        hits = _search_chunks_hybrid(
            query=normalized_query,
            project_id=normalized_project_id,
            top_k=top_k,
        )
        return {
            "status": "ok",
            "query": normalized_query,
            "project_id": normalized_project_id,
            "hits": hits,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description='基于 BM25+关键词重叠的混合检索。')
    parser.add_argument('input_json', help='输入 JSON（建议 02 图文绑定输出）')
    parser.add_argument('output_json', help='输出 JSON')
    parser.add_argument('--goal', required=True, help='检索目标')
    parser.add_argument('--topk', type=int, default=20)
    args = parser.parse_args()

    data = load_json(args.input_json)
    out = run_hybrid_retrieval(data, goal=args.goal, topk=args.topk)
    dump_json(out, args.output_json)
    print(json.dumps(out['stats'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
