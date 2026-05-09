from __future__ import annotations


def test_happy_path_small_corpus_requires_public_retrieve_then_rerank_wrapper() -> None:
    """R5 Option B contract: expose a thin public wrapper in eval_retrieval_runtime."""
    import eval_retrieval_runtime as runtime

    wrapper = getattr(runtime, "retrieve_then_rerank", None)
    assert callable(wrapper), (
        "missing public retrieve_then_rerank(query_text, corpus, top_k, ...): "
        "R5 Option B requires a thin formal wrapper in eval_retrieval_runtime.py"
    )
