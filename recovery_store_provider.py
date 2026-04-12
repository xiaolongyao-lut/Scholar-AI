# -*- coding: utf-8 -*-
"""
Harness V2 Phase H3: Shared Recovery Store Provider

Provides singleton-like access to shared, persistent event and fact stores
used by recovery CLI, workflows, and APIs.

Design:
- Stores are initialized once per process on first access
- All recovery operations share the same event/fact stores
- Database paths are configurable via environment or defaults
- Thread-safe lazy initialization with module-level caching
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from canonical_event_store import CanonicalEventStore, HarnessStore, create_integrated_store
from memory_fact_store import MemoryFactStore, create_default_fact_store

logger = logging.getLogger("RecoveryStoreProvider")

# Module-level cache for shared store instances
_event_store: Optional[CanonicalEventStore] = None
_fact_store: Optional[MemoryFactStore] = None
_harness_store: Optional[HarnessStore] = None

# Configuration from environment
_event_store_db = os.environ.get("RECOVERY_EVENT_DB", "harness_state.db")
_fact_store_db = os.environ.get("RECOVERY_FACT_DB", "harness_facts.db")


def get_event_store() -> CanonicalEventStore:
    """
    Get or create the shared canonical event store.
    
    Returns:
        CanonicalEventStore: Shared repository-backed event store
    """
    global _event_store, _harness_store
    
    if _event_store is None:
        logger.debug(f"Initializing event store from: {_event_store_db}")
        _harness_store, _event_store = create_integrated_store(_event_store_db)
        logger.info(f"✓ Event store initialized (db={_event_store_db})")
    
    return _event_store


def get_harness_store() -> HarnessStore:
    """
    Get or create the shared harness store (state and metadata).
    
    Returns:
        HarnessStore: Shared repository-backed harness store
    """
    global _harness_store, _event_store
    
    if _harness_store is None:
        logger.debug(f"Initializing harness store from: {_event_store_db}")
        _harness_store, _event_store = create_integrated_store(_event_store_db)
        logger.info(f"✓ Harness store initialized (db={_event_store_db})")
    
    return _harness_store


def get_fact_store() -> MemoryFactStore:
    """
    Get or create the shared temporal fact store.
    
    Returns:
        MemoryFactStore: Shared repository-backed fact store
    """
    global _fact_store
    
    if _fact_store is None:
        logger.debug(f"Initializing fact store from: {_fact_store_db}")
        _fact_store = create_default_fact_store(_fact_store_db)
        logger.info(f"✓ Fact store initialized (db={_fact_store_db})")
    
    return _fact_store


def reset_stores() -> None:
    """
    Reset all store instances. Useful for testing.
    
    Warning: This closes existing connections and clears the cache.
    """
    global _event_store, _fact_store, _harness_store
    
    logger.warning("Resetting recovery stores (testing only)")
    _event_store = None
    _fact_store = None
    _harness_store = None


def get_stores() -> dict[str, object]:
    """
    Get all shared store instances.
    
    Returns:
        Dictionary with keys: event_store, fact_store, harness_store
    """
    return {
        "event_store": get_event_store(),
        "fact_store": get_fact_store(),
        "harness_store": get_harness_store(),
    }
