"""Static release contract for the measured collaboration scale rehearsal."""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
source = (root / "oms" / "verify_collaboration_scale_postgres.py").read_text(encoding="utf-8")
workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

assert "EDITOR_COUNT = 20" in source
assert "READER_COUNT = 200" in source
assert 'COLLABORATION_ACK_P95_LIMIT_MS", "250"' in source
assert "ThreadPoolExecutor(max_workers=EDITOR_COUNT)" in source
assert "ThreadPoolExecutor(max_workers=READER_COUNT)" in source
assert "len(replicas)" in source and "start_replica" in source
assert "lost_updates" in source and "collaboration_receipt" in source
assert "verify_collaboration_scale_postgres.py" in workflow

print("Collaboration scale contract verified: two replicas, 20 editors, 200 readers, and p95 gate are wired.")
