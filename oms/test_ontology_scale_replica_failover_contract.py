"""Static contract for strict streaming-replica recovery evidence."""

from pathlib import Path


source = (Path(__file__).resolve().parent / "rehearse_ontology_scale_replica_failover.py").read_text(encoding="utf-8")
for required in (
    '"pg_basebackup"',
    '"-R", "-P"',
    "pg_last_wal_replay_lsn",
    "host replication {POSTGRES_USER} {network_cidr} scram-sha-256",
    "SELECT pg_reload_conf();",
    "ontology_replication_rehearsal",
    'docker("stop", "--time", "10", SOURCE_CONTAINER)',
    "pg_promote(true, 60)",
    '"replication_replay_seconds"',
    '"committed_probe_preserved": True',
    '"failover_promotion_seconds"',
    "RPO_LIMIT_SECONDS",
    "RTO_LIMIT_SECONDS",
    "atexit.register(cleanup_containers)",
):
    assert required in source, required

print("Ontology scale replica contract verified: WAL replay, committed probe, primary loss, promotion, RPO, and RTO are required.")
