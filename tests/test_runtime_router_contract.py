# -*- coding: utf-8 -*-
"""Contract tests for the runtime events route."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from harness_protocols import JobKind, SessionMode
from python_adapter_server import app
from writing_runtime import WritingRuntime
import routers.runtime_router as runtime_router_module


def test_runtime_events_route_supports_incremental_polling(monkeypatch) -> None:
    """The runtime job events endpoint should honor cursor and limit query params."""
    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.SKILL)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="Route cursor test",
        skill_id="skill-route-test",
    )

    asyncio.run(runtime.start_job(job.job_id))
    asyncio.run(runtime.complete_job(job.job_id, result="done"))

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    client = TestClient(app)

    ordered_response = client.get(f"/runtime/job/{job.job_id}/events")
    assert ordered_response.status_code == 200
    ordered_events = ordered_response.json()
    assert [event["event_type"] for event in ordered_events] == [
        "job_created",
        "job_started",
        "job_completed",
    ]

    cursor_response = client.get(
        f"/runtime/job/{job.job_id}/events",
        params={
            "since_timestamp": ordered_events[1]["timestamp"],
            "after_event_id": ordered_events[1]["event_id"],
            "limit": 1,
        },
    )
    assert cursor_response.status_code == 200
    assert [event["event_id"] for event in cursor_response.json()] == [ordered_events[2]["event_id"]]