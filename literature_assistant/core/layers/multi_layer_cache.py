import hashlib
import json
import time
import os
import sqlite3
import logging
from typing import Any, Dict, Optional, List, Tuple
from collections import OrderedDict

logger = logging.getLogger("MultiLayerCache")

class QueryFingerprint:
    """查询指纹生成器：确保语义一致的查询命中同一缓存键。"""
    @staticmethod
    def generate(query: str, focus_keywords: List[str] = None, domain: str = "general") -> str:
        factors = {
            "query": " ".join(query.lower().split()).strip(),
            "focus": sorted(focus_keywords or []),
            "domain": domain,
            "v": "2.0" # 缓存协议版本
        }
        factors_json = json.dumps(factors, sort_keys=True)
        return hashlib.md5(factors_json.encode()).hexdigest()

class L1ProcessCache:
    """L1: 进程内内存缓存 (LRU + TTL)"""
    def __init__(self, max_size_mb: int = 50, ttl_seconds: int = 600):
        self.cache = OrderedDict() # key -> (value, expiry)
        self.max_size = max_size_mb * 1024 * 1024
        self.ttl = ttl_seconds
        self.current_size = 0

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None
        val, expiry = self.cache[key]
        if time.time() > expiry:
            self.delete(key)
            return None
        self.cache.move_to_end(key)
        return val

    def set(self, key: str, value: Any):
        if key in self.cache:
            self.delete(key)
        
        val_size = len(json.dumps(value).encode())
        while self.current_size + val_size > self.max_size and self.cache:
            self.pop_oldest()
            
        self.cache[key] = (value, time.time() + self.ttl)
        self.current_size += val_size

    def delete(self, key: str):
        if key in self.cache:
            val, _ = self.cache.pop(key)
            self.current_size -= len(json.dumps(val).encode())

    def pop_oldest(self):
        key, (val, _) = self.cache.popitem(last=False)
        self.current_size -= len(json.dumps(val).encode())

class L2SQLiteCache:
    """L2: SQLite 持久化缓存 (支持检索/评分结果存储)"""
    def __init__(self, db_path: str = ".cache/query_vault.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS universal_cache (
                    fingerprint TEXT PRIMARY KEY,
                    query_text TEXT,
                    result_json TEXT,
                    hit_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ttl_seconds INTEGER DEFAULT 86400
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_hit ON universal_cache(hit_count)")

    def get(self, key: str) -> Optional[Any]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT result_json, accessed_at, ttl_seconds FROM universal_cache WHERE fingerprint = ?", (key,)
                )
                row = cur.fetchone()
                if row:
                    # 简单 TTL 校验
                    # (此处可根据需求实现更复杂的清理逻辑)
                    conn.execute("UPDATE universal_cache SET hit_count = hit_count + 1, accessed_at = CURRENT_TIMESTAMP WHERE fingerprint = ?", (key,))
                    return json.loads(row["result_json"])
                return None
        except Exception as e:
            logger.debug(f"L2 读取异常: {e}")
            return None

    def set(self, key: str, query: str, result: Any, ttl: int = 86400):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO universal_cache (fingerprint, query_text, result_json, ttl_seconds) VALUES (?, ?, ?, ?)",
                    (key, query, json.dumps(result, ensure_ascii=False), ttl)
                )
            # 随机触发容量清理
            import random
            if random.random() < 0.05:
                self.prune()
        except Exception as e:
            logger.error(f"L2 写入异常: {e}")

    def prune(self, max_records: int = 5000):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM universal_cache WHERE fingerprint NOT IN (SELECT fingerprint FROM universal_cache ORDER BY accessed_at DESC, hit_count DESC LIMIT ?)",
                    (max_records,)
                )
                conn.execute("DELETE FROM universal_cache WHERE strftime('%s', 'now') - strftime('%s', accessed_at) > ttl_seconds")
        except Exception as e:
            logger.error(f"L2 容量清理异常: {e}")

class MultiLayerCacheManager:
    """三层缓存管理器：统筹 L1/L2/L3 调度。"""
    def __init__(self, mempalace_adapter=None):
        self.l1 = L1ProcessCache()
        self.l2 = L2SQLiteCache()
        self.l3 = mempalace_adapter # L3 MemPalace 适配器 (如果有)
        self.stats = {"hits": 0, "misses": 0, "l1": 0, "l2": 0, "l3": 0}

    async def fetch(self, query: str, focus: List[str] = None, domain: str = "general") -> Optional[Any]:
        key = QueryFingerprint.generate(query, focus, domain)
        
        # 1. 尝试 L1
        res = self.l1.get(key)
        if res:
            self.stats["hits"] += 1; self.stats["l1"] += 1
            return res
        
        # 2. 尝试 L2
        res = self.l2.get(key)
        if res:
            self.stats["hits"] += 1; self.stats["l2"] += 1
            self.l1.set(key, res) # 回填 L1
            return res

        # 3. 尝试 L3 (如果有)
        if self.l3:
            try:
                l3_res = self.l3.search(query=query, wing="research_assistant", room=domain, limit=1)
                if getattr(l3_res, 'available', False) and l3_res.results:
                    top_hit = l3_res.results[0]
                    # 置信度阈值验证，避免语义漂移的错误命中
                    if top_hit.similarity >= 0.85:
                        self.stats["hits"] += 1; self.stats["l3"] += 1
                        try:
                            val = json.loads(top_hit.text)
                        except Exception:
                            val = top_hit.text
                        self.l2.set(key, query, val)
                        self.l1.set(key, val)
                        return val
            except Exception as e:
                logger.error(f"L3 读取异常: {e}")

        self.stats["misses"] += 1
        return None

    async def commit(self, query: str, result: Any, focus: List[str] = None, domain: str = "general", confidence: float = 1.0):
        key = QueryFingerprint.generate(query, focus, domain)
        self.l1.set(key, result)
        self.l2.set(key, query, result)
        # 高价值结果逻辑 (如 confidence > 0.8) 可在此触发 L3 永久化
        if self.l3 and confidence >= 0.85:
            try:
                content_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
                self.l3.add_memory(
                    wing="research_assistant",
                    room=domain,
                    content=content_str,
                    source_file="L3_cache_transfer",
                    added_by="multi_layer_cache"
                )
            except Exception as e:
                logger.error(f"L3 写入异常: {e}")
