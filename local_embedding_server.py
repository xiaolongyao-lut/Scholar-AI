"""Reference implementation: minimal OpenAI-compatible /v1/embeddings server.

This is a **reference script** showing how to expose a local embedding service
that the desktop App can consume when the upstream API (SiliconFlow / DashScope)
is unreachable. It is NOT the only supported deployment — the App talks to any
service that implements the OpenAI /v1/embeddings protocol (infinity, TEI,
your own FastAPI, etc).

If you only need the **in-process** fallback (no separate server) the app
already does that via ``literature_assistant/core/local_embedding_adapter.py``
on every embedding call — no need to start anything. This script is for the
case where you want a dedicated embedding service shared across processes /
machines.

Run (single line, Windows cmd / PowerShell / *nix shell):
    python local_embedding_server.py
    python local_embedding_server.py --model BAAI/bge-m3 --port 7998
    python local_embedding_server.py --model "D:\\path\\to\\bge-m3"
"""
from __future__ import annotations

import argparse
import os
from typing import List, Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

# Default resolves at runtime: LOCAL_EMBEDDING_MODEL env > HuggingFace model id.
# Local filesystem paths are user-supplied via --model or the env var; this
# script ships no machine-specific defaults.
DEFAULT_MODEL = os.environ.get("LOCAL_EMBEDDING_MODEL") or "BAAI/bge-m3"


class EmbedRequest(BaseModel):
    model: Optional[str] = None
    input: List[str]
    encoding_format: Optional[str] = "float"
    dimensions: Optional[int] = None


class EmbedItem(BaseModel):
    object: str = "embedding"
    index: int
    embedding: List[float]


class EmbedUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbedResponse(BaseModel):
    object: str = "list"
    data: List[EmbedItem]
    model: str
    usage: EmbedUsage


def build_app(model_path: str, default_device: str | None = None) -> FastAPI:
    app = FastAPI(title="Local BGE Embedding Server")
    encoder = SentenceTransformer(model_path, device=default_device)

    @app.post("/v1/embeddings", response_model=EmbedResponse)
    def embeddings(req: EmbedRequest) -> EmbedResponse:
        vecs = encoder.encode(
            req.input,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        target = req.dimensions or vecs.shape[1]
        items = [
            EmbedItem(index=i, embedding=v.tolist()[:target])
            for i, v in enumerate(vecs)
        ]
        return EmbedResponse(
            data=items,
            model=req.model or model_path,
            usage=EmbedUsage(prompt_tokens=0, total_tokens=0),
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model": model_path}

    return app


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--port", type=int, default=7998)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument(
        "--device",
        default=None,
        help="Force device (cpu / cuda / cuda:0). Default: auto-detect.",
    )
    args = p.parse_args()
    print(f"[local-embedding] loading model: {args.model}")
    print(
        f"[local-embedding] listening on "
        f"http://{args.host}:{args.port}/v1/embeddings"
    )
    uvicorn.run(build_app(args.model, default_device=args.device), host=args.host, port=args.port)
