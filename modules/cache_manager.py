"""
Cache Manager Module

Provides in-memory caching with:
- TTL (time-to-live) support
- Statistics tracking
- Hit/miss rates
- Automatic eviction
"""

import hashlib
import time
from typing import Any, Dict, Optional, Callable
from collections import OrderedDict
from threading import Lock
from modules.logger_config import get_logger

logger = get_logger("scoring_system.cache")


class CacheEntry:
    """Internal cache entry with metadata"""

    def __init__(self, value: Any, ttl: Optional[int] = None):
        """
        Initialize cache entry

        Args:
            value: Value to cache
            ttl: Time-to-live in seconds (None for no expiration)
        """
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.access_count = 0

    def is_expired(self) -> bool:
        """Check if entry has expired"""
        if self.ttl is None:
            return False
        elapsed = time.time() - self.created_at
        return elapsed > self.ttl

    def touch(self):
        """Record access for LRU tracking"""
        self.access_count += 1


class CacheManager:
    """Simple in-memory cache with TTL and statistics"""

    def __init__(self, max_size: int = 10000, ttl_seconds: Optional[int] = 3600):
        """
        Initialize cache manager

        Args:
            max_size: Maximum number of items to cache
            ttl_seconds: Default TTL for entries in seconds
        """
        self.max_size = max_size
        self.default_ttl = ttl_seconds
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = Lock()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "sets": 0}

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value from cache

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self.lock:
            if key not in self.cache:
                self.stats["misses"] += 1
                return None

            entry = self.cache[key]

            # Check expiration
            if entry.is_expired():
                del self.cache[key]
                self.stats["misses"] += 1
                logger.debug(f"Cache entry expired: {key}")
                return None

            # Update LRU order
            self.cache.move_to_end(key)
            entry.touch()
            self.stats["hits"] += 1

            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Store value in cache

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        ttl = ttl if ttl is not None else self.default_ttl

        with self.lock:
            # Remove old entry if exists
            if key in self.cache:
                del self.cache[key]

            # Check size and evict if necessary
            while len(self.cache) >= self.max_size:
                evicted_key, _ = self.cache.popitem(last=False)
                self.stats["evictions"] += 1
                logger.debug(f"Cache evicted (LRU): {evicted_key}")

            # Add new entry
            self.cache[key] = CacheEntry(value, ttl)
            self.stats["sets"] += 1

    def delete(self, key: str) -> bool:
        """
        Delete entry from cache

        Args:
            key: Cache key

        Returns:
            True if entry was deleted, False if not found
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries"""
        with self.lock:
            self.cache.clear()
            logger.info("Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dictionary with cache stats
        """
        with self.lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = (
                self.stats["hits"] / total_requests if total_requests > 0 else 0
            )

            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_rate": round(hit_rate, 4),
                "evictions": self.stats["evictions"],
                "total_sets": self.stats["sets"],
            }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return f"CacheManager(size={stats['size']}/{self.max_size}, hit_rate={stats['hit_rate']})"


class HashableCache:
    """Helper for caching with complex keys"""

    @staticmethod
    def make_key(*args, **kwargs) -> str:
        """
        Create consistent hashable key from arguments

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Hashable key string
        """
        import json

        key_data = {"args": args, "kwargs": sorted(kwargs.items())}
        key_str = json.dumps(key_data, default=str, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    @staticmethod
    def text_key(text: str) -> str:
        """Create consistent key from text content"""
        # Normalize text (remove extra whitespace)
        normalized = " ".join(text.split())
        return hashlib.md5(normalized.encode()).hexdigest()


def cached(cache: CacheManager, ttl: Optional[int] = None):
    """
    Decorator for caching function results

    Usage:
        @cached(cache_instance, ttl=3600)
        def expensive_function(text):
            return classify_evidence(text)
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            # Create cache key
            key = HashableCache.make_key(*args, **kwargs)

            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                return result

            # Compute and cache result
            result = func(*args, **kwargs)
            cache.set(key, result, ttl=ttl)

            return result

        wrapper.__wrapped__ = func
        return wrapper

    return decorator


# Global cache instance
_default_cache: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """Get or create global cache instance"""
    global _default_cache
    if _default_cache is None:
        _default_cache = CacheManager(max_size=10000, ttl_seconds=3600)
        logger.info("Created global cache instance")
    return _default_cache
