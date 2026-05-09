"""smoke_cache_guard.py — Phase 4.2 B-2 / 429 退避独立 smoke 工具。

不进评测链路，不拿指标，只验机制。API 代价：≤ 10 次 /embeddings 调用 + 1 次 /rerank。

用法:
    python smoke_cache_guard.py                   # 跑全部 case
    python smoke_cache_guard.py --case miss       # cache-miss 新建
    python smoke_cache_guard.py --case hit        # cache-hit 复用
    python smoke_cache_guard.py --case tamper     # manifest 篡改 → raise
    python smoke_cache_guard.py --case oversize   # 超长 chunk → split+mean-pool 不 raise
    python smoke_cache_guard.py --case no_zero_rows  # build 后 .npy 无全零行
    python smoke_cache_guard.py --case rerank     # 验 rerank retry 路径

会在 `.smoke_cache_guard/` 下建临时 cache 目录，跑完自动清理。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from chunk_vector_store import ChunkVectorStore
from reranker_client import rerank_async

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("smoke")

SMOKE_DIR = Path(".smoke_cache_guard")
CACHE_NPY = SMOKE_DIR / "smoke_embeddings.npy"
CACHE_MANIFEST = SMOKE_DIR / "smoke_embeddings.manifest.json"
OVERSIZE_NPY = SMOKE_DIR / "smoke_oversize.npy"
OVERSIZE_MANIFEST = SMOKE_DIR / "smoke_oversize.manifest.json"
MAN2011_PATH = Path("output") / "chunk_store" / "man2011_chunks.json"
N_CHUNKS = 5  # small enough to be cheap


def _load_micro_corpus() -> list[dict]:
    """Take first N_CHUNKS chunks from man2011 as smoke corpus."""
    if not MAN2011_PATH.exists():
        raise FileNotFoundError(f"smoke corpus source missing: {MAN2011_PATH}")
    data = json.loads(MAN2011_PATH.read_text(encoding="utf-8"))
    material_id = next(iter(data))
    chunks = data[material_id][:N_CHUNKS]
    if len(chunks) < N_CHUNKS:
        raise RuntimeError(f"only {len(chunks)} chunks available in {MAN2011_PATH}")
    return chunks


def _reset_smoke_dir() -> None:
    if SMOKE_DIR.exists():
        shutil.rmtree(SMOKE_DIR)
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)


async def case_miss(chunks: list[dict]) -> bool:
    """Cache miss → API build → npy + manifest written."""
    logger.info("[case_miss] cache 不存在，必须走 API 新建并落 manifest")
    _reset_smoke_dir()
    assert not CACHE_NPY.exists()
    assert not CACHE_MANIFEST.exists()

    store = await ChunkVectorStore.build(chunks, cache_path=CACHE_NPY)

    if not CACHE_NPY.exists():
        logger.error("FAIL: %s 未生成", CACHE_NPY)
        return False
    if not CACHE_MANIFEST.exists():
        logger.error("FAIL: %s 未生成", CACHE_MANIFEST)
        return False

    manifest = json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
    required = {"version", "chunk_count", "chunks_hash", "embedding_shape", "is_contextual"}
    missing = required - set(manifest)
    if missing:
        logger.error("FAIL: manifest 缺字段 %s", missing)
        return False
    if manifest["chunk_count"] != len(chunks):
        logger.error("FAIL: manifest chunk_count %s != %d", manifest["chunk_count"], len(chunks))
        return False
    if not store.has_embeddings:
        logger.error("FAIL: store.has_embeddings=False（API key 可能未配置或全 zero）")
        return False

    logger.info("PASS case_miss: manifest %s", {k: manifest[k] for k in required})
    return True


async def case_hit(chunks: list[dict]) -> bool:
    """Cache hit → manifest validated → no API call."""
    logger.info("[case_hit] cache 已存在 + manifest 有效 → 必须命中缓存不走 API")
    if not CACHE_NPY.exists() or not CACHE_MANIFEST.exists():
        logger.info("  case_hit 依赖 case_miss 的产物，先跑 case_miss")
        if not await case_miss(chunks):
            return False

    # 改 env 让 API 不可用，cache 命中就不会走 embed；cache 不命中会返回 zero embeddings
    original_key = os.environ.pop("SILICONFLOW_API_KEY", None)
    original_key2 = os.environ.pop("SILICONFLOW_EMBEDDING_API_KEY", None)
    try:
        store = await ChunkVectorStore.build(chunks, cache_path=CACHE_NPY)
    finally:
        if original_key is not None:
            os.environ["SILICONFLOW_API_KEY"] = original_key
        if original_key2 is not None:
            os.environ["SILICONFLOW_EMBEDDING_API_KEY"] = original_key2

    if not store.has_embeddings:
        logger.error("FAIL: has_embeddings=False，说明 cache 未命中（退化到 zero 向量）")
        return False
    logger.info("PASS case_hit: cache 命中，manifest 校验通过，未调用 API")
    return True


async def case_tamper(chunks: list[dict]) -> bool:
    """Manifest content hash tampered → build must raise ValueError."""
    logger.info("[case_tamper] 篡改 manifest.chunks_hash → build 必须 raise")
    if not CACHE_MANIFEST.exists():
        logger.info("  tamper 依赖 case_miss 产物，先跑 case_miss")
        if not await case_miss(chunks):
            return False

    manifest = json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
    original_hash = manifest["chunks_hash"]
    manifest["chunks_hash"] = "0" * 64  # 篡改
    CACHE_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    try:
        await ChunkVectorStore.build(chunks, cache_path=CACHE_NPY)
    except ValueError as exc:
        logger.info("PASS case_tamper: 如预期 raise ValueError: %s", exc)
        # 复原 manifest，避免污染后续 case
        manifest["chunks_hash"] = original_hash
        CACHE_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as exc:  # pragma: no cover
        logger.error("FAIL case_tamper: 预期 ValueError，实际 %s: %s", type(exc).__name__, exc)
        return False

    logger.error("FAIL case_tamper: 未 raise，manifest 硬门禁失效")
    return False


async def case_rerank(chunks: list[dict]) -> bool:
    """Rerank path smoke：确认 429 退避链路可走通（正常响应即可，不强求触发 429）。"""
    logger.info("[case_rerank] 调一次 rerank，验证 retry/backoff 代码路径不炸")
    api_key = os.getenv("SILICONFLOW_RERANK_API_KEY")
    if not api_key:
        logger.warning("SKIP case_rerank: SILICONFLOW_RERANK_API_KEY 未配置")
        return True  # 不 FAIL，只跳过

    candidates = [
        dict(c, rrf_score=1.0 / (i + 1)) for i, c in enumerate(chunks)
    ]
    timings: dict[str, float] = {}
    out = await rerank_async(
        "激光焊接钛合金",
        candidates,
        top_k=3,
        timings=timings,
    )
    if not out:
        logger.error("FAIL case_rerank: rerank 返回空列表")
        return False
    logger.info(
        "PASS case_rerank: top_k=%d, timings=%s",
        len(out),
        {k: round(v, 2) if isinstance(v, float) else v for k, v in timings.items()},
    )
    return True


def _build_oversize_chunks(base_chunks: list[dict]) -> list[dict]:
    """Return 5 chunks with 1 synthetic oversized chunk (> 8192 tokens)."""
    oversized_text = "激光焊接钛合金的微观组织与力学性能研究。" * 1000  # ~14k tokens
    oversize_chunk = {
        "chunk_id": "smoke_oversize_0",
        "content": oversized_text,
    }
    # Keep 4 regular chunks to make the corpus non-trivial.
    return [oversize_chunk, *base_chunks[:4]]


async def case_oversize(chunks: list[dict]) -> bool:
    """超长 chunk：split+mean-pool 必须让 build 成功，且对应行非零。"""
    logger.info("[case_oversize] 构造 >8192 token 的 chunk → build 不应 raise，对应行非零")
    _reset_smoke_dir()

    oversize_chunks = _build_oversize_chunks(chunks)
    try:
        store = await ChunkVectorStore.build(oversize_chunks, cache_path=OVERSIZE_NPY)
    except Exception as exc:
        logger.error("FAIL case_oversize: build raised %s: %s", type(exc).__name__, exc)
        return False

    if not OVERSIZE_NPY.exists() or not OVERSIZE_MANIFEST.exists():
        logger.error("FAIL case_oversize: %s 或 manifest 未生成", OVERSIZE_NPY)
        return False
    if not store.has_embeddings:
        logger.error("FAIL case_oversize: store.has_embeddings=False")
        return False

    arr = np.load(str(OVERSIZE_NPY))
    if arr.shape[0] != len(oversize_chunks):
        logger.error("FAIL case_oversize: shape[0] %d != %d", arr.shape[0], len(oversize_chunks))
        return False
    oversize_row_zero = bool(np.all(arr[0] == 0))
    if oversize_row_zero:
        logger.error("FAIL case_oversize: 超长 chunk 对应的 row 0 全零（split+mean-pool 失效）")
        return False

    manifest = json.loads(OVERSIZE_MANIFEST.read_text(encoding="utf-8"))
    logger.info(
        "PASS case_oversize: manifest=%s, row0_norm=%.4f",
        {k: manifest.get(k) for k in ("chunk_count", "zero_row_count", "embedding_shape")},
        float(np.linalg.norm(arr[0])),
    )
    return True


async def case_no_zero_rows(chunks: list[dict]) -> bool:
    """紧接 case_oversize 的产物 → .npy 不允许任何全零行。"""
    logger.info("[case_no_zero_rows] 读 oversize 产物，断言无全零行")
    if not OVERSIZE_NPY.exists():
        logger.info("  依赖 case_oversize，先跑")
        if not await case_oversize(chunks):
            return False

    arr = np.load(str(OVERSIZE_NPY))
    zero_rows = int(np.sum((arr == 0).all(axis=1)))
    if zero_rows > 0:
        logger.error("FAIL case_no_zero_rows: %d/%d 行全零", zero_rows, arr.shape[0])
        return False

    manifest = json.loads(OVERSIZE_MANIFEST.read_text(encoding="utf-8"))
    manifest_zero_rows = manifest.get("zero_row_count")
    if manifest_zero_rows != 0:
        logger.error("FAIL case_no_zero_rows: manifest.zero_row_count=%s != 0", manifest_zero_rows)
        return False

    logger.info("PASS case_no_zero_rows: %d 行全部非零，manifest.zero_row_count=0", arr.shape[0])
    return True


CASES = {
    "miss": case_miss,
    "hit": case_hit,
    "tamper": case_tamper,
    "oversize": case_oversize,
    "no_zero_rows": case_no_zero_rows,
    "rerank": case_rerank,
}


async def run(cases: list[str], cleanup: bool) -> int:
    chunks = _load_micro_corpus()
    logger.info("smoke corpus: %d chunks from %s", len(chunks), MAN2011_PATH)

    results: dict[str, bool] = {}
    for name in cases:
        logger.info("─" * 60)
        try:
            results[name] = await CASES[name](chunks)
        except Exception as exc:  # pragma: no cover
            logger.exception("FAIL %s: %s", name, exc)
            results[name] = False

    logger.info("─" * 60)
    for name, ok in results.items():
        logger.info("%s  %s", "PASS" if ok else "FAIL", name)

    if cleanup and SMOKE_DIR.exists():
        shutil.rmtree(SMOKE_DIR)
        logger.info("cleaned %s", SMOKE_DIR)

    return 0 if all(results.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=[*CASES.keys(), "all"],
        default="all",
        help="跑某个 case（默认 all）",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="跑完保留 .smoke_cache_guard/ 目录，便于手动 inspect",
    )
    args = parser.parse_args()

    cases = ["miss", "hit", "tamper", "oversize", "no_zero_rows", "rerank"] if args.case == "all" else [args.case]
    return asyncio.run(run(cases, cleanup=not args.keep))


if __name__ == "__main__":
    sys.exit(main())
