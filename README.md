# Signal Network Intelligence

A local project demo based on `assignment.docx` and `libraries_to_be_used.md`. React and React Flow visualize the network; FastAPI, SQLAlchemy and SQLite store five isolated sample networks; NetworkX and LangGraph correlate alarm and KPI evidence. REST and stdio MCP use the same service functions.

All network data is simulated. The agent uses Gemini function calling when configured, with a local evidence workflow when no key is present. Deterministic code controls KPI calculations and approval eligibility in both modes. No network-change executor is provided.

## Gemini and environment configuration

Local environment files are provided at `backend/.env` and `frontend/.env`, with shareable `.env.example` templates. The real `.env` files are ignored by Git. Existing files and credentials are preserved during setup.

Set these values in **backend/.env**:

```dotenv
GEMINI_API_KEY=your-google-ai-studio-api-key
GEMINI_MODEL=gemini-3.5-flash
SIGNAL_AGENT_MODE=auto
```

Get a key from [Google AI Studio](https://aistudio.google.com/apikey). Set `GEMINI_MODEL` to a function-calling model available to your project. Restart the backend after editing environment settings. Never put the key in the frontend or in a `VITE_` variable.

In **AI workbench**, enter a question or choose a suggestion, then click **Investigate incident**. Gemini chooses bounded read tools and produces a cited response. The deterministic finding, measured evidence, recommendation eligibility, provider/model label and tool trace remain visible. The same Gemini-enabled investigation is available through the MCP `investigate` tool.

- `auto`: Gemini when a key is configured; otherwise local mode. Provider errors return a local result with an explicit fallback message.
- `llm`: require Gemini. Missing credentials, quota, timeouts or invalid responses return a clear 503 error.
- `deterministic`: local mode only, with no external model calls.

`GET /api/v1/agent/status` reports configuration without revealing the key. Configuration is not a live connectivity check; the first investigation verifies the provider. The backend sets a 30-second investigation budget, at most 16 tool attempts and four model requests by default. A transient server failure may be retried once per turn within that same request/time budget; retries count toward the four-request cap. Model-generated calls cannot approve, execute, supply SQL, override customer scope or change the deterministic decision.

The integration uses Google's [official Gen AI Python SDK](https://googleapis.github.io/python-genai/#manually-declare-and-invoke-a-function-for-function-calling), with explicit function dispatch and automatic SDK tool execution disabled.

## Expanded sample data

The default database includes five isolated customers. Each has 18 sites, 36 radio nodes, 108 cells, six transports and eight services: **880 total entities**, **1,085 historical relationships**, **51,840 counter rows** and **51,840 initial KPI results**. There are 19 alarms across eight incident scenarios per customer, including transport failures, collector delay, partial measurements, a healthy-counter alarm and uncorroborated radio degradation. KPI explorer can switch between 2, 12 and 24 hours.

`SIGNAL_SEED_SITES=18` and `SIGNAL_SEED_HOURS=24` control generation. On startup, seeding upgrades the original dataset without deleting investigations, audit logs, approvals or KPI revisions. Repeated runs are idempotent. You can explicitly populate or upgrade the data with:

```bash
.venv/bin/python -m backend.seed
```

## Run locally

Prerequisites: Python 3.12 or newer, Node.js 20.19+ (or 22.12+), and npm. Run the commands from this project directory, not from `backend/`.

Terminal 1 — backend:

```bash
cd /Users/nishanth/Desktop/aman_tcs_assignment
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```bash
cd /Users/nishanth/Desktop/aman_tcs_assignment/frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. API documentation: http://127.0.0.1:8000/docs. The frontend proxies `/api` to port 8000, so no CORS setup is needed. SQLite is created and seeded automatically on the first backend startup. Subsequent starts preserve investigations, audit events and proposals.

If a port is occupied, reuse the running instance or stop it with Ctrl+C in its terminal. Both servers must run. If changing the backend port, set `API_PROXY_TARGET` in `frontend/.env` and restart Vite. Client configuration also supports `VITE_API_BASE_URL` and `VITE_API_TIMEOUT_MS`; neither should contain credentials.

## Demo walkthrough

1. Open **Network overview**. The incident affects four cells across two sites, with TRANS-01 as their shared transport dependency.
2. Open **Network topology**, click an entity, and inspect its bounded two-hop neighborhood. Use **Full network** to include the unaffected transport path and the telemetry gaps.
3. Switch the topology snapshot to **09:45 UTC**. NODE-02 uses TRANS-02. At **10:05 UTC**, the topology reflects the change to TRANS-01 effective at 10:00.
4. Open **AI workbench** and choose **Transport failure**. Run the investigation to see the shared dependency, before/during KPI comparison, uncertainties, and tool trace.
5. Choose **Missing telemetry**. CELL-103 has null incident-window values; the workflow declines a network-change recommendation. **Conflicting evidence** demonstrates partial measurements and an unresolved inventory reference.
6. Switch among **Alarm management**, **Performance analysis**, and **Change planning**. The same trusted evidence produces role-specific outputs. The **Human approver** cannot initiate investigations or draft proposals.
7. For a sufficient-evidence investigation, click **Draft review proposal**. Switch to **Human approver** and record the review. No executor is provided, even after approval.
8. Change the customer to inspect isolated records. Entity identifiers intentionally repeat between customers; customer scope comes from the selected demo identity.
9. Open **KPI explorer**, **Data quality**, and **Audit trail** to inspect completeness, versioned inventory, quarantined sample records, and persisted tool events. Export a JSON snapshot from the top-right button.

The event clock is fixed to 10 November 2026: incident 10:05 UTC, evidence observed at 10:20 UTC. Audit and proposal creation/expiry use the actual wall clock. Changing the topology snapshot changes historical relationships; KPI explorer and agent investigations continue to use the stated incident reporting windows. All five tenants use the same scenario templates with separate stored records.

## Validation

From the project root:

```bash
.venv/bin/python -m pytest -q
```

From `frontend/`:

```bash
npm run build
```

The regression suite covers weighted KPI calculations, null and partial data, append-only late-data revisions, historical topology, query bounds, tenant isolation, role restrictions, independent approval, expiry, denied actions, expanded data and shared MCP service behavior. Gemini tests mock provider responses while exercising SDK types, the dispatcher and the workflow; no API credits are spent. They cover successful tool calls, invented citations, missing keys, provider failure, strict mode, forbidden tools and model budgets. Tests use a temporary database and do not modify the interactive demo data.

## MCP

Run the stdio server from the project root:

```bash
SIGNAL_DEMO_TOKEN=demo-atlas-alarm .venv/bin/python -m backend.mcp_server
```

Use this process configuration in an MCP host that supports stdio:

```json
{
  "mcpServers": {
    "signal": {
      "command": "/Users/nishanth/Desktop/aman_tcs_assignment/.venv/bin/python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "/Users/nishanth/Desktop/aman_tcs_assignment",
      "env": { "SIGNAL_DEMO_TOKEN": "demo-atlas-alarm" }
    }
  }
}
```

The MCP host must launch from this working directory (or set PYTHONPATH). The process identity is fixed at launch. Tools cannot supply their own customer or role. The seven tools are `get_entity`, `get_topology_neighbors`, `get_kpi_timeseries`, `get_alarm_context`, `get_shared_dependencies`, `investigate`, and `propose_action`. The investigation accepts an optional `question` and reads Gemini configuration from backend/.env. No approval or execution tool is exposed through MCP.

## Project map

- `frontend/src/components/`: React Flow topology, Recharts KPIs, investigation display and shadcn-style UI primitives.
- `backend/main.py`: FastAPI adapters, authentication dependencies and error responses.
- `backend/services/`: shared query, KPI, LangGraph and proposal logic.
- `backend/database.py`: tenant-scoped SQLAlchemy records.
- `backend/seed.py` and `sample_data/inventory.json`: reproducible demonstration fixtures.
- `backend/mcp_server.py`: stdio MCP adapters over the same services.
- `backend/tests/`: regression tests.
- `docs/design.md`: short design note, architecture and production migration plan.
- `docs/api-contract.md`: example REST/MCP contract and operational limits.

## Prototype boundaries

Public `demo-<customer>-<role>` bearer identities are intentional for local demonstration; they are not production authentication. Keep the servers bound to localhost. A production service needs verified OIDC identities, database isolation policies, stronger execution deadlines, concurrency limits and a separate authorized execution service.

Inventory ingestion and quarantine results are seeded fixtures rather than a running vendor connector. KPI calculation and revision publication are implemented; late-arrival recalculation is tested, not driven by a live ingestion scheduler. SQLite, current entity attributes and fixed sample formulas are prototype choices. The historical relationship intervals work for the seeded route change; full bitemporal inventory corrections and historical entity attributes are production work described in the design note. No production scale or latency claim has been validated.
