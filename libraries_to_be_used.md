For your Telecom Network Intelligence Platform with role-based AI agents, I recommend React + React Flow for the frontend, Python FastAPI for the backend, and SQLite for the initial prototype.

This is a good stack for building a working demonstration within a limited timeframe. You can visualize network topology, investigate alarms, calculate KPIs, and demonstrate AI-agent tool calls without setting up a complicated cloud infrastructure.

However, SQLite should be used only for the prototype, not the full production workload of 50 million counter rows per day.
1. Recommended technology stack
Frontend
React recommended











React + React Flow

Interactive 2D network topology, node inspection, alarms and dashboards











Streamlit

Quick Python dashboards, KPI exploration and proof-of-concept demos



Requirement	Recommended library
Frontend framework	React + Vite
2D topology graph	@xyflow/react
Graph automatic layout	dagre
UI components	shadcn/ui + Tailwind CSS
KPI charts	recharts
API requests	axios
Server state	@tanstack/react-query
Backend	fastapi
API server	uvicorn
Database	SQLite
Database ORM	sqlalchemy
Schema validation	pydantic
KPI calculations	pandas, numpy
Graph traversal	networkx
AI agent orchestration	langgraph
LLM integration	langchain-openai or another model SDK
MCP tools	mcp
Testing	pytest, httpx

Estimated total: 19 core packages, excluding React/Vite build tooling, shadcn-generated components and optional dependencies. You do not need all 19 on day one.
2. React vs Streamlit
Feature	React	Streamlit
Development speed	Moderate	Very fast
Interactive 2D topology	Excellent	Limited without custom components
Custom node/edge rendering	Excellent	More difficult
Real-time alarm dashboard	Excellent	Suitable for simpler dashboards
Role-specific interfaces	Excellent	Basic to moderate
Integration with FastAPI	Excellent	Good
Production UI flexibility	High	Moderate

Choose React. The topology visualization is central to this assignment. React Flow allows you to build a telecom topology where cells, nodes, sites, services and transport dependencies appear as connected objects.






















10











You can make the graph interactive: click an affected cell, highlight its dependencies, display KPIs, and show alarm evidence in a side panel.
3. Proposed architecture
Vendor data sources

Inventory JSON/CSV • Performance counters • Alarms


Python FastAPI

Validation • Authentication • REST API • MCP tools


Connection Factory
Normalize and version inventory

KPI Engine
Calculate performance metrics

Topology Engine
Resolve graph relationships



SQLite

Entities • Relationships • KPI history • Provenance • Audit logs


React Dashboard
React Flow • KPI charts • Alarm investigation

Role-based AI Agents
Alarm • Performance • Change planning



For the demo, run ingestion and KPI calculations as Python jobs. Use synchronous REST calls for bounded graph queries and event-style triggers for alarm investigations. For production, introduce Pub/Sub, Cloud Run, BigQuery and potentially PostgreSQL as scale demands.
4. SQLite database design
SQLite can support your prototype with a relational graph model. You don't need Neo4j initially.
Table	Purpose
customers	Tenant information
entities	Cells, nodes, sites, services
relationships	Graph edges and dependencies
inventory_versions	Historical inventory records
performance_counters	Raw measurements
kpi_results	Calculated KPI values and quality
alarms	Incident and alarm records
investigations	Agent conclusions and evidence
audit_logs	Tool calls and action history
action_proposals	Recommendations and approvals

Each tenant-owned table should have a customer_id. Relationships need validity intervals such as valid_from and valid_to to support historical topology queries.

Use SQLAlchemy and indexed recursive queries for bounded traversal. NetworkX is useful for in-memory analysis of small subgraphs, but avoid loading the entire production topology into memory.
5. Example topology visualization
This is the kind of interactive 2D network you can implement using React Flow.
Network topology — incident 10:05 UTC
Demo data


Select a network entity to inspect its simulated incident details.
SITE-01NODE-01CELL-101CELL-102CELL-103TRANS-01
CELL-101
Alarm

Availability alarm

Customer: customer-01

Topology snapshot: 2026-11-10T10:05:00Z

Evidence: simulated inventory and alarm data


In the actual React application, React Flow handles dragging, zooming, node selection, edge highlighting and custom node components.
6. API and MCP contract
Build a single deterministic service layer and expose it through REST and MCP. The agent should not directly execute arbitrary SQL.

Example REST endpoint:

POST /api/v1/topology/neighbors

{
  "customer_id": "customer-01",
  "entity_id": "CELL-101",
  "as_of": "2026-11-10T10:05:00Z",
  "max_depth": 2,
  "max_results": 100
}



Example response:

{
  "entity_id": "CELL-101",
  "as_of": "2026-11-10T10:05:00Z",
  "entities": [
    {"id": "CELL-101", "type": "cell"},
    {"id": "NODE-01", "type": "node"},
    {"id": "SITE-01", "type": "site"}
  ],
  "relationships": [
    {"source": "CELL-101", "target": "NODE-01"},
    {"source": "NODE-01", "target": "SITE-01"}
  ],
  "quality": {
    "status": "complete",
    "missing_links": 0
  },
  "provenance": {
    "source": "vendor-inventory",
    "inventory_version": "v12"
  },
  "truncated": false,
  "errors": []
}



For production, derive customer_id from authenticated identity instead of trusting the request body. Enforce tenant scope and role permissions at the service/database boundary.

Recommended MCP tools: get_entity, get_topology_neighbors, get_kpi_timeseries, get_alarm_context, get_shared_dependencies, and propose_action.
7. Role-based AI agent permissions
Capability	Alarm agent	Performance agent	Change agent
Read topology	Yes	Yes	Yes
Read KPI history	Yes	Yes	Yes
Read alarms	Yes	Yes	Yes
Correlate incidents	Yes	Read-only	Read-only
Draft incident update	Yes	No	No
Recommend changes	Yes	Yes	Yes
Prepare change plan	No	No	Yes
Execute network change	No	No	No

All production changes go through a separate approval and execution service. An approved action should be checked again for tenant scope, target scope, current state, approval validity and expiry before execution.

For the first release, I would implement one LangGraph investigation workflow with role-based tool permissions, rather than three independent autonomous agents. It will be easier to test, debug and audit.
8. Installation commands
Frontend

npm create vite@latest frontend -- --template react
cd frontend
npm install

npm install @xyflow/react dagre
npm install axios @tanstack/react-query
npm install recharts lucide-react
npm install react-router-dom
npm install tailwindcss @tailwindcss/vite



Backend

mkdir backend && cd backend
python3 -m venv venv
source venv/bin/activate

pip install fastapi "uvicorn[standard]"
pip install sqlalchemy pydantic
pip install pandas numpy networkx
pip install langgraph langchain-openai
pip install mcp
pip install pytest httpx



SQLite is already included with Python through sqlite3; you don't need to install a separate SQLite server.
9. Suggested project structure

network-intelligence/
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── TopologyGraph.jsx
│       │   ├── AlarmPanel.jsx
│       │   ├── KPIDashboard.jsx
│       │   └── AgentChat.jsx
│       ├── pages/
│       │   ├── Dashboard.jsx
│       │   └── Investigation.jsx
│       └── services/api.js
│
├── backend/
│   ├── main.py
│   ├── database.py
│   ├── models/
│   ├── routers/
│   │   ├── topology.py
│   │   ├── kpi.py
│   │   └── alarms.py
│   ├── services/
│   │   ├── inventory.py
│   │   ├── topology.py
│   │   └── kpi_engine.py
│   ├── agents/
│   │   └── investigation.py
│   ├── mcp_server.py
│   └── tests/
│
└── sample_data/



10. What I would deliver for this assignment
Since the submission is limited to three hours of preparation, prioritize a clear design with one working vertical slice.
Stage 1 — Foundation

FastAPI, SQLite schema, sample vendor inventory, topology API, tenant-scoped queries.



Stage 2 — Visualization and KPIs

React Flow network graph, KPI history chart, incident view, missing-data indicators.



Stage 3 — Agent demonstration

Alarm-triggered investigation, MCP tool calls, shared-dependency analysis, evidence-backed recommendation.



For the design note, explicitly cover temporal inventory versioning, late KPI data, provenance, completeness, tenant isolation, tool budgets, human approval and evaluation tests. These matter more to the assessment than the visual polish.

One important distinction: your React + FastAPI + SQLite solution is a prototype architecture. For the specified production scale, I would move performance-counter storage and aggregation to BigQuery, run stateless APIs and agents on Cloud Run, use Pub/Sub for ingestion events, and evaluate PostgreSQL for transactional topology and inventory history. SQLite is not suitable as the shared production database at that scale.

My final recommendation is React + React Flow + FastAPI + SQLAlchemy + SQLite + NetworkX + LangGraph + MCP. This gives you a manageable, demonstrable system with a clear migration path to Google Cloud.