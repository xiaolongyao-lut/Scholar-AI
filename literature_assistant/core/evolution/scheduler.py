"""Async scheduler for periodic evolution curator passes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from evolution.config import curator_interval_seconds, is_curator_enabled
from evolution.curator import EvolutionCurator
from evolution.service import EvolutionService, get_evolution_service

logger = logging.getLogger("EvolutionCuratorScheduler")

Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class CuratorSchedulerStatus:
    """Runtime status for the periodic curator scheduler."""

    enabled: bool
    running: bool
    interval_seconds: int
    last_run_scanned: int | None = None
    last_error: str | None = None


class EvolutionCuratorScheduler:
    """Small asyncio scheduler guarded by evolution curator kill switches."""

    def __init__(
        self,
        *,
        service_factory: Callable[[], EvolutionService] = get_evolution_service,
        enabled_reader: Callable[[], bool] = is_curator_enabled,
        interval_reader: Callable[[], int] = curator_interval_seconds,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._service_factory = service_factory
        self._enabled_reader = enabled_reader
        self._interval_reader = interval_reader
        self._sleeper = sleeper
        self._task: asyncio.Task[None] | None = None
        self._last_run_scanned: int | None = None
        self._last_error: str | None = None

    def start(self) -> bool:
        """Start the scheduler when enabled and not already running."""
        if not self._enabled_reader():
            return False
        if self._task is not None and not self._task.done():
            return True
        self._task = asyncio.create_task(self._run_loop(), name="evolution-curator-scheduler")
        return True

    async def stop(self) -> None:
        """Cancel the scheduler task and wait for shutdown."""
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    def status(self) -> CuratorSchedulerStatus:
        """Return current scheduler state without starting it."""
        task = self._task
        return CuratorSchedulerStatus(
            enabled=bool(self._enabled_reader()),
            running=task is not None and not task.done(),
            interval_seconds=self._interval_reader(),
            last_run_scanned=self._last_run_scanned,
            last_error=self._last_error,
        )

    async def _run_loop(self) -> None:
        while self._enabled_reader():
            await self.run_once()
            await self._sleeper(float(self._interval_reader()))

    async def run_once(self) -> None:
        """Run one curator pass and record a bounded status summary."""
        try:
            result = EvolutionCurator(self._service_factory()).run()
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            self._last_error = exc.__class__.__name__
            logger.warning("scheduled curator pass failed: %s", exc)
            return
        self._last_run_scanned = int(result.scanned_count)
        self._last_error = None


_scheduler = EvolutionCuratorScheduler()


def get_curator_scheduler() -> EvolutionCuratorScheduler:
    """Return the process-wide curator scheduler instance."""
    return _scheduler
