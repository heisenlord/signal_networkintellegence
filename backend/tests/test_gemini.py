"""Exercise the real Gemini adapter/SDK types with a mocked provider; never spend API credits."""
import json
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.genai import types
import httpx
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.auth import IDENTITIES
from backend.config import get_settings
from backend.database import Counter, Entity, Investigation, KPI, Session
from backend.seed import seed
from backend.services.gemini_agent import _declarations, dispatch
from backend.services.tools import Tools


def auth(role="alarm"):
    return {"Authorization": f"Bearer demo-atlas-{role}"}


@pytest.fixture
def gemini_mode(monkeypatch):
    monkeypatch.setenv("SIGNAL_AGENT_MODE", "auto")
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key-never-sent")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def response(name, args):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model",
        parts=[types.Part(function_call=types.FunctionCall(id="call-1", name=name, args=args))]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=50, candidates_token_count=25))


def mock_provider(monkeypatch, replies):
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.generate_content.side_effect = replies
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr("backend.services.gemini_agent.genai.Client", constructor)
    return client, constructor


def report(**overrides):
    return {"answer": "TRANS-01 is the leading shared dependency hypothesis; verify diagnostics before a change.",
        "next_steps": ["Inspect TRANS-01 link diagnostics and request independent human review."],
        "citations": ["TRANS-01", "CELL-101"], **overrides}


def test_gemini_calls_a_real_scoped_tool_and_returns_validated_report(client, gemini_mode, monkeypatch):
    provider, constructor = mock_provider(monkeypatch, [
        response("get_entity", {"entity_id": "TRANS-01"}),
        response("finish_investigation", report()),
    ])
    result = client.post("/api/v1/investigations", headers=auth(),
        json={"incident_id": "INC-1005", "question": "What is the likely cause?"})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["llm_used"] is True
    assert data["provider"] == "gemini"
    assert data["mode"] == "llm"
    assert data["model_calls"] == 2
    assert data["question"] == "What is the likely cause?"
    assert data["agent_response"]["citations"] == ["TRANS-01", "CELL-101"]
    assert data["classification"] == "Network degradation"
    assert data["can_recommend"] is True
    assert any(t["tool"] == "get_entity" and t["origin"] == "gemini" for t in data["trace"])
    assert provider.models.generate_content.call_count == 2
    assert constructor.call_args.kwargs["api_key"] == "unit-test-key-never-sent"
    config = provider.models.generate_content.call_args.kwargs["config"]
    assert config.automatic_function_calling.disable is True
    assert len(config.tools[0].function_declarations) == 6
    contents = provider.models.generate_content.call_args.kwargs["contents"]
    assert any(c.role == "user" and any(p.function_response for p in c.parts) for c in contents)
    assert "unit-test-key-never-sent" not in result.text


def test_auto_without_key_runs_local_and_explains_configuration(client, gemini_mode, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    provider, _ = mock_provider(monkeypatch, [])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1020"})
    assert result.status_code == 200
    data = result.json()
    assert data["mode"] == "deterministic"
    assert data["classification"] == "Missing telemetry"
    assert data["can_recommend"] is False
    assert data["agent_response"]["answer"]
    assert "GEMINI_API_KEY" in data["llm_error"]
    provider.models.generate_content.assert_not_called()


def test_provider_failure_falls_back_without_exposing_secrets(client, gemini_mode, monkeypatch):
    mock_provider(monkeypatch, [RuntimeError("private provider payload unit-test-key-never-sent")])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 200
    data = result.json()
    assert data["mode"] == "fallback"
    assert data["llm_used"] is False
    assert data["llm_attempted"] is True
    assert data["evidence"]
    assert "private provider payload" not in result.text
    assert "unit-test-key-never-sent" not in result.text


@pytest.mark.parametrize("code,phrase", [(400, "request format"), (401, "API key"), (403, "permission"), (404, "unavailable"), (429, "quota"), (503, "temporarily"), (504, "timed out")])
def test_provider_error_codes_have_actionable_messages(client, gemini_mode, monkeypatch, code, phrase):
    error = RuntimeError("private provider details")
    error.code = code
    mock_provider(monkeypatch, [error, error])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 200
    assert phrase in result.json()["llm_error"]
    assert "private provider details" not in result.text


def test_required_llm_mode_rejects_missing_key(client, gemini_mode, monkeypatch):
    monkeypatch.setenv("SIGNAL_AGENT_MODE", "llm")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 503
    assert "GEMINI_API_KEY" in result.json()["detail"]


def test_required_llm_mode_returns_sanitized_provider_error(client, gemini_mode, monkeypatch):
    monkeypatch.setenv("SIGNAL_AGENT_MODE", "llm")
    get_settings.cache_clear()
    mock_provider(monkeypatch, [RuntimeError("unit-test-key-never-sent")])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 503
    assert "unit-test-key-never-sent" not in result.text


def test_model_cannot_override_the_evidence_gate(client, gemini_mode, monkeypatch):
    mock_provider(monkeypatch, [
        response("get_entity", {"entity_id": "CELL-103"}),
        response("finish_investigation", report(citations=["CELL-103"])),
    ])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1020"}).json()
    assert result["llm_used"] is True
    assert result["classification"] == "Missing telemetry"
    assert result["can_recommend"] is False
    assert result["target"] is None
    assert client.post("/api/v1/proposals", headers=auth(), json={"investigation_id": result["id"]}).status_code == 409


def test_hallucinated_citations_fall_back(client, gemini_mode, monkeypatch):
    mock_provider(monkeypatch, [
        response("get_entity", {"entity_id": "TRANS-01"}),
        response("finish_investigation", report(citations=["TRANS-DOES-NOT-EXIST"])),
    ])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"}).json()
    assert result["mode"] == "fallback"
    assert result["llm_used"] is False
    assert "TRANS-DOES-NOT-EXIST" not in result["agent_response"]["citations"]


def test_unknown_execution_tool_is_refused_and_audited(client, gemini_mode, monkeypatch):
    mock_provider(monkeypatch, [
        response("execute_network_change", {"customer_id": "horizon", "entity_id": "TRANS-01"}),
        response("get_entity", {"entity_id": "TRANS-01"}),
        response("finish_investigation", report()),
    ])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 200, result.text
    data = result.json()
    assert any(t["tool"] == "execute_network_change" and t["status"] == "refused" for t in data["trace"])
    events = client.get("/api/v1/audit?limit=200", headers=auth()).json()["items"]
    assert any(e["operation"] == "gemini_tool_refused" for e in events)


def test_agent_status_never_returns_key(client, gemini_mode):
    result = client.get("/api/v1/agent/status", headers=auth())
    assert result.status_code == 200
    assert result.json()["provider"] == "gemini"
    assert result.json()["api_key_configured"] is True
    assert "unit-test-key-never-sent" not in result.text


def test_tool_arguments_cannot_override_tenant(client):
    with Session() as session:
        tools = Tools(session, IDENTITIES["demo-atlas-alarm"])
        with pytest.raises(ValidationError):
            dispatch(tools, "get_entity", {"entity_id": "CELL-101", "customer_id": "horizon"})


def test_model_turn_budget_is_enforced(client, gemini_mode, monkeypatch):
    provider, _ = mock_provider(monkeypatch, [response("get_entity", {"entity_id": "TRANS-01"}) for _ in range(8)])
    data = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"}).json()
    assert provider.models.generate_content.call_count == 4
    assert data["mode"] == "fallback"
    assert "budget" in data["llm_error"]


def test_approvers_never_call_gemini(client, gemini_mode, monkeypatch):
    provider, _ = mock_provider(monkeypatch, [])
    result = client.post("/api/v1/investigations", headers=auth("approver"), json={"incident_id": "INC-1005"})
    assert result.status_code == 403
    provider.models.generate_content.assert_not_called()


def test_expansion_is_idempotent_and_preserves_investigations(client):
    with Session() as session:
        before = [session.scalar(select(func.count()).select_from(model)) for model in (Entity, Counter, KPI, Investigation)]
    seed()
    with Session() as session:
        after = [session.scalar(select(func.count()).select_from(model)) for model in (Entity, Counter, KPI, Investigation)]
    assert before == after
    assert before[0] == 880
    assert before[1] == 51840


def test_expanded_history_and_scenarios_are_queryable(client):
    data = client.get("/api/v1/kpis/CELL-3603?start=2026-11-09T10:15:00Z", headers=auth()).json()
    assert len(data["points"]) == 96
    assert data["points"][-1]["quality"] == "complete"
    assert data["points"][-1]["availability"] > 99
    expected = {"INC-2005": "Network degradation", "INC-2020": "Missing telemetry",
        "INC-2035": "Unresolved uncertainty", "INC-2050": "No measured degradation", "INC-2060": "Unresolved uncertainty"}
    for incident, classification in expected.items():
        result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": incident})
        assert result.status_code == 200, result.text
        assert result.json()["classification"] == classification
    quality = client.get("/api/v1/quality", headers=auth()).json()
    assert len(quality["gaps"]) == 6
    assert sum(len(v["issues"]) for v in quality["versions"]) == 4


def test_google_sdk_serializes_tool_requests_and_responses(client, gemini_mode, monkeypatch):
    """Use the real SDK HTTP serializer with an in-memory fake Google endpoint."""
    from google import genai
    real_client = genai.Client
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        assert all(c["role"] in {"user", "model"} for c in requests[-1]["contents"])
        if len(requests) == 2:
            part = requests[-1]["contents"][-1]["parts"][0]["functionResponse"]
            assert requests[-1]["contents"][-1]["role"] == "user"
            assert part["name"] == "get_entity"
            assert part["id"] == "wire-call-1"
        function = {"name": "get_entity", "args": {"entity_id": "TRANS-01"}} if len(requests) == 1 else {"name": "finish_investigation", "args": report()}
        function["id"] = "wire-call-1"
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"functionCall": function}]}, "finishReason": "STOP"}]})

    def factory(**kwargs):
        kwargs["http_options"].httpx_client = httpx.Client(transport=httpx.MockTransport(handle))
        return real_client(**kwargs)

    monkeypatch.setattr("backend.services.gemini_agent.genai.Client", factory)
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 200, result.text
    assert result.json()["llm_used"] is True, result.text
    assert len(requests) == 2
    assert len(requests[0]["tools"][0]["functionDeclarations"]) == 5
    assert len(requests[1]["tools"][0]["functionDeclarations"]) == 6
    assert any("functionResponse" in part for content in requests[1]["contents"] for part in content["parts"])
    assert "unit-test-key-never-sent" not in json.dumps(requests)


def test_gemini_thinking_configuration_matches_model_family():
    from backend.services.gemini_agent import _thinking_config
    assert _thinking_config("gemini-2.5-flash").thinking_budget == 0
    assert _thinking_config("gemini-3.5-flash").thinking_level == types.ThinkingLevel.LOW
    assert _thinking_config("gemini-3.5-flash").thinking_budget is None


def test_transient_provider_failure_retries_within_the_request_budget(client, gemini_mode, monkeypatch):
    error = RuntimeError("temporary outage")
    error.code = 503
    provider, _ = mock_provider(monkeypatch, [
        error, response("get_entity", {"entity_id": "TRANS-01"}),
        response("finish_investigation", report()),
    ])
    result = client.post("/api/v1/investigations", headers=auth(), json={"incident_id": "INC-1005"})
    assert result.status_code == 200
    assert result.json()["llm_used"] is True
    assert result.json()["model_calls"] == 3
    assert provider.models.generate_content.call_count == 3
    events = client.get("/api/v1/audit?limit=200", headers=auth()).json()["items"]
    assert any(event["operation"] == "gemini_retry" for event in events)


def test_mcp_stdio_protocol_exposes_and_runs_the_investigation(client):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        server = StdioServerParameters(command=sys.executable, args=["-m", "backend.mcp_server"],
            cwd=str(Path(__file__).resolve().parents[2]),
            env={**os.environ, "SIGNAL_DEMO_TOKEN": "demo-atlas-alarm", "SIGNAL_AGENT_MODE": "deterministic"})
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert len(names) == 7
                assert "investigate" in names
                result = await session.call_tool("investigate", {"incident_id": "INC-2005", "question": "Explain the shared cause."})
                assert result.isError is False
                data = result.structuredContent or json.loads(result.content[0].text)
                assert data["customer_id"] == "atlas"
                assert data["classification"] == "Network degradation"
                assert data["question"] == "Explain the shared cause."
                assert data["agent_response"]["answer"]
    asyncio.run(asyncio.wait_for(run(), timeout=30))
