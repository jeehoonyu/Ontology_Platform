"""Static contract for the strict ontology process-restart rehearsal."""

from pathlib import Path


source = (Path(__file__).resolve().parent / "rehearse_ontology_scale_recovery.py").read_text(encoding="utf-8")
for required in (
    "VACUUM (ANALYZE) object_instances",
    "VACUUM (ANALYZE) object_change_events",
    "SET maintenance_work_mem = '64MB'",
    "SET max_parallel_maintenance_workers = 0",
    '["docker", "restart", "--time", "30", CONTAINER]',
    "database_restart_recovery_seconds",
    "fixture_state_preserved",
    "indexed_plan_after_restart",
    "RTO_LIMIT_SECONDS",
):
    assert required in source, required

print("Ontology scale recovery contract verified: vacuum, restart, state, index, and RTO evidence are required.")
