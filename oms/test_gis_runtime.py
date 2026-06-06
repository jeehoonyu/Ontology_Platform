import os
import tempfile

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'gis_runtime.db')}"

from app import models, models_action, schemas  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    bootstrap_maintenance_domain,
    evaluate_gis_geofence,
    export_gis_feature_collection,
    query_gis_spatial_objects,
    validate_ontology,
)


models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        bootstrap = bootstrap_maintenance_domain(
            schemas.DomainBootstrapRequest(actor="gis_test", run_pipelines=True),
            db,
        )
        assert all(run["status"] == "SUCCESS" for run in bootstrap["pipeline_runs"])
        assert bootstrap["pipeline_runs"][0]["metrics"]["geometries_created"] == 1
        assert bootstrap["pipeline_runs"][1]["metrics"]["geometries_created"] == 2

        validation = validate_ontology(db)
        assert validation["status"] == "PASS"

        pump = db.query(models.ObjectInstance).filter_by(id="asset_pump_4").first()
        assert pump.properties["geometry"]["type"] == "Point"
        assert pump.properties["geometry"]["coordinates"] == [-122.4012, 37.7924]

        radius = query_gis_spatial_objects(
            schemas.GISSpatialQuery(
                object_type_id="asset",
                near={"longitude": -122.4012, "latitude": 37.7924},
                radius_meters=150,
                include_lineage=False,
            ),
            db,
        )
        assert radius["count"] == 1
        assert radius["objects"][0]["id"] == "asset_pump_4"
        assert radius["objects"][0]["spatial"]["distance_meters"] == 0

        bbox = query_gis_spatial_objects(
            schemas.GISSpatialQuery(
                object_type_id="asset",
                bbox=[-122.4025, 37.7915, -122.4005, 37.7930],
                include_lineage=False,
            ),
            db,
        )
        assert {item["id"] for item in bbox["objects"]} == {"asset_pump_4"}

        features = export_gis_feature_collection(
            schemas.GISFeatureCollectionRequest(object_type_id="asset"),
            db,
        )
        assert features["type"] == "FeatureCollection"
        assert features["metadata"]["feature_count"] == 2
        assert all(feature["type"] == "Feature" for feature in features["features"])

        geofence = evaluate_gis_geofence(
            schemas.GISGeofenceRequest(
                object_type_id="asset",
                geofence={
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.4030, 37.7910],
                        [-122.3990, 37.7910],
                        [-122.3990, 37.7940],
                        [-122.4030, 37.7940],
                        [-122.4030, 37.7910],
                    ]],
                },
            ),
            db,
        )
        assert geofence["summary"] == {"total": 2, "inside": 1, "outside": 1}
        assert geofence["inside"][0]["id"] == "asset_pump_4"
        assert geofence["outside"][0]["id"] == "asset_chiller_2"

        print("GIS runtime scenario passed")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    main()
