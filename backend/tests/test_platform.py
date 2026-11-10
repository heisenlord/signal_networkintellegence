from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.auth import IDENTITIES
from backend.database import Counter, KPI, Proposal, Session
from backend.mcp_server import invoke
from backend.services.kpi import calculate, publish


def auth(role="alarm", customer="atlas"):
    return {"Authorization": f"Bearer demo-{customer}-{role}"}


def investigate(client, incident="INC-1005", role="alarm"):
    response = client.post("/api/v1/investigations", headers=auth(role), json={"incident_id": incident})
    assert response.status_code == 200, response.text
    return response.json()


def test_authentication_is_required(client):
    assert client.get("/api/v1/overview").status_code == 401
    assert client.get("/api/v1/overview", headers={"Authorization": "Bearer unknown"}).status_code == 401


def test_five_tenant_identities_are_scoped(client):
    for cid in ("atlas", "horizon", "meridian", "nova", "summit"):
        response = client.get("/api/v1/overview", headers=auth(customer=cid))
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["customer_id"] == cid
        assert data["customer"]["id"] == cid
        assert data["metrics"]["entities"] == 176
        assert data["metrics"]["cells"] == 108
        assert data["metrics"]["sites"] == 18
        assert data["metrics"]["counter_rows"] == 10368
        assert len(data["incidents"]) == 8
        assert len(data["alarms"]) == 19
    # A caller cannot override customer scope through the body.
    response = client.post("/api/v1/topology/neighbors", headers=auth(), json={"entity_id": "CELL-101", "customer_id": "horizon"})
    assert response.status_code == 422


def test_historical_topology_tracks_backhaul_change(client, headers):
    before = client.post("/api/v1/topology/neighbors", headers=headers, json={"entity_id": "NODE-02", "as_of": "2026-11-10T09:45:00Z"}).json()
    during = client.post("/api/v1/topology/neighbors", headers=headers, json={"entity_id": "NODE-02", "as_of": "2026-11-10T10:05:00Z"}).json()
    assert any(e["source"] == "NODE-02" and e["target"] == "TRANS-02" for e in before["relationships"])
    assert any(e["source"] == "NODE-02" and e["target"] == "TRANS-01" for e in during["relationships"])
    assert not any(e["source"] == "NODE-02" and e["target"] == "TRANS-02" for e in during["relationships"])
    assert before["provenance"]["inventory_version"] == "v11"


def test_traversal_rejects_unbounded_requests_and_reports_truncation(client, headers):
    assert client.post("/api/v1/topology/neighbors", headers=headers, json={"entity_id": "NODE-01", "max_depth": 10}).status_code == 422
    response = client.post("/api/v1/topology/neighbors", headers=headers, json={"entity_id": "NODE-01", "max_results": 1})
    assert response.status_code == 200
    assert response.json()["truncated"] is True
    assert len(response.json()["entities"]) == 1


def test_bad_timestamps_and_unknown_entities_are_controlled_errors(client, headers):
    for timestamp in ("garbage", "2026-11-10T10:05:00"):
        response = client.post("/api/v1/topology/neighbors", headers=headers, json={"entity_id": "CELL-101", "as_of": timestamp})
        assert response.status_code == 422
    assert client.get("/api/v1/entities/DOES-NOT-EXIST", headers=headers).status_code == 404
    assert client.get("/api/v1/kpis/CELL-101?start=2026-11-09T00:00:00Z", headers=headers).status_code == 422


def test_shared_transport_is_found(client, headers):
    result = client.post("/api/v1/topology/shared-dependencies", headers=headers, json={"entity_ids": ["CELL-101", "CELL-102", "CELL-201", "CELL-202"]})
    assert result.status_code == 200, result.text
    assert [d["id"] for d in result.json()["shared_dependencies"]] == ["TRANS-01"]


def test_shared_dependency_queries_preserve_unresolved_inventory_quality(client, headers):
    result = client.post("/api/v1/topology/shared-dependencies", headers=headers, json={"entity_ids": ["CELL-301"]})
    assert result.status_code == 200
    assert result.json()["quality"]["status"] == "partial"


@pytest.mark.parametrize("incident,classification,recommend", [
    ("INC-1005", "Network degradation", True),
    ("INC-1020", "Missing telemetry", False),
    ("INC-1035", "Unresolved uncertainty", False),
])
def test_evidence_classification(client, incident, classification, recommend):
    result = investigate(client, incident)
    assert result["classification"] == classification
    assert result["can_recommend"] is recommend
    assert result["llm_used"] is False
    assert result["tool_calls"] <= 16
    assert result["duration_ms"] < 30000
    assert result["trace"]


def test_missing_values_are_null_and_partial_values_are_flagged(client, headers):
    missing = client.get("/api/v1/kpis/CELL-103", headers=headers).json()["points"][-1]
    partial = client.get("/api/v1/kpis/CELL-301", headers=headers).json()["points"][-1]
    assert missing["availability"] is None
    assert missing["throughput_mbps"] is None
    assert missing["quality"] == "unavailable"
    assert partial["quality"] == "partial"
    assert partial["completeness"] == pytest.approx(8 / 15, abs=.001)
    assert partial["final"] is False


def test_weighted_kpi_uses_counters_instead_of_average_percentages():
    rows = [{"window": "2026-11-10T10:00:00Z", "successful_seconds": success, "observed_seconds": total,
        "samples": samples, "expected_samples": samples, "throughput_mbps": 10} for success, total, samples in [(90, 100, 1), (0, 900, 9)]]
    result = calculate(rows, now="2026-11-10T12:15:00Z")
    assert result["availability"] == 9.0
    assert result["quality"] == "complete"
    assert result["final"] is True


def test_empty_and_invalid_counters_are_unavailable():
    assert calculate([], now="2026-11-10T12:15:00Z")["availability"] is None
    result = calculate([{"window": "2026-11-10T10:00:00Z", "successful_seconds": 120, "observed_seconds": 100,
        "samples": 1, "expected_samples": 1, "throughput_mbps": 10}], now="2026-11-10T12:15:00Z")
    assert result["quality"] == "unavailable"
    assert result["availability"] is None


@pytest.mark.parametrize("role,prefix", [("alarm", "Incident update:"), ("performance", "Performance finding:"), ("change", "Change plan:")])
def test_roles_receive_only_their_specialized_outputs(client, role, prefix):
    result = investigate(client, role=role)
    assert result["role"] == role
    assert result["role_output"].startswith(prefix)


def test_approval_is_independent_and_never_executes(client):
    result = investigate(client)
    response = client.post("/api/v1/proposals", headers=auth(), json={"investigation_id": result["id"]})
    assert response.status_code == 200, response.text
    proposal_id = response.json()["id"]
    assert client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=auth()).status_code == 403
    assert client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=auth("approver", "horizon")).status_code == 404
    approved = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=auth("approver"))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved_for_review"
    assert client.post(f"/api/v1/proposals/{proposal_id}/execute", headers=auth("approver")).status_code == 403
    assert client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=auth("approver")).status_code == 409


def test_approvers_cannot_investigate_or_propose(client):
    assert client.post("/api/v1/investigations", headers=auth("approver"), json={"incident_id": "INC-1005"}).status_code == 403
    assert client.post("/api/v1/proposals", headers=auth("approver"), json={"investigation_id": "unknown"}).status_code == 403


def test_insufficient_evidence_cannot_be_proposed(client):
    result = investigate(client, "INC-1020")
    assert client.post("/api/v1/proposals", headers=auth(), json={"investigation_id": result["id"]}).status_code == 409


def test_cross_tenant_investigations_and_proposals_do_not_leak(client):
    result = investigate(client)
    response = client.post("/api/v1/proposals", headers=auth(customer="horizon"), json={"investigation_id": result["id"]})
    assert response.status_code == 404
    history = client.get("/api/v1/investigations", headers=auth(customer="horizon")).json()["items"]
    assert result["id"] not in [r["id"] for r in history]
    audit = client.get("/api/v1/audit", headers=auth(customer="horizon")).json()
    assert all(event["actor"].startswith("demo:horizon:") for event in audit["items"])


def test_expired_proposals_are_rejected(client):
    result = investigate(client)
    proposal = client.post("/api/v1/proposals", headers=auth(), json={"investigation_id": result["id"]}).json()
    with Session.begin() as session:
        row = session.get(Proposal, ("atlas", proposal["id"]))
        row.expires_at = "2020-01-01T00:00:00Z"
    assert client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=auth("approver")).status_code == 409


def test_audit_includes_denied_actions_and_request_ids(client, headers):
    client.post("/api/v1/investigations", headers=auth("approver"), json={"incident_id": "INC-1005"})
    events = client.get("/api/v1/audit?limit=200", headers=headers).json()["items"]
    assert any(e["operation"] == "request_denied" for e in events)
    assert any(e["operation"] == "investigation_completed" for e in events)
    assert all(e["details"]["request_id"] for e in events)


def test_mcp_adapter_shares_scope_and_permissions(client, monkeypatch):
    monkeypatch.setenv("SIGNAL_DEMO_TOKEN", "demo-horizon-alarm")
    result = invoke("get_entity", "CELL-101")
    assert result["customer_id"] == "horizon"
    monkeypatch.setenv("SIGNAL_DEMO_TOKEN", "demo-atlas-approver")
    with pytest.raises(Exception, match="cannot investigate"):
        invoke("investigate", "INC-1005")
    monkeypatch.delenv("SIGNAL_DEMO_TOKEN")
    with pytest.raises(ValueError, match="explicit demo customer"):
        invoke("get_entity", "CELL-101")


def test_late_counter_revisions_are_append_only_and_idempotent(client):
    with Session.begin() as session:
        counter = session.get(Counter, ("summit", "CELL-103", "2026-11-10T10:00:00Z"))
        original = publish(session, counter, "2026-11-10T10:20:00Z")
        assert original.revision == 1
        counter.samples = counter.expected_samples
        counter.observed_seconds = counter.samples * 60
        counter.successful_seconds = counter.observed_seconds * .998
        counter.received_at = "2026-11-10T11:00:00Z"
        amended = publish(session, counter, "2026-11-10T11:01:00Z")
        assert amended.revision == 2
        assert amended.availability == 99.8
        assert publish(session, counter, "2026-11-10T11:01:00Z").revision == 2
        revisions = list(session.scalars(select(KPI).where(KPI.customer_id == "summit", KPI.entity_id == "CELL-103", KPI.window == counter.window).order_by(KPI.revision)))
        assert [r.revision for r in revisions] == [1, 2]
        assert revisions[0].availability is None
    before = client.get("/api/v1/kpis/CELL-103", headers=auth(customer="summit")).json()["points"][-1]
    after = client.get("/api/v1/kpis/CELL-103?known_at=2026-11-10T11:01:00Z", headers=auth(customer="summit")).json()["points"][-1]
    assert before["availability"] is None
    assert after["availability"] == 99.8
