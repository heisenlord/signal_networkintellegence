# REST and MCP contract example

The caller authenticates with a demo bearer identity. Customer and role are derived from the server's token mapping. Extra body fields, including `customer_id` or a role override, are rejected. Production should replace the public demo mapping with verified claims.

## Topology request

```http
POST /api/v1/topology/neighbors
Authorization: Bearer demo-atlas-alarm
Content-Type: application/json

{
  "entity_id": "CELL-101",
  "as_of": "2026-11-10T10:05:00Z",
  "known_at": "2026-11-10T10:20:00Z",
  "max_depth": 2,
  "max_results": 100
}
```

The response includes identity, effective and knowledge timestamps, canonical entities, effective-dated relationships, provenance, quality, truncation, errors and budget. The following shows the envelope and selected entries; the actual response includes the full bounded neighborhood.

```json
{
  "request_id": "server-generated-uuid",
  "customer_id": "atlas",
  "observed_at": "2026-11-10T10:20:00Z",
  "entity_id": "CELL-101",
  "as_of": "2026-11-10T10:05:00Z",
  "known_at": "2026-11-10T10:20:00Z",
  "entities": [
    {
      "id": "CELL-101",
      "name": "Bandra sector A",
      "type": "cell",
      "vendor": "Ericsson",
      "status": "critical",
      "metadata": {
        "source": "vendor-inventory-demo",
        "inventory_version": "v12",
        "region": "Mumbai",
        "unresolved_references": 0
      }
    }
  ],
  "relationships": [
    {
      "id": "7",
      "source": "CELL-101",
      "target": "NODE-01",
      "kind": "depends_on",
      "valid_from": "2026-11-10T08:00:00Z",
      "valid_to": null,
      "recorded_at": "2026-11-10T08:02:00Z",
      "version": "v11"
    }
  ],
  "quality": { "status": "complete", "missing_links": 0 },
  "provenance": {
    "source": "vendor-inventory-demo",
    "inventory_version": "v12",
    "simulated": true
  },
  "truncated": false,
  "errors": [],
  "budget": { "max_depth": 2, "max_results": 100, "max_edges": 300, "deadline_ms": 1500 }
}
```

`status` on an entity is a sample incident annotation rather than a historical health reconstruction. `known_at` filters newly recorded edges but does not reconstruct knowledge of interval closures; the full bitemporal production model is described in the design note. IDs in this illustrative response are local to the seeded database.

Equivalent MCP call: `get_topology_neighbors(entity_id="CELL-101", as_of="2026-11-10T10:05:00Z", max_depth=2, max_results=100)`. Its process identity comes from `SIGNAL_DEMO_TOKEN`, never from a tool argument. MCP uses the default knowledge timestamp in this demo.

## Other operations

- `GET /api/v1/entities/{id}` → `get_entity`: canonical identity and unresolved-reference flag.
- `GET /api/v1/kpis/{id}?start=...&end=...&known_at=...` → `get_kpi_timeseries`: at most 24 hours, half-open range, timestamped points with formula version, revision, completeness, quality and finality. Null values mean unavailable evidence.
- `GET /api/v1/alarms/{incident_id}` → `get_alarm_context`: at most 100 alarms, occurrence times and vendor evidence.
- `POST /api/v1/topology/shared-dependencies` with `entity_ids` and `as_of` → `get_shared_dependencies`: at most ten entities and a bounded subgraph.
- `POST /api/v1/investigations` with `incident_id` and optional `question` (at most 1,500 characters) → `investigate`: role-specific finding, measured evidence, uncertainty and tool trace.
- `POST /api/v1/proposals` with `investigation_id` → `propose_action`: persisted review proposal derived from an existing sufficient-evidence investigation.
- `POST /api/v1/proposals/{id}/approve`: human-approver-only REST operation. No MCP approval tool.
- `POST /api/v1/proposals/{id}/execute`: always refused. No execution implementation or MCP tool.

## Errors and limits

401 indicates missing or invalid identity; 403 a forbidden role/action; 404 an object absent in the authenticated scope; 409 insufficient evidence, expired/previously reviewed proposal or changed target; 422 invalid shape, timestamps, range or query bounds; 408 workflow evidence-budget exhaustion. HTTP exceptions include a request ID and structured errors; Pydantic validation errors use FastAPI's validation response and carry the request ID in the response header.

Topology truncation is returned explicitly with partial quality. Tool traces count top-level workflow calls and reference the same request ID as nested audited calls. Hard cancellation, distributed admission control, database statement deadlines and monetary query budgets remain production work. OpenAPI is generated at `/openapi.json`, with interactive documentation at `/docs` on the backend origin.

## Gemini investigation

POST /api/v1/investigations accepts, for example, {"incident_id": "INC-1005", "question": "Compare the affected cells across the previous 24 hours and explain the likely shared cause."}. The equivalent MCP tool is investigate(incident_id, question).

The result retains deterministic classification, confidence, can_recommend, target and evidence. Additional fields include provider, model, mode, llm_used, llm_attempted, llm_error, model_calls, token_usage and agent_response, containing answer, next_steps and observed-ID citations. Trace entries identify origin=gemini for model-selected calls. Invalid citations or provider failures fall back visibly in auto mode; required LLM mode returns 503 instead.

GET /api/v1/agent/status reports configuration, budgets and key-presence without credential values. It does not verify provider connectivity; the first investigation does that. The dashboard shows the active mode and lets the operator enter an investigation question.

The workflow first collects deterministic incident evidence, then allows Gemini to request additional read tools. It does not use MCP transport internally; its dispatcher shares the same tenant-scoped services that the external MCP server exposes. The MCP investigate operation runs this same workflow.
