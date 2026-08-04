"""Static release contract for strict physical backup and fresh-volume restore."""

from pathlib import Path


source = (Path(__file__).resolve().parent / "rehearse_ontology_scale_backup_restore.py").read_text(encoding="utf-8")
for required in (
    '"pg_basebackup"',
    '"-Fp", "-Xs", "-c", "fast"',
    "Target volume must use the ontology_scale_restore_ prefix",
    '"fresh_volume": True',
    '"restore_readiness_seconds"',
    '"rpo_semantics"',
    'assert target_state == source_state',
    '"indexed_plan"',
    "atexit.register(cleanup_target)",
    "RTO_LIMIT_SECONDS",
):
    assert required in source, required

print("Ontology scale physical backup contract verified: fresh volume, exact state, index, RPO semantics, and RTO are required.")
