"""Static release contract for the snapshot-native pipeline benchmark."""

from pathlib import Path


root = Path(__file__).resolve().parent
source = (root / "benchmark_pipeline_scale.py").read_text(encoding="utf-8")
data_plane_source = (root / "app" / "data_plane.py").read_text(encoding="utf-8")
workflow = (root.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

for required in (
    "REFERENCE_ROWS = 10_000_000",
    'PIPELINE_SCALE_PROFILE", "smoke"',
    "Reference profile requires at least 10,000,000 rows",
    '"executor": "duckdb"',
    '"materialized_python_rows"',
    '"reference_scale_achieved"',
    'build_evidence_provenance(',
    '"provenance":',
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
    'PIPELINE_SCALE_PIVOT_CARDINALITY',
    'PIPELINE_SCALE_GATE_EVIDENCE_DIR',
    '"id": "large_join", "type": "join"',
    '"id": "large_union", "type": "union"',
    '"id": "wide_pivot", "type": "pivot"',
    '"complex_join_left_rows": ROW_COUNT',
    '"complex_join_right_rows": ROW_COUNT',
    '"complex_union_rows": ROW_COUNT * 2',
    '"complex_pivot_cardinality": PIVOT_CARDINALITY',
    '"complex_idempotent_replay": complex_replay["idempotent_replay"]',
    'PIPELINE_SCALE_GEOFENCE_VERTICES',
    '"geofence_outer_vertices": GEOFENCE_OUTER_VERTICES',
    '"geofence_hole_vertices": GEOFENCE_HOLE_VERTICES',
    '"geofence_parameterized_edges": True',
):
    assert required in source, required

assert "benchmark_pipeline_scale.py" in workflow

for required in (
    "def _duckdb_polygon_filter_sql(",
    'json.dumps(edges, separators=(",", ":"))',
    "FROM json_each(",
    "SELECT DISTINCT CAST(",
    "polygon_inside",
):
    assert required in data_plane_source, required

# Tier B gate evidence must be emitted, and must be emitted only for the
# reference profile. CI runs the smoke profile on every push; if that emitted,
# it would overwrite a genuine reference PASS with a FAIL and the gate would
# never hold for longer than one commit.
assert 'if PROFILE == "reference":' in source, "gate evidence is not guarded by profile"
assert 'write_evidence(' in source and '"pipeline_scale"' in source, "gate evidence is not emitted"
gate_block = source.split('if PROFILE == "reference":', 1)[1]
assert "write_evidence(" in gate_block, "write_evidence is outside the reference guard"
for threshold in ("input_rows_min", "preview_p95_ms_max", "deliver_ms_max",
                  "materialized_python_rows_max", "complex_join_left_rows_min",
                  "complex_join_right_rows_min", "complex_union_rows_min",
                  "complex_pivot_cardinality_min", "complex_preview_ms_max",
                  "complex_deliver_ms_max", "complex_materialized_python_rows_max",
                  "complex_idempotent_replay_min"):
    assert threshold in gate_block, threshold

for threshold in ("geofence_outer_vertices_min", "geofence_total_positions_min",
                  "geofence_parameterized_edges_min"):
    assert threshold in gate_block, threshold

print("Pipeline scale benchmark contract verified: CI smoke and strict 10M-row reference "
      "profiles cover the baseline plus high-vertex geofence, large join/union/wide-pivot/replay path, and gate "
      "evidence is reference-only.")
