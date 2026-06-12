# -*- coding: utf-8 -*-
"""Local rerank HTTP server — loopback fallback for the main retriever.

Architecture(per GPT review 2026-06-12):
  - **Independent process** — do NOT load the HF model in the FastAPI main
    process. Main process talks to this server through HTTP API.
  - **Loopback only by default** — binds 127.0.0.1, NOT 0.0.0.0.
  - **Compatible request schema** — accepts both
    SiliconFlow-style ``{"model":"...","query":"...","documents":[...]}``
    and DashScope-native rerank shapes the main retriever already speaks.
  - **Reuses ``local_rerank_adapter``** — model loading / scoring code stays
    in one place; this server is the HTTP wrapper.

Usage:
    python literature_assistant/core/local_rerank_server.py [--port 7997]

Health:
    GET  http://127.0.0.1:7997/health   → {"status":"ok","model":"..."}
    POST http://127.0.0.1:7997/rerank   → SiliconFlow-style response

Then configure in Settings / .env:
    RERANK_BASE_URL=http://127.0.0.1:7997
    (the reranker_client appends /rerank — see resolve_rerank_request_url)

Production hook-up:
  1. Start this server as a separate process (systemd / pm2 / Windows service)
  2. Point ``RERANK_BASE_URL`` at the loopback URL
  3. provider_endpoint_policy already passes loopback HTTP under
     ``allow_loopback_http=True`` (verified 2026-06-12)
  4. When cloud API DNS is hijacked by VPN fake-IP, this server keeps working
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Make the adapter importable when run as `python <file>`
sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger("local_rerank_server")


# Pydantic schemas at module scope — pydantic v2 ForwardRef resolution requires
# this when used as FastAPI body parameters (in-function definitions fail).
try:
    from pydantic import BaseModel, Field
except ImportError:
    BaseModel = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]


if BaseModel is not None:
    class RerankRequest(BaseModel):
        # SiliconFlow / OpenAI-style schema — what reranker_client sends
        model: str = Field(default="", description="Model name (echoed back).")
        query: str = Field(..., description="User query.")
        documents: list[str] = Field(..., description="Candidate texts to score.")
        top_n: int | None = Field(default=None, description="Optional truncation.")
        return_documents: bool = Field(default=False)

    class RerankResultItem(BaseModel):
        index: int
        relevance_score: float
        document: dict[str, str] | None = None

    class RerankResponse(BaseModel):
        id: str
        model: str
        results: list[RerankResultItem]
        meta: dict[str, Any] | None = None


def _build_app():
    """Build the FastAPI app lazily so this module can be imported for tests
    without forcing the FastAPI dep to load."""
    try:
        from fastapi import FastAPI, HTTPException, Body
    except ImportError as exc:
        raise RuntimeError(
            "local_rerank_server requires fastapi + pydantic. "
            "Install with: pip install fastapi uvicorn pydantic"
        ) from exc

    import local_rerank_adapter as lra

    app = FastAPI(
        title="Local Rerank Server",
        version="1.0.0",
        description="loopback fallback for cloud rerank APIs (DashScope/SiliconFlow)",
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok" if lra.is_available() else "degraded",
            "model": os.environ.get("LOCAL_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3"),
            "adapter_available": lra.is_available(),
        }

    @app.post("/rerank", response_model=RerankResponse)
    async def rerank(req: RerankRequest = Body(...)) -> RerankResponse:
        if not req.documents:
            return RerankResponse(id="empty", model=req.model, results=[])

        scores = await lra.ascore_pairs(req.query, req.documents)
        if scores is None:
            raise HTTPException(
                status_code=503,
                detail="local rerank model unavailable (weights missing or disabled)",
            )

        items: list[RerankResultItem] = []
        for i, s in enumerate(scores):
            item = RerankResultItem(index=i, relevance_score=float(s))
            if req.return_documents:
                item.document = {"text": req.documents[i]}
            items.append(item)
        items.sort(key=lambda x: x.relevance_score, reverse=True)
        if req.top_n is not None and req.top_n > 0:
            items = items[: req.top_n]

        return RerankResponse(
            id="local-rerank",
            model=req.model or os.environ.get("LOCAL_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3"),
            results=items,
            meta={"engine": "local_cross_encoder", "scored": len(scores)},
        )

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Local rerank HTTP server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind host (default: 127.0.0.1, loopback only)")
    parser.add_argument("--port", type=int, default=7997,
                        help="Bind port (default: 7997)")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    args = parser.parse_args()

    # Hard guard: refuse non-loopback bind unless caller passes a public flag
    if args.host not in ("127.0.0.1", "::1", "localhost") and not os.environ.get("LOCAL_RERANK_ALLOW_NON_LOOPBACK"):
        logger.error(
            "local_rerank_server: refusing to bind %s (non-loopback). "
            "Set LOCAL_RERANK_ALLOW_NON_LOOPBACK=1 if you know what you're doing.",
            args.host,
        )
        return 2

    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn not installed: pip install uvicorn")
        return 3

    app = _build_app()
    logger.info("starting local_rerank_server on http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
