"""
Isolated Proof of Concept for Async DB Migration

This file implements an asynchronous version of the CanonicalEventStore using `aiosqlite`.
It is NOT integrated into the main pipeline. 
It serves purely as a feasibility demonstration.
"""

import asyncio
import json
import logging
import sqlite3
from typing import Optional, List

try:
    import aiosqlite
except ImportError:
    # Fallback/mock if not installed in current environment
    aiosqlite = None

from harness_canonical_events import CanonicalEvent

logger = logging.getLogger(__name__)

class AsyncCanonicalEventStorePoC:
    """
    An asynchronous proof of concept for the event store.
    Utilizes aiosqlite to push file I/O out of the main asyncio loop.
    """
    
    def __init__(self, db_path: str = "harness_async_poc.db"):
        self.db_path = db_path
        
    async def init_schema(self) -> None:
        """Initialize the schema non-blockingly."""
        if aiosqlite is None:
            logger.warning("aiosqlite not installed. Schema init skipped.")
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS canonical_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    correlation_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    session_id TEXT,
                    job_id TEXT,
                    user_id TEXT,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSON NOT NULL,
                    actor_id TEXT,
                    actor_type TEXT DEFAULT 'system',
                    severity TEXT DEFAULT 'info',
                    previous_state JSON,
                    new_state JSON,
                    error_code TEXT,
                    error_message TEXT,
                    source TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def append_event(self, event: CanonicalEvent) -> None:
        """Append event payload asymptotically."""
        if aiosqlite is None:
            return
            
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("""
                    INSERT INTO canonical_events (
                        event_id, correlation_id, timestamp, session_id, job_id, user_id,
                        aggregate_type, aggregate_id, event_type, payload, actor_id, actor_type,
                        severity, previous_state, new_state, error_code, error_message, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id, event.correlation_id, event.timestamp, event.session_id,
                    event.job_id, event.user_id, event.aggregate_type, event.aggregate_id,
                    event.event_type, json.dumps(event.payload), event.actor_id, event.actor_type,
                    event.severity, 
                    json.dumps(event.previous_state) if event.previous_state else None,
                    json.dumps(event.new_state) if event.new_state else None,
                    event.error_code, event.error_message, event.source
                ))
                await db.commit()
            except sqlite3.IntegrityError as e:
                logger.error(f"Event insertion failed due to integrity error: {e}")
                raise

    async def get_job_timeline(self, job_id: str) -> List[dict]:
        """Fetch timeline rows contextually."""
        if aiosqlite is None:
            return []
            
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM canonical_events WHERE job_id = ? ORDER BY timestamp ASC", 
                (job_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

async def _run_demo():
    print("Executing Async SQLite PoC...")
    store = AsyncCanonicalEventStorePoC()
    await store.init_schema()
    
    # Generate mock event
    event = CanonicalEvent(
        event_id="test-event-async-001",
        correlation_id="corr-1",
        timestamp="2026-04-12T00:00:00Z",
        aggregate_type="demo",
        aggregate_id="demo-1",
        event_type="test_async",
        payload={"msg": "hello from async"},
        source="poc"
    )
    
    await store.append_event(event)
    timeline = await store.get_job_timeline(None)
    print(f"Stored async timeline fetched: {len(timeline)} events.")
    
if __name__ == "__main__":
    if aiosqlite is not None:
        asyncio.run(_run_demo())
    else:
        print("PoC requires `aiosqlite` extension. Install with `pip install aiosqlite` to try this sandbox.")
