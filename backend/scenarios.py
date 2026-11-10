"""Scenario labels and deterministic faults; all records are simulated."""
SCENARIOS = {
    "INC-1005": {"name": "West cluster transport incident", "type": "Transport failure"},
    "INC-1020": {"name": "Bandra telemetry gap", "type": "Missing telemetry"},
    "INC-1035": {"name": "Powai availability anomaly", "type": "Conflicting evidence"},
    "INC-2005": {"name": "North aggregation link failure", "type": "North transport failure"},
    "INC-2020": {"name": "Vendor collector delay", "type": "Collector delay"},
    "INC-2035": {"name": "Partial measurements in east sector", "type": "Partial measurements"},
    "INC-2050": {"name": "Availability alarm with healthy counters", "type": "Healthy counter evidence"},
    "INC-2060": {"name": "Radio capacity regression", "type": "Uncorroborated degradation"},
}
DEGRADED_CELLS = {"CELL-101", "CELL-102", "CELL-201", "CELL-202", "CELL-301", "CELL-401", "CELL-402", "CELL-801", "CELL-802", "CELL-601", "CELL-602", "CELL-901", "CELL-902"}
MISSING_CELLS = {"CELL-103", "CELL-501", "CELL-502"}
PARTIAL_CELLS = {"CELL-301", "CELL-601", "CELL-602"}
EXTRA_ALARMS = [
    ("ALM-101", "CELL-401", "INC-2005", "Cell availability degraded", "critical"),
    ("ALM-102", "CELL-402", "INC-2005", "Cell availability degraded", "critical"),
    ("ALM-103", "CELL-801", "INC-2005", "Cell availability degraded", "critical"),
    ("ALM-104", "CELL-802", "INC-2005", "Cell availability degraded", "critical"),
    ("ALM-105", "TRANS-03", "INC-2005", "Transport link down", "critical"),
    ("ALM-106", "CELL-501", "INC-2020", "Counter reporting delayed", "warning"),
    ("ALM-107", "CELL-502", "INC-2020", "Counter reporting delayed", "warning"),
    ("ALM-108", "CELL-601", "INC-2035", "Incomplete performance samples", "major"),
    ("ALM-109", "CELL-602", "INC-2035", "Incomplete performance samples", "major"),
    ("ALM-110", "CELL-701", "INC-2050", "Availability alarm awaiting corroboration", "warning"),
    ("ALM-111", "CELL-901", "INC-2060", "Radio performance regression", "major"),
    ("ALM-112", "CELL-902", "INC-2060", "Radio performance regression", "major"),
]
