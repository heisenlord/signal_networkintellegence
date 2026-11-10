"""Deterministic services shared verbatim by REST, LangGraph and MCP adapters."""
import time
from datetime import datetime, timezone
from uuid import uuid4

import networkx as nx
from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from backend.auth import Principal, utcnow
from backend.database import Alarm, Audit, Counter, Entity, InventoryVersion, KPI, Relationship
from backend.seed import OBSERVED_AT

DEFAULT_AS_OF = "2026-11-10T10:05:00Z"


def timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError as exc:
        raise HTTPException(422, "Use an ISO-8601 timestamp with a timezone") from exc


def serialize_entity(entity: Entity):
    return {"id": entity.id, "name": entity.name, "type": entity.type, "vendor": entity.vendor,
            "status": entity.status, "metadata": entity.metadata_json}


class Tools:
    def __init__(self, session, identity: Principal, request_id: str | None = None):
        self.session, self.identity = session, identity
        self.customer = identity.customer_id
        self.request_id = request_id or str(uuid4())

    def audit(self, operation: str, details: dict):
        self.session.add(Audit(customer_id=self.customer, actor=self.identity.subject, role=self.identity.role,
            operation=operation, timestamp=utcnow(), details={"request_id": self.request_id, **details}))
        self.session.flush()

    def require(self, permission: str):
        self.identity.require(permission)

    def envelope(self, operation: str, payload: dict, status="complete", **extra):
        self.require("read")
        self.audit(operation, {"quality": status, "truncated": extra.get("truncated", False)})
        return {"request_id": self.request_id, "customer_id": self.customer, "observed_at": OBSERVED_AT,
            "provenance": {"source": "simulated-vendor-feeds", "inventory_version": "v12", "simulated": True},
            "quality": {"status": status}, "truncated": False, "errors": [], **payload, **extra}

    def entity(self, entity_id: str):
        self.require("read")
        entity = self.session.get(Entity, (self.customer, entity_id))
        if not entity:
            raise HTTPException(404, "Entity not found in the current customer scope")
        return entity

    def get_entity(self, entity_id: str):
        entity = self.entity(entity_id)
        missing = entity.metadata_json.get("unresolved_references", 0)
        return self.envelope("get_entity", {"entity": serialize_entity(entity)}, "partial" if missing else "complete")

    def active_edges(self, as_of: str, known_at: str = OBSERVED_AT, frontier: set | None = None, limit=501):
        statement = select(Relationship).where(Relationship.customer_id == self.customer,
            Relationship.valid_from <= as_of, or_(Relationship.valid_to.is_(None), Relationship.valid_to > as_of),
            Relationship.recorded_at <= known_at)
        if frontier is not None:
            statement = statement.where(or_(Relationship.source.in_(frontier), Relationship.target.in_(frontier)))
        return list(self.session.scalars(statement.order_by(Relationship.id).limit(limit)))

    def get_topology_neighbors(self, entity_id: str, as_of=DEFAULT_AS_OF, max_depth=2, max_results=100, known_at=OBSERVED_AT):
        self.entity(entity_id)
        if not 1 <= max_depth <= 2 or not 1 <= max_results <= 100:
            raise HTTPException(422, "Topology budget is depth 1–2 and 1–100 entities")
        as_of, known_at = timestamp(as_of), timestamp(known_at)
        seen, frontier, edges = {entity_id}, {entity_id}, {}
        truncated = False
        started = time.monotonic()
        for _ in range(max_depth):
            rows = self.active_edges(as_of, known_at, frontier, limit=301)
            if len(rows) > 300:
                truncated = True
            next_frontier = set()
            for edge in rows[:300]:
                new_ids = {edge.source, edge.target} - seen
                if len(seen | new_ids) > max_results or len(edges) >= 300:
                    truncated = True
                    continue
                edges[edge.id] = edge
                next_frontier |= new_ids
                seen |= new_ids
            frontier = next_frontier
            if not frontier:
                break
            if time.monotonic() - started >= 1.5:
                truncated = True
                break
        entities = list(self.session.scalars(select(Entity).where(Entity.customer_id == self.customer, Entity.id.in_(seen)).order_by(Entity.id)))
        unresolved = sum(e.metadata_json.get("unresolved_references", 0) for e in entities)
        version = "v12" if as_of >= "2026-11-10T10:00:00Z" and known_at >= "2026-11-10T10:02:00Z" else "v11"
        return self.envelope("get_topology_neighbors", {"entity_id": entity_id, "as_of": as_of, "known_at": known_at,
            "entities": [serialize_entity(e) for e in entities], "relationships": [self.edge_dict(e) for e in edges.values()]},
            "partial" if truncated or unresolved else "complete", truncated=truncated,
            quality={"status": "partial" if truncated or unresolved else "complete", "missing_links": unresolved},
            provenance={"source": "vendor-inventory-demo", "inventory_version": version, "simulated": True},
            budget={"max_depth": max_depth, "max_results": max_results, "max_edges": 300, "deadline_ms": 1500})

    @staticmethod
    def edge_dict(e):
        return {"id": str(e.id), "source": e.source, "target": e.target, "kind": e.kind,
                "valid_from": e.valid_from, "valid_to": e.valid_to, "recorded_at": e.recorded_at, "version": e.version}

    def overview_topology(self, as_of=DEFAULT_AS_OF):
        self.require("read")
        as_of = timestamp(as_of)
        entities = list(self.session.scalars(select(Entity).where(Entity.customer_id == self.customer).order_by(Entity.id).limit(201)))
        edges = self.active_edges(as_of)
        truncated = len(entities) > 200 or len(edges) > 500
        ids = {e.id for e in entities[:200]}
        return self.envelope("get_topology_overview", {"as_of": as_of, "entities": [serialize_entity(e) for e in entities[:200]],
            "relationships": [self.edge_dict(e) for e in edges[:500] if e.source in ids and e.target in ids]}, "partial", truncated=truncated)

    def get_kpi_timeseries(self, entity_id: str, start="2026-11-10T08:00:00Z", end="2026-11-10T10:15:00Z", known_at=OBSERVED_AT):
        entity = self.entity(entity_id)
        start, end, known_at = timestamp(start), timestamp(end), timestamp(known_at)
        if start >= end or (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() > 86400:
            raise HTTPException(422, "KPI lookup must be an ordered interval of at most 24 hours")
        rows = self.session.scalars(select(KPI).where(KPI.customer_id == self.customer, KPI.entity_id == entity_id,
            KPI.window >= start, KPI.window < end, KPI.computed_at <= known_at).order_by(KPI.window, KPI.revision).limit(1000))
        latest = {row.window: row for row in rows}
        points = [{"window": row.window, "availability": row.availability, "throughput_mbps": row.throughput_mbps,
            "completeness": row.completeness, "quality": row.quality, "formula_version": row.formula_version,
            "revision": row.revision, "final": row.final, "computed_at": row.computed_at} for row in latest.values()]
        quality = "unavailable" if not points or all(p["quality"] == "unavailable" for p in points) else "partial" if any(p["quality"] != "complete" for p in points) else "complete"
        return self.envelope("get_kpi_timeseries", {"entity_id": entity_id, "entity_type": entity.type, "start": start, "end": end,
            "known_at": known_at, "window_minutes": 15, "watermark_delay_minutes": 120, "points": points}, quality)

    def get_alarm_context(self, incident_id: str):
        self.require("read")
        alarms = list(self.session.scalars(select(Alarm).where(Alarm.customer_id == self.customer, Alarm.incident_id == incident_id).order_by(Alarm.id).limit(101)))
        if not alarms:
            raise HTTPException(404, "Incident not found in the current customer scope")
        return self.envelope("get_alarm_context", {"incident_id": incident_id, "alarms": [self.alarm_dict(a) for a in alarms[:100]]}, truncated=len(alarms) > 100)

    @staticmethod
    def alarm_dict(a):
        return {"id": a.id, "entity_id": a.entity_id, "incident_id": a.incident_id, "title": a.title,
                "severity": a.severity, "occurred_at": a.occurred_at, "evidence": a.evidence}

    def get_shared_dependencies(self, entity_ids: list[str], as_of=DEFAULT_AS_OF):
        if not 1 <= len(entity_ids) <= 10:
            raise HTTPException(422, "Shared-dependency query requires 1–10 entities")
        as_of = timestamp(as_of)
        graph = nx.DiGraph()
        truncation = False
        incomplete = False
        for entity_id in entity_ids:
            self.entity(entity_id)
            # Reuse the same bounded SQL traversal; never build a production-wide graph.
            result = self.get_topology_neighbors(entity_id, as_of, max_depth=2)
            truncation |= result["truncated"]
            incomplete |= result["quality"]["status"] != "complete"
            graph.add_edges_from((e["source"], e["target"]) for e in result["relationships"])
        reachable = [set(nx.single_source_shortest_path_length(graph, e, cutoff=2)) - {e} if e in graph else set() for e in entity_ids]
        shared = set.intersection(*reachable)
        entities = [self.entity(e) for e in sorted(shared)]
        entities = [e for e in entities if e.type in {"transport", "site", "node"}]
        return self.envelope("get_shared_dependencies", {"entity_ids": entity_ids, "as_of": as_of,
            "shared_dependencies": [serialize_entity(e) for e in entities]}, "partial" if incomplete or truncation else "complete", truncated=truncation)

    def data_quality(self):
        versions = list(self.session.scalars(select(InventoryVersion).where(InventoryVersion.customer_id == self.customer).order_by(InventoryVersion.received_at.desc())))
        gaps = list(self.session.scalars(select(Counter).where(Counter.customer_id == self.customer,
            Counter.window == "2026-11-10T10:00:00Z", Counter.samples < Counter.expected_samples).order_by(Counter.entity_id).limit(100)))
        return self.envelope("get_data_quality", {"versions": [{"id": v.id, "source": v.source, "effective_at": v.effective_at,
            "received_at": v.received_at, "accepted": v.accepted, "rejected": v.rejected, "issues": v.issues} for v in versions],
            "watermark": "2026-11-10T08:20:00Z", "observed_at": OBSERVED_AT,
            "late_entity": "CELL-103", "partial_entity": "CELL-301",
            "gaps": [{"entity_id": row.entity_id, "received": row.samples, "expected": row.expected_samples,
                "quality": "missing" if row.samples == 0 else "partial"} for row in gaps]}, "partial")
