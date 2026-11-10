"""Small local SQLite store. Every customer-owned record has a tenant key."""
import os
from pathlib import Path

from sqlalchemy import JSON, Boolean, Float, ForeignKeyConstraint, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.config import get_settings

get_settings()

DATA = Path(__file__).parent / "data"
DATABASE_URL = os.getenv("SIGNAL_DATABASE_URL", f"sqlite:///{DATA / 'signal.db'}")
if "SIGNAL_DATABASE_URL" not in os.environ:
    DATA.mkdir(exist_ok=True)
if not DATABASE_URL.startswith("sqlite:///"):
    raise ValueError("This deployment supports SQLite only; configure SIGNAL_DATABASE_URL with sqlite:///")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    region: Mapped[str]


class DatasetState(Base):
    __tablename__ = "demo_dataset_state"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    config: Mapped[dict] = mapped_column(JSON)


class Entity(Base):
    __tablename__ = "entities"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    type: Mapped[str]
    vendor: Mapped[str]
    status: Mapped[str]
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Relationship(Base):
    __tablename__ = "relationships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str]
    target: Mapped[str]
    kind: Mapped[str]
    valid_from: Mapped[str] = mapped_column(String, index=True)
    valid_to: Mapped[str | None]
    recorded_at: Mapped[str]
    version: Mapped[str]
    __table_args__ = (
        ForeignKeyConstraint(["customer_id", "source"], ["entities.customer_id", "entities.id"]),
        ForeignKeyConstraint(["customer_id", "target"], ["entities.customer_id", "entities.id"]),
    )


class InventoryVersion(Base):
    __tablename__ = "inventory_versions"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    effective_at: Mapped[str]
    received_at: Mapped[str]
    source: Mapped[str]
    accepted: Mapped[int]
    rejected: Mapped[int]
    issues: Mapped[list] = mapped_column(JSON)


class Counter(Base):
    __tablename__ = "performance_counters"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    window: Mapped[str] = mapped_column(String, primary_key=True)
    successful_seconds: Mapped[float] = mapped_column(Float)
    observed_seconds: Mapped[float] = mapped_column(Float)
    samples: Mapped[int]
    expected_samples: Mapped[int]
    received_at: Mapped[str]
    throughput_mbps: Mapped[float]


class KPI(Base):
    __tablename__ = "kpi_results"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    window: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    formula_version: Mapped[str]
    availability: Mapped[float | None]
    throughput_mbps: Mapped[float | None]
    completeness: Mapped[float]
    quality: Mapped[str]
    computed_at: Mapped[str]
    final: Mapped[bool] = mapped_column(Boolean)


class Alarm(Base):
    __tablename__ = "alarms"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_id: Mapped[str]
    incident_id: Mapped[str]
    title: Mapped[str]
    severity: Mapped[str]
    occurred_at: Mapped[str]
    evidence: Mapped[dict] = mapped_column(JSON)


class Investigation(Base):
    __tablename__ = "investigations"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str]
    created_at: Mapped[str]
    result: Mapped[dict] = mapped_column(JSON)


class Proposal(Base):
    __tablename__ = "action_proposals"
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    investigation_id: Mapped[str]
    created_by: Mapped[str]
    title: Mapped[str]
    target: Mapped[str]
    status: Mapped[str]
    created_at: Mapped[str]
    expires_at: Mapped[str]
    approved_by: Mapped[str | None]


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str]
    role: Mapped[str]
    operation: Mapped[str]
    timestamp: Mapped[str]
    details: Mapped[dict] = mapped_column(JSON)
