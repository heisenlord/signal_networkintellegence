"""Reproducible fixtures for transport failure, late telemetry and conflicting evidence."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from backend.auth import CUSTOMERS
from backend.config import get_settings
from backend.database import Alarm, Base, Counter, Customer, DatasetState, Entity, InventoryVersion, KPI, Relationship, Session, engine
from backend.scenarios import DEGRADED_CELLS, EXTRA_ALARMS, MISSING_CELLS, PARTIAL_CELLS
from backend.services.kpi import publish, publish_new_sample_counters

INCIDENT_TIME = "2026-11-10T10:05:00Z"
OBSERVED_AT = "2026-11-10T10:20:00Z"


def _seed_core():
    Base.metadata.create_all(engine)
    with Session.begin() as session:
        if session.scalar(select(Customer.id).limit(1)):
            return
        inventory = json.loads((Path(__file__).parents[1] / "sample_data/inventory.json").read_text())
        for cid, name, region in CUSTOMERS:
            session.add(Customer(id=cid, name=name, region=region))
            for item in inventory["entities"]:
                session.add(Entity(customer_id=cid, **item, metadata_json={"source": inventory["source"], "inventory_version": "v12", "region": region,
                    "unresolved_references": 1 if item["id"] == "CELL-301" else 0}))
            session.flush()
            for source, target, kind in inventory["relationships"]:
                old_route = source == "NODE-02" and kind == "backhaul"
                session.add(Relationship(customer_id=cid, source=source, target=target, kind=kind, valid_from=inventory["effective_at"],
                    valid_to="2026-11-10T10:00:00Z" if old_route else None, recorded_at="2026-11-10T08:02:00Z", version="v11"))
            session.add(Relationship(customer_id=cid, source="NODE-02", target="TRANS-01", kind="backhaul", valid_from="2026-11-10T10:00:00Z",
                valid_to=None, recorded_at="2026-11-10T10:02:00Z", version="v12"))
            for version, effective, received in [("v11", "08:00", "08:02"), ("v12", "10:00", "10:02")]:
                session.add(InventoryVersion(customer_id=cid, id=version, effective_at=f"2026-11-10T{effective}:00Z", received_at=f"2026-11-10T{received}:00Z",
                    source=inventory["source"], accepted=31 if version == "v11" else 1, rejected=0 if version == "v11" else 3,
                    issues=[] if version == "v11" else inventory["quarantined_examples"]))
            cells = [item["id"] for item in inventory["entities"] if item["type"] == "cell"]
            for cell in cells:
                for i in range(9):
                    dt = datetime(2026, 11, 10, 8, tzinfo=timezone.utc) + timedelta(minutes=i * 15)
                    window = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
                    during = i >= 8
                    missing = cell == "CELL-103" and during
                    partial = cell == "CELL-301" and during
                    samples = 0 if missing else 8 if partial else 15
                    availability = (62.4 + (int(cell[-1]) % 3) * 1.1) if during and cell != "CELL-103" else 99.7 + (i % 3) * 0.1
                    counter = Counter(customer_id=cid, entity_id=cell, window=window,
                        successful_seconds=samples * 60 * availability / 100, observed_seconds=samples * 60,
                        samples=samples, expected_samples=15,
                        received_at=OBSERVED_AT if during else (dt + timedelta(minutes=17)).isoformat(timespec="seconds").replace("+00:00", "Z"),
                        throughput_mbps=round(22 + i * 0.7 if during else 85 + i * 2.4 + int(cell[-1]), 1))
                    session.add(counter)
                    publish(session, counter, OBSERVED_AT)
            alarm_specs = [
                ("ALM-001", "CELL-101", "INC-1005", "Cell availability degraded", "critical"),
                ("ALM-002", "CELL-102", "INC-1005", "Cell availability degraded", "critical"),
                ("ALM-003", "CELL-201", "INC-1005", "Cell availability degraded", "critical"),
                ("ALM-004", "CELL-202", "INC-1005", "Cell availability degraded", "critical"),
                ("ALM-005", "TRANS-01", "INC-1005", "Transport link down", "critical"),
                ("ALM-006", "CELL-103", "INC-1020", "Performance measurements absent", "warning"),
                ("ALM-007", "CELL-301", "INC-1035", "Availability degradation; partial counters", "major"),
            ]
            for aid, entity, incident, title, severity in alarm_specs:
                session.add(Alarm(customer_id=cid, id=aid, entity_id=entity, incident_id=incident, title=title, severity=severity,
                    occurred_at=INCIDENT_TIME, evidence={"source": "vendor-alarm-demo", "received_at": "2026-11-10T10:05:04Z", "simulated": True}))


def _expand_dataset():
    settings = get_settings()
    config = {"version": 3, "sites": settings.signal_seed_sites, "hours": settings.signal_seed_hours}
    with Session.begin() as session:
        state = session.get(DatasetState, "expanded-sample-data")
        if state and state.config == config:
            return
        site_count = config["sites"]
        window_count = config["hours"] * 4
        start = datetime(2026, 11, 10, 10, 15, tzinfo=timezone.utc) - timedelta(hours=config["hours"])
        for customer_index, (cid, _, region) in enumerate(CUSTOMERS):
            entities = {e.id: e for e in session.scalars(select(Entity).where(Entity.customer_id == cid))}
            edges = {(e.source, e.target, e.kind) for e in session.scalars(select(Relationship).where(Relationship.customer_id == cid))}

            def entity(entity_id, name, kind, vendor="Ericsson", status="healthy"):
                if entity_id not in entities:
                    row = Entity(customer_id=cid, id=entity_id, name=name, type=kind, vendor=vendor, status=status,
                        metadata_json={"source": "generated-vendor-demo", "inventory_version": "v12", "region": region,
                            "unresolved_references": 1 if entity_id == "CELL-601" else 0})
                    session.add(row)
                    entities[entity_id] = row

            def edge(source, target, kind):
                if (source, target, kind) not in edges:
                    session.add(Relationship(customer_id=cid, source=source, target=target, kind=kind,
                        valid_from="2026-11-09T00:00:00Z", valid_to=None, recorded_at="2026-11-09T00:02:00Z", version="v11"))
                    edges.add((source, target, kind))

            for number in range(3, 7):
                entity(f"TRANS-{number:02}", f"{region} aggregation {number}", "transport", "Cisco" if number % 2 else "Juniper", "critical" if number == 3 else "healthy")
            for number in range(4, 9):
                entity(f"SVC-{number:02}", ["IoT connectivity", "Private 5G", "Emergency voice", "Fixed wireless", "Enterprise VPN"][number - 4], "service", "Internal")
            entity("SVC-03", "Retail data services", "service", "Internal", "degraded")
            for number in range(1, site_count + 1):
                entity(f"SITE-{number:02}", f"{region} zone {number:02}", "site", "Nokia" if number % 2 == 0 else "Ericsson",
                    "degraded" if number in {4, 6, 8, 9} else "healthy")
            for number in range(1, site_count * 2 + 1):
                node = f"NODE-{number:02}"
                site = f"SITE-{(number - 1) % site_count + 1:02}"
                vendor = "Nokia" if number % 2 == 0 else "Ericsson"
                entity(node, f"{region} radio node {number:02}", "node", vendor,
                    "degraded" if number in {4, 6, 8, 9} else "unknown" if number == 5 else "healthy")
                if number > 3:
                    edge(node, site, "hosted_at")
                    edge(node, f"TRANS-{3 + (number - 4) % 4:02}", "backhaul")
                for sector in range(1, 4):
                    cell = f"CELL-{number}{sector:02}"
                    status = "unknown" if cell in MISSING_CELLS else "degraded" if cell in PARTIAL_CELLS or cell in {"CELL-901", "CELL-902"} else "critical" if cell in DEGRADED_CELLS else "healthy"
                    entity(cell, f"{region} sector {number:02}{chr(64 + sector)}", "cell", vendor, status)
                    if cell not in {"CELL-101", "CELL-102", "CELL-103", "CELL-201", "CELL-202", "CELL-301"}:
                        edge(cell, node, "depends_on")
                    if number >= 4 and sector == 1:
                        edge(f"SVC-{3 + (number - 4) % 6:02}", cell, "depends_on")
            session.flush()
            existing_alarms = set(session.scalars(select(Alarm.id).where(Alarm.customer_id == cid)))
            for aid, target, incident, title, severity in EXTRA_ALARMS:
                if aid not in existing_alarms:
                    session.add(Alarm(customer_id=cid, id=aid, entity_id=target, incident_id=incident, title=title, severity=severity,
                        occurred_at=INCIDENT_TIME, evidence={"source": "generated-vendor-alarm-demo", "received_at": "2026-11-10T10:05:04Z", "simulated": True}))
            existing = set(session.execute(select(Counter.entity_id, Counter.window).where(Counter.customer_id == cid)).all())
            records = []
            for cell in sorted(e for e in entities if e.startswith("CELL-")):
                number = int(cell[5:-2])
                for index in range(window_count):
                    window_dt = start + timedelta(minutes=index * 15)
                    window = window_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
                    if (cell, window) in existing:
                        continue
                    during = window >= "2026-11-10T10:00:00Z"
                    samples = 0 if during and cell in MISSING_CELLS else 8 if during and cell in PARTIAL_CELLS else 15
                    availability = round(99.6 + ((index + number + customer_index) % 4) * .1, 2)
                    if during and cell in DEGRADED_CELLS:
                        availability = round(61.5 + (number % 5) + customer_index * .3, 2)
                    observed = samples * 60
                    records.append({"customer_id": cid, "entity_id": cell, "window": window,
                        "successful_seconds": round(observed * availability / 100, 6), "observed_seconds": observed,
                        "samples": samples, "expected_samples": 15, "received_at": OBSERVED_AT if during else
                            (window_dt + timedelta(minutes=17)).isoformat(timespec="seconds").replace("+00:00", "Z"),
                        "throughput_mbps": round((23 if during and cell in DEGRADED_CELLS else 80) + ((index * 7 + number * 3 + customer_index) % 35), 1)})
            publish_new_sample_counters(session, records, OBSERVED_AT)
            version = session.get(InventoryVersion, (cid, "v11"))
            version.accepted = len(entities) + len(edges)
            version = session.get(InventoryVersion, (cid, "v12"))
            if not any(issue["record"].startswith("CELL-601") for issue in version.issues):
                version.issues = [*version.issues, {"record": "CELL-601 → NODE-999",
                    "reason": "Unresolved secondary reference in generated inventory; excluded from trusted topology"}]
                version.rejected = len(version.issues)
        if state:
            state.config = config
        else:
            session.add(DatasetState(id="expanded-sample-data", config=config))


def seed():
    """Upgrade generated data without deleting existing investigations or approvals."""
    _seed_core()
    _expand_dataset()


if __name__ == "__main__":
    seed()
    from sqlalchemy import func
    with Session() as session:
        print(json.dumps({"customers": session.scalar(select(func.count()).select_from(Customer)),
            "entities": session.scalar(select(func.count()).select_from(Entity)),
            "relationships": session.scalar(select(func.count()).select_from(Relationship)),
            "counters": session.scalar(select(func.count()).select_from(Counter)),
            "kpi_results": session.scalar(select(func.count()).select_from(KPI))}))
