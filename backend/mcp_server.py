"""Stdio MCP adapter. Set a fixed demo identity in the process environment.

No tool accepts customer_id or an arbitrary role. The host binds that identity
at launch; production remote MCP needs verified per-request OAuth/OIDC instead.
"""
import os

from mcp.server.fastmcp import FastMCP

from backend.auth import IDENTITIES
from backend.config import get_settings
from backend.database import Session
from backend.seed import seed
from backend.services.actions import propose_action as service_propose
from backend.services.investigation import investigate as service_investigate
from backend.services.tools import DEFAULT_AS_OF, Tools

mcp = FastMCP("Signal Network Intelligence")


def invoke(name, *args, **kwargs):
    if get_settings().signal_environment == "production":
        raise ValueError("Demo stdio MCP is disabled in production; use the authenticated REST API")
    identity = IDENTITIES.get(os.getenv("SIGNAL_DEMO_TOKEN", ""))
    if identity is None:
        raise ValueError("SIGNAL_DEMO_TOKEN must identify an explicit demo customer and role")
    with Session() as session:
        tools = Tools(session, identity)
        if name == "propose_action":
            result = service_propose(tools, *args, **kwargs)
        elif name == "investigate":
            result = service_investigate(tools, *args, **kwargs)
        else:
            result = getattr(tools, name)(*args, **kwargs)
        session.commit()
        return result


@mcp.tool()
def get_entity(entity_id: str) -> dict:
    """Read one entity within the process's fixed authenticated customer scope."""
    return invoke("get_entity", entity_id)


@mcp.tool()
def get_topology_neighbors(entity_id: str, as_of: str = DEFAULT_AS_OF, max_depth: int = 2, max_results: int = 100) -> dict:
    """Bounded historical topology with completeness, lineage and truncation."""
    return invoke("get_topology_neighbors", entity_id, as_of, max_depth, max_results)


@mcp.tool()
def get_kpi_timeseries(entity_id: str, start: str = "2026-11-10T08:00:00Z", end: str = "2026-11-10T10:15:00Z") -> dict:
    """Read at most 24 hours of versioned KPIs, including missing evidence."""
    return invoke("get_kpi_timeseries", entity_id, start, end)


@mcp.tool()
def get_alarm_context(incident_id: str) -> dict:
    """Read alarm evidence for an incident."""
    return invoke("get_alarm_context", incident_id)


@mcp.tool()
def get_shared_dependencies(entity_ids: list[str], as_of: str = DEFAULT_AS_OF) -> dict:
    """Find shared dependencies for 1–10 entities in a bounded subgraph."""
    return invoke("get_shared_dependencies", entity_ids, as_of)


@mcp.tool()
def investigate(incident_id: str, question: str = "") -> dict:
    """Run the role-scoped LangGraph investigation and optional Gemini tool loop."""
    if len(question) > 1500:
        raise ValueError("Question must be at most 1500 characters")
    return invoke("investigate", incident_id, question)


@mcp.tool()
def propose_action(investigation_id: str) -> dict:
    """Draft a proposal from sufficient evidence. Cannot approve or execute."""
    return invoke("propose_action", investigation_id)


if __name__ == "__main__":
    if get_settings().signal_environment == "production":
        raise SystemExit("Demo stdio MCP is disabled in production")
    seed()
    mcp.run(transport="stdio")
