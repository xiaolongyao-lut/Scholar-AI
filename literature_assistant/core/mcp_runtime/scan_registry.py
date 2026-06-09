"""In-memory ``scan_id`` → ``McpPackageScanResult`` registry with TTL.

The installer looks up a scan by id, so the scanner output must outlive
the HTTP request that produced it. We hold the result for ``SCAN_ID_TTL_SECONDS``
and reject installs whose scan has expired with ``ScanExpiredError``.

Not persisted: scans are ephemeral by design. A process restart invalidates
all in-flight installs, which the frontend recovers by re-running the scanner.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from models.mcp_installation import McpPackageScanResult


class ScanNotFoundError(LookupError):
    """Unknown scan_id. Either never registered or already evicted."""


class ScanExpiredError(LookupError):
    """Scan_id was registered but has aged past SCAN_ID_TTL_SECONDS.

    Maps to HTTP ``scan_expired`` in the installer router; the frontend
    should re-run the scan rather than retry the install.
    """


class McpScanRegistry:
    """In-memory scan_id cache.

    Thread-safe: a single internal lock guards both the dict and the
    purge-expired sweep. Reads are O(1).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, McpPackageScanResult] = {}

    def register(self, result: McpPackageScanResult) -> None:
        """Store a scan result keyed by its scan_id.

        Idempotent: re-registering the same scan_id overwrites the entry
        (which only matters if the same scanner instance issued the same id
        twice — generate_scan_id uses UUID4 so this shouldn't happen in
        practice).
        """
        with self._lock:
            self._cache[result.scan_id] = result

    def get(self, scan_id: str) -> McpPackageScanResult:
        """Fetch and TTL-check a scan.

        Raises ``ScanNotFoundError`` if the id was never registered or has
        been evicted. Raises ``ScanExpiredError`` if the TTL has elapsed
        (the entry is evicted as a side effect to keep the cache bounded).
        """
        with self._lock:
            entry = self._cache.get(scan_id)
            if entry is None:
                raise ScanNotFoundError(scan_id)
            if self._is_expired(entry):
                self._cache.pop(scan_id, None)
                raise ScanExpiredError(scan_id)
            return entry

    def purge_expired(self) -> int:
        """Remove all entries past their TTL. Returns count removed.

        Cheap to call periodically (e.g. on each register / installer entry)
        to bound memory in long-running processes.
        """
        removed = 0
        with self._lock:
            stale = [sid for sid, r in self._cache.items() if self._is_expired(r)]
            for sid in stale:
                del self._cache[sid]
                removed += 1
        return removed

    def clear(self) -> None:
        """Test helper: drop all entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _is_expired(entry: McpPackageScanResult) -> bool:
        try:
            expires = datetime.fromisoformat(entry.expires_at)
        except ValueError:
            # Malformed expiry — treat as expired (defensive).
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_singleton: McpScanRegistry | None = None


def get_scan_registry() -> McpScanRegistry:
    global _singleton
    if _singleton is None:
        _singleton = McpScanRegistry()
    return _singleton


def set_scan_registry(registry: McpScanRegistry | None) -> None:
    """Test hook."""
    global _singleton
    _singleton = registry


__all__ = [
    "McpScanRegistry",
    "ScanExpiredError",
    "ScanNotFoundError",
    "get_scan_registry",
    "set_scan_registry",
]
