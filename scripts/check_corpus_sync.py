# -*- coding: utf-8 -*-
"""
Squad Readiness Check (DoD §4.1)
Role: 在执行任何推理任务前，确保环境变量与缓存语料库完全对齐。
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from dotenv import load_dotenv

def check_sync():
    load_dotenv()
    cache_manifest = Path("output/embedding_cache/corpus_embeddings_contextual.manifest.json")

    if not cache_manifest.exists():
        print("❌ ERROR: Embedding cache manifest missing. Run eval to generate.")
        return False

    try:
        manifest = json.loads(cache_manifest.read_text())
        cached_model = manifest.get("model")
        current_model = os.getenv("SILICONFLOW_EMBEDDING_MODEL")

        print(f"--- Squad Sync Audit ---")
        print(f"Cached Model:  {cached_model}")
        print(f"Current Model: {current_model}")

        if cached_model and current_model and cached_model != current_model:
            print("❌ FAIL: Model mismatch detected! Cache is stale.")
            return False

        print("✅ PASS: Ecosystem is in sync.")
        return True
    except Exception as e:
        print(f"❌ CRITICAL ERROR during sync check: {e}")
        return False

if __name__ == "__main__":
    import sys
    sys.exit(0 if check_sync() else 1)
