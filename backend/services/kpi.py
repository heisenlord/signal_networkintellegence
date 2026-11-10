"""Versioned, weighted KPI calculations. Missing evidence is never zero-filled."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import insert, select

from backend.database import Counter, KPI

FORMULA_VERSION = "availability-v1"


def calculate(counters: list[dict], *, now: str) -> dict:
    if not counters:
        return {"availability": None, "throughput_mbps": None, "completeness": 0, "quality": "unavailable", "final": False}
    frame = pd.DataFrame(counters)
    denominator = float(frame.observed_seconds.sum())
    completeness = min(1.0, float(frame.samples.sum() / frame.expected_samples.sum())) if frame.expected_samples.sum() else 0.0
    valid = denominator > 0 and (frame.successful_seconds >= 0).all() and (frame.successful_seconds <= frame.observed_seconds).all()
    value = round(float(np.clip(frame.successful_seconds.sum() / denominator * 100, 0, 100)), 2) if valid else None
    quality = "complete" if valid and completeness == 1 else "partial" if valid else "unavailable"
    window_end = datetime.fromisoformat(str(frame.window.max()).replace("Z", "+00:00")) + timedelta(minutes=15)
    final = datetime.fromisoformat(now.replace("Z", "+00:00")) >= window_end + timedelta(hours=2)
    return {"availability": value, "throughput_mbps": round(float(np.average(frame.throughput_mbps, weights=frame.samples)), 1) if frame.samples.sum() else None,
            "completeness": round(completeness, 3), "quality": quality, "final": final}


def publish(session, counter: Counter, now: str) -> KPI:
    """Append revisions instead of overwriting results; idempotent for an unchanged input."""
    values = {key: getattr(counter, key) for key in ("window", "successful_seconds", "observed_seconds", "samples", "expected_samples", "throughput_mbps")}
    result = calculate([values], now=now)
    prior = session.scalars(select(KPI).where(KPI.customer_id == counter.customer_id, KPI.entity_id == counter.entity_id, KPI.window == counter.window).order_by(KPI.revision.desc())).first()
    if prior and all(getattr(prior, key) == value for key, value in result.items()) and prior.formula_version == FORMULA_VERSION:
        return prior
    kpi = KPI(customer_id=counter.customer_id, entity_id=counter.entity_id, window=counter.window,
              revision=(prior.revision + 1 if prior else 1), formula_version=FORMULA_VERSION, computed_at=now, **result)
    session.add(kpi)
    session.flush()
    return kpi


def publish_new_sample_counters(session, records: list[dict], now: str):
    """Vectorized first publication for unique generated cell/window counters.

    Callers must exclude existing keys. Live corrections use append-only publish().
    """
    if not records:
        return
    frame = pd.DataFrame(records)
    observed = frame.observed_seconds.to_numpy()
    successful = frame.successful_seconds.to_numpy()
    valid = (observed > 0) & (successful >= 0) & (successful <= observed)
    availability = np.divide(successful * 100, observed, out=np.zeros(len(frame)), where=observed > 0)
    completeness = np.divide(frame.samples.to_numpy(), frame.expected_samples.to_numpy(), out=np.zeros(len(frame)), where=frame.expected_samples.to_numpy() > 0)
    final = [datetime.fromisoformat(row["window"].replace("Z", "+00:00")) + timedelta(minutes=135) <=
        datetime.fromisoformat(now.replace("Z", "+00:00")) for row in records]
    kpis = [{"customer_id": row["customer_id"], "entity_id": row["entity_id"], "window": row["window"], "revision": 1,
        "formula_version": FORMULA_VERSION, "availability": round(float(availability[i]), 2) if valid[i] else None,
        "throughput_mbps": row["throughput_mbps"] if row["samples"] > 0 else None,
        "completeness": round(float(min(1, completeness[i])), 3),
        "quality": "unavailable" if not valid[i] else "complete" if completeness[i] == 1 else "partial",
        "computed_at": now, "final": bool(final[i])} for i, row in enumerate(records)]
    session.execute(insert(Counter), records)
    session.execute(insert(KPI), kpis)
