"""Tests for discussion_advanced_router (Slice D / TASK-605)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import discussion_advanced_router as adv_router_module


DUMMY_LLM_KEY = "test-orch-router-key-1234567890ABC"


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(adv_router_module.router)
    return TestClient(app)


def _request_body(synth_strategy: str = "synthesize") -> dict:
    return {
        "project_id": None,
        "query": "What is attention in transformers?",
        "agent_configs": [
            {
                "agent_id": "p",
                "role": "proposer",
                "llm": {
                    "provider": "OpenAI",
                    "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": DUMMY_LLM_KEY,
                },
            },
            {
                "agent_id": "c",
                "role": "critic",
                "llm": {
                    "provider": "OpenAI",
                    "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": DUMMY_LLM_KEY,
                },
            },
        ],
        "synthesizer_agent_id": "p",
        "max_turns": 1,
        "evidence_mode": "none",
        "synthesis_strategy": synth_strategy,
        "timeout_seconds": 5.0,
    }


def test_run_endpoint_returns_synthesis(client) -> None:
    async def stub_invoke(candidate, prompt):
        return f"answer-{candidate.agent_id}"

    adv_router_module.set_invoke_agent_factory(lambda cfg: stub_invoke)
    try:
        r = client.post("/api/discussion/runs", json=_request_body())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["query"].startswith("What is attention")
        assert len(body["turns"]) == 1
        assert {t["agent_id"] for t in body["turns"][0]["agent_traces"]} == {"p", "c"}
        assert body["synthesis"]["success"] is True
        assert body["synthesis"]["synthesizer_agent_id"] == "p"
        # Secrets must never leak to API response
        assert DUMMY_LLM_KEY not in r.text
    finally:
        adv_router_module.set_invoke_agent_factory(None)


def test_run_endpoint_400_on_unsupported_strategy(client) -> None:
    async def stub_invoke(candidate, prompt):
        return "x"

    adv_router_module.set_invoke_agent_factory(lambda cfg: stub_invoke)
    try:
        body = _request_body(synth_strategy="vote")
        r = client.post("/api/discussion/runs", json=body)
        assert r.status_code == 400
        assert "vote" in r.text
    finally:
        adv_router_module.set_invoke_agent_factory(None)


def test_run_endpoint_422_on_missing_agents(client) -> None:
    body = _request_body()
    body["agent_configs"] = []  # min_length=1
    r = client.post("/api/discussion/runs", json=body)
    assert r.status_code == 422


def test_run_endpoint_422_on_duplicate_agent_ids(client) -> None:
    body = _request_body()
    body["agent_configs"][1]["agent_id"] = "p"  # duplicate
    r = client.post("/api/discussion/runs", json=body)
    assert r.status_code == 422


def test_run_endpoint_422_on_unknown_synthesizer(client) -> None:
    body = _request_body()
    body["synthesizer_agent_id"] = "ghost"
    r = client.post("/api/discussion/runs", json=body)
    assert r.status_code == 422


def test_run_endpoint_422_on_credential_xor_llm_violation(client) -> None:
    body = _request_body()
    body["agent_configs"][0]["credential_id"] = "cred_x"
    # llm is also set -> XOR violation
    r = client.post("/api/discussion/runs", json=body)
    assert r.status_code == 422
