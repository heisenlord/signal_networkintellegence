from contextlib import asynccontextmanager
from collections import OrderedDict
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from backend.auth import CUSTOMERS, PERMISSIONS, ROLES, Principal, principal
from backend.config import agent_status, get_settings
from backend.security import SecurityMiddleware
from backend.database import Alarm, Audit, Counter, Customer, Entity, Investigation, Proposal, Relationship, Session
from backend.scenarios import SCENARIOS
from backend.seed import OBSERVED_AT, seed
from backend.services.actions import approve_action, proposal_dict, propose_action
from backend.services.investigation import investigate
from backend.services.tools import DEFAULT_AS_OF, Tools


@asynccontextmanager
async def lifespan(app):
    seed()
    yield


settings = get_settings()
production = settings.signal_environment == "production"
app = FastAPI(title="Signal Network Intelligence", version="1.0.0", lifespan=lifespan,
    docs_url=None if production else "/docs", redoc_url=None if production else "/redoc",
    openapi_url=None if production else "/openapi.json",
    description="Sample-data network intelligence. No network-change executor is installed.")
app.add_middleware(CORSMiddleware, allow_origins=settings.signal_allowed_origins,
    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After", "WWW-Authenticate"], max_age=600)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.signal_allowed_hosts)
app.add_middleware(SecurityMiddleware, settings=settings)
investigation_slots = BoundedSemaphore(settings.signal_max_concurrent_investigations)
investigation_rates = OrderedDict()
investigation_rate_lock = Lock()


@app.exception_handler(HTTPException)
async def error_response(request: Request, exc: HTTPException):
    # Persist denied authenticated requests as well as successful tools.
    identity = getattr(request.state, "identity", None)
    if identity:
        with Session.begin() as session:
            Tools(session, identity, request.state.request_id).audit("request_denied", {"path": request.url.path, "status": exc.status_code, "reason": str(exc.detail)})
    return JSONResponse(status_code=exc.status_code, headers=exc.headers, content={"detail": exc.detail, "request_id": request.state.request_id,
        "errors": [{"code": str(exc.status_code), "message": str(exc.detail)}]})


def tool_context(request: Request, identity: Principal = Depends(principal)):
    with Session() as session:
        try:
            yield Tools(session, identity, request.state.request_id)
            session.commit()
        except Exception:
            session.rollback()
            raise


Context = Annotated[Tools, Depends(tool_context)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopologyRequest(StrictModel):
    entity_id: str = Field(min_length=1, max_length=100)
    as_of: str = DEFAULT_AS_OF
    known_at: str = OBSERVED_AT
    max_depth: int = Field(default=2, ge=1, le=2)
    max_results: int = Field(default=100, ge=1, le=100)


class SharedRequest(StrictModel):
    entity_ids: list[str] = Field(min_length=1, max_length=10)
    as_of: str = DEFAULT_AS_OF


class InvestigationRequest(StrictModel):
    incident_id: str = Field(min_length=1, max_length=100)
    question: str = Field(default="", max_length=1500)


class ActionRequest(StrictModel):
    investigation_id: str = Field(min_length=1, max_length=100)


@app.get("/api/health")
def health():
    from sqlalchemy import text
    with Session() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok", "mode": "sample-data"}


@app.get("/api/config")
def public_config():
    return {"authentication": "oidc" if production else "demo"}


@app.get("/api/v1/session")
def current_session(identity: Principal = Depends(principal)):
    return {"customer_id": identity.customer_id, "role": identity.role, "subject": identity.subject}


@app.get("/api/v1/agent/status")
def agent_configuration(tools: Context):
    tools.require("read")
    return agent_status()


@app.get("/api/v1/demo/sessions")
def sessions():
    if production:
        raise HTTPException(404, "Not found")
    return {"notice": "Public localhost-only demo identities, not production authentication.",
        "customers": [{"id": cid, "name": name, "region": region} for cid, name, region in CUSTOMERS],
        "roles": [{"id": rid, "name": name, "permissions": sorted(PERMISSIONS[rid])} for rid, name in ROLES.items()]}


@app.get("/api/v1/overview")
def overview(tools: Context):
    tools.require("read")
    customer = tools.session.get(Customer, tools.customer)
    alarms = list(tools.session.scalars(select(Alarm).where(Alarm.customer_id == tools.customer).order_by(Alarm.id)))
    entities = list(tools.session.scalars(select(Entity).where(Entity.customer_id == tools.customer)))
    grouped = {}
    for alarm in alarms:
        grouped.setdefault(alarm.incident_id, []).append(alarm)
    severity_order = {"critical": 0, "major": 1, "warning": 2}
    incidents = []
    for incident_id, incident_alarms in grouped.items():
        label = SCENARIOS.get(incident_id, {"name": incident_id, "type": "Unclassified"})
        cells = sorted({a.entity_id for a in incident_alarms if a.entity_id.startswith("CELL-")})
        incidents.append({"id": incident_id, **label, "severity": min((a.severity for a in incident_alarms), key=severity_order.get),
            "cells": len(cells), "cell_ids": cells})
    affected = {a.entity_id for a in alarms if a.entity_id.startswith("CELL-")}
    counter_count = tools.session.scalar(select(func.count()).select_from(Counter).where(Counter.customer_id == tools.customer))
    relationship_count = tools.session.scalar(select(func.count()).select_from(Relationship).where(Relationship.customer_id == tools.customer))
    severity_counts = {severity: sum(a.severity == severity for a in alarms) for severity in severity_order}
    return tools.envelope("get_overview", {"customer": {"id": customer.id, "name": customer.name, "region": customer.region},
        "metrics": {"entities": len(entities), "active_alarms": len(alarms), "affected_cells": len(affected),
            "shared_dependencies": sum(e.type == "transport" and e.status == "critical" for e in entities),
            "sites": sum(e.type == "site" for e in entities), "cells": sum(e.type == "cell" for e in entities),
            "relationships": relationship_count, "counter_rows": counter_count, "severity_counts": severity_counts},
        "incidents": incidents, "alarms": [tools.alarm_dict(a) for a in alarms], "snapshot_at": DEFAULT_AS_OF})


@app.get("/api/v1/entities/{entity_id}")
def entity(entity_id: str, tools: Context):
    return tools.get_entity(entity_id)


@app.get("/api/v1/topology")
def topology(tools: Context, as_of: str = DEFAULT_AS_OF):
    return tools.overview_topology(as_of)


@app.post("/api/v1/topology/neighbors")
def neighbors(body: TopologyRequest, tools: Context):
    return tools.get_topology_neighbors(**body.model_dump())


@app.post("/api/v1/topology/shared-dependencies")
def shared(body: SharedRequest, tools: Context):
    return tools.get_shared_dependencies(**body.model_dump())


@app.get("/api/v1/kpis/{entity_id}")
def kpis(entity_id: str, tools: Context, start: str = "2026-11-10T08:00:00Z", end: str = "2026-11-10T10:15:00Z", known_at: str = OBSERVED_AT):
    return tools.get_kpi_timeseries(entity_id, start, end, known_at)


@app.get("/api/v1/alarms/{incident_id}")
def alarms(incident_id: str, tools: Context):
    return tools.get_alarm_context(incident_id)


@app.post("/api/v1/investigations")
def run_investigation(body: InvestigationRequest, tools: Context):
    tools.require("investigate")
    if production:
        # Subject and tenant come from a verified token, not caller-supplied input.
        key = (tools.customer, tools.identity.subject)
        with investigation_rate_lock:
            now = monotonic()
            started, count = investigation_rates.pop(key, (now, 0))
            if now - started >= 60:
                started, count = now, 0
            investigation_rates[key] = (started, count + 1)
            if len(investigation_rates) > 10000:
                investigation_rates.popitem(last=False)
        if count >= settings.signal_investigations_per_minute:
            raise HTTPException(429, "Investigation request limit exceeded", headers={"Retry-After": str(max(1, int(60 - now + started)))})
    if not investigation_slots.acquire(blocking=False):
        raise HTTPException(429, "Investigation capacity reached; retry shortly", headers={"Retry-After": "5"})
    try:
        return investigate(tools, body.incident_id, body.question)
    finally:
        investigation_slots.release()


@app.get("/api/v1/investigations")
def investigations(tools: Context):
    tools.require("read")
    rows = tools.session.scalars(select(Investigation).where(Investigation.customer_id == tools.customer).order_by(Investigation.created_at.desc()).limit(50))
    return {"items": [row.result for row in rows]}


@app.post("/api/v1/proposals")
def proposal(body: ActionRequest, tools: Context):
    return propose_action(tools, body.investigation_id)


@app.get("/api/v1/proposals")
def proposals(tools: Context):
    tools.require("read")
    rows = tools.session.scalars(select(Proposal).where(Proposal.customer_id == tools.customer).order_by(Proposal.created_at.desc()).limit(50))
    return {"items": [proposal_dict(p) for p in rows]}


@app.post("/api/v1/proposals/{proposal_id}/approve")
def approve(proposal_id: str, tools: Context):
    return approve_action(tools, proposal_id)


@app.post("/api/v1/proposals/{proposal_id}/execute")
def execute(proposal_id: str, tools: Context):
    tools.audit("execution_refused", {"proposal_id": proposal_id})
    raise HTTPException(403, "No network-change executor is available. Approval records review only.")


@app.get("/api/v1/quality")
def quality(tools: Context):
    return tools.data_quality()


@app.get("/api/v1/audit")
def audit(tools: Context, limit: int = Query(default=50, ge=1, le=200)):
    tools.require("read")
    rows = tools.session.scalars(select(Audit).where(Audit.customer_id == tools.customer).order_by(Audit.id.desc()).limit(limit))
    return {"customer_id": tools.customer, "items": [{"id": r.id, "actor": r.actor, "role": r.role, "operation": r.operation,
        "timestamp": r.timestamp, "details": r.details} for r in rows]}


# Register last so unknown API routes cannot resolve to the frontend.
if settings.signal_static_dir:
    static_dir = Path(settings.signal_static_dir)
    if not (static_dir / "index.html").is_file():
        raise RuntimeError("SIGNAL_STATIC_DIR must contain the built frontend")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
