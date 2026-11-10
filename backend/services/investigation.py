"""A bounded LangGraph workflow; evidence evaluation never depends on an LLM."""
import time
from typing import TypedDict
from uuid import uuid4

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from backend.auth import utcnow
from backend.config import get_settings
from backend.database import Investigation
from backend.services.gemini_agent import augment_with_gemini
from backend.services.tools import Tools


class State(TypedDict, total=False):
    incident_id: str
    context: dict
    cells: list[str]
    dependencies: dict
    kpis: list[dict]
    trace: list[dict]
    result: dict


def investigate(tools: Tools, incident_id: str, question: str = "") -> dict:
    tools.require("investigate")
    settings = get_settings()
    started = time.monotonic()
    deadline = started + settings.signal_agent_deadline_seconds
    calls = 0
    trace = []

    def call(name, operation, *args, origin="workflow", arguments=None):
        nonlocal calls
        if calls >= settings.signal_agent_max_tool_calls or time.monotonic() >= deadline:
            raise HTTPException(408, "Investigation evidence budget exhausted; no action recommended")
        tick = time.monotonic()
        calls += 1
        status = "error"
        try:
            value = operation(*args)
            status = value["quality"]["status"]
            return value
        except (HTTPException, ValidationError):
            status = "refused"
            raise
        finally:
            trace.append({"step": len(trace) + 1, "tool": name, "status": status, "origin": origin,
                "arguments": arguments, "duration_ms": round((time.monotonic() - tick) * 1000, 1),
                "request_id": tools.request_id})
            if origin == "gemini":
                tools.audit("gemini_tool_call", {"tool": name, "status": status, "arguments": arguments})

    def gather(state):
        context = call("get_alarm_context", tools.get_alarm_context, state["incident_id"])
        cells = sorted({a["entity_id"] for a in context["alarms"] if a["entity_id"].startswith("CELL-")})
        if not 1 <= len(cells) <= 10:
            raise HTTPException(409, "Incident requires manual scoping to 1–10 affected cells")
        return {"context": context, "cells": cells}

    def correlate(state):
        return {"dependencies": call("get_shared_dependencies", tools.get_shared_dependencies, state["cells"])}

    def measure(state):
        return {"kpis": [call("get_kpi_timeseries", tools.get_kpi_timeseries, cell) for cell in state["cells"]]}

    def conclude(state):
        dependencies = state["dependencies"]["shared_dependencies"]
        transport = [d for d in dependencies if d["type"] == "transport"]
        alarms = state["context"]["alarms"]
        transport_alarm = next((a for a in alarms if any(d["id"] == a["entity_id"] for d in transport)), None)
        latest = [series["points"][-1] if series["points"] else {"availability": None, "quality": "unavailable", "completeness": 0} for series in state["kpis"]]
        unavailable = any(p["availability"] is None for p in latest)
        incomplete = any(p["quality"] != "complete" for p in latest) or state["dependencies"]["quality"]["status"] != "complete" or state["context"]["truncated"]
        degraded = bool(latest) and all(p["availability"] is not None and p["availability"] < 95 for p in latest)
        can_recommend = bool(transport_alarm and degraded and not incomplete)
        if can_recommend:
            classification, confidence = "Network degradation", "High"
            summary = f"{len(state['cells'])} affected cells share {transport_alarm['entity_id']}. Its link-down alarm coincides with a measured availability drop. Transport failure is the leading hypothesis; confirm with transport diagnostics before any change."
            recommendation = f"Ask the transport operations team to inspect {transport_alarm['entity_id']} and validate the link state. Prepare a recovery plan for human review."
        elif unavailable:
            classification, confidence = "Missing telemetry", "Insufficient evidence"
            summary = "Incident-window counters are absent. Missing measurements do not establish a network outage. The two-hour lateness allowance is still open."
            recommendation = "Check the vendor collector and ingestion lag, wait for the watermark, then recalculate. No network change is supported."
        elif not incomplete and not degraded:
            classification, confidence = "No measured degradation", "Moderate"
            summary = "Complete incident-window measurements remain above the degradation threshold. The availability alarm is not corroborated by the measured counters."
            recommendation = "Validate the alarm source and reporting window. Continue monitoring; no network change is supported by the current evidence."
        else:
            classification, confidence = "Unresolved uncertainty", "Low"
            summary = "The evidence does not establish a shared transport cause. " + ("Measurements or topology are incomplete. " if incomplete else "Observed degradation has no corroborating shared transport alarm. ") + "The cause remains uncertain."
            recommendation = "Validate counter coverage and inventory references, then request radio and transport diagnostics. Escalate for manual investigation; decline a network-change recommendation."
        evidence = []
        for cell, series, point in zip(state["cells"], state["kpis"], latest):
            before = [p for p in series["points"] if p["window"] < "2026-11-10T10:00:00Z" and p["availability"] is not None]
            baseline = round(sum(p["availability"] for p in before) / len(before), 2) if before else None
            evidence.append({"entity_id": cell, "baseline": baseline, "during": point["availability"],
                "completeness": point["completeness"], "quality": point["quality"], "source": "availability-v1", "window": "2026-11-10T10:00:00Z"})
        role_output = {
            "alarm": "Incident update: " + summary,
            "performance": "Performance finding: " + ("Correlated availability regression across all measured affected cells." if can_recommend else recommendation),
            "change": "Change plan: " + ("1. Verify transport diagnostics. 2. Assess the dependent sites and services in the topology. 3. Draft a restoration procedure and rollback. 4. Obtain independent human approval. No execution tool is available." if can_recommend else "Blocked until evidence gaps are resolved."),
        }[tools.identity.role]
        return {"result": {"classification": classification, "confidence": confidence, "summary": summary,
            "recommendation": recommendation, "can_recommend": can_recommend, "target": transport_alarm["entity_id"] if can_recommend else None,
            "evidence": evidence, "shared_dependencies": dependencies, "affected_cells": state["cells"],
            "role_output": role_output, "uncertainties": ["Correlation supports a hypothesis; physical root cause requires diagnostics.", "Incident KPIs remain provisional until the two-hour watermark."] if can_recommend else [recommendation],
            "mode": "deterministic", "llm_used": False}}

    def agent_response(state):
        finding = {**state["result"], "incident_id": incident_id}
        prompt = question.strip() or "Investigate this incident, explain the evidence, and recommend the next steps for my role."
        return {"result": {**state["result"], **augment_with_gemini(tools, finding, prompt, call, deadline)}}

    workflow = StateGraph(State)
    for name, function in [("alarm_context", gather), ("shared_dependencies", correlate), ("kpi_evidence", measure), ("recommendation", conclude), ("agent_response", agent_response)]:
        workflow.add_node(name, function)
    workflow.add_edge(START, "alarm_context")
    workflow.add_edge("alarm_context", "shared_dependencies")
    workflow.add_edge("shared_dependencies", "kpi_evidence")
    workflow.add_edge("kpi_evidence", "recommendation")
    workflow.add_edge("recommendation", "agent_response")
    workflow.add_edge("agent_response", END)
    output = workflow.compile().invoke({"incident_id": incident_id}, {"recursion_limit": 10})
    result = {**output["result"], "id": f"INV-{uuid4().hex[:8].upper()}", "incident_id": incident_id,
        "customer_id": tools.customer, "role": tools.identity.role, "created_at": utcnow(), "trace": trace,
        "duration_ms": round((time.monotonic() - started) * 1000, 1), "tool_calls": calls,
        "budget": {"max_tool_calls": settings.signal_agent_max_tool_calls, "deadline_seconds": settings.signal_agent_deadline_seconds,
            "max_model_calls": settings.signal_agent_max_model_calls}, "as_of": "2026-11-10T10:05:00Z"}
    tools.session.add(Investigation(customer_id=tools.customer, id=result["id"], role=tools.identity.role, created_at=result["created_at"], result=result))
    tools.audit("investigation_completed", {"investigation_id": result["id"], "classification": result["classification"], "tool_calls": calls,
        "mode": result["mode"], "model": result["model"]})
    return result
