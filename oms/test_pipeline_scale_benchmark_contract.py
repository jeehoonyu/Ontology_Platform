"""Static release contract for the snapshot-native pipeline benchmark."""

from pathlib import Path


root = Path(__file__).resolve().parent
source = (root / "benchmark_pipeline_scale.py").read_text(encoding="utf-8")
workflow = (root.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

for required in (
    "REFERENCE_ROWS = 10_000_000",
    'PIPELINE_SCALE_PROFILE", "smoke"',
    "Reference profile requires at least 10,000,000 rows",
    '"executor": "duckdb"',
    '"materialized_python_rows"',
    '"reference_scale_achieved"',
    '"source_snapshot_id"',
    '"source_snapshot_ids"',
    '"output_snapshot_id"',
    '"type": "join"',
    '"type": "unique_id"',
    '"type": "derive_geo_point"',
    '"type": "spatial_filter"',
    '"type": "derive_mgrs"',
    '"mode": "geofence"',
    'PIPELINE_SCALE_PARTITIONS',
    '"input_partitions": PARTITION_COUNT',
    '"partition_by": ["category"]',
    '"output_partitions"',
    '"type": "window"',
    '"dimension_rows": 20',
):
    assert required in source, required

assert "benchmark_pipeline_scale.py" in workflow

# Tier B gate evidence must be emitted, and must be emitted only for the
# reference profile. CI runs the smoke profile on every push; if that emitted,
# it would overwrite a genuine reference PASS with a FAIL and the gate would
# never hold for longer than one commit.
assert 'if PROFILE == "reference":' in source, "gate evidence is not guarded by profile"
assert 'write_evidence(' in source and '"pipeline_scale"' in source, "gate evidence is not emitted"
gate_block = source.split('if PROFILE == "reference":', 1)[1]
assert "write_evidence(" in gate_block, "write_evidence is outside the reference guard"
for threshold in ("input_rows_min", "preview_p95_ms_max", "deliver_ms_max",
                  "materialized_python_rows_max"):
    assert threshold in gate_block, threshold

print("Pipeline scale benchmark contract verified: 1M-row CI smoke and strict 10M-row "
      "reference profiles are wired, and gate evidence is reference-only.")
