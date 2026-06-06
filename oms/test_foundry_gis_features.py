import os
import tempfile

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'foundry_gis_features.db')}"

from app import models, models_action, schemas  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    bootstrap_maintenance_domain,
    create_link_instance,
    create_map_layer,
    create_saved_object_set,
    decode_gis_mgrs,
    encode_gis_mgrs,
    evaluate_saved_object_set_endpoint,
    get_object_profile,
    render_gis_map_layer,
    validate_ontology,
)


models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        bootstrap = bootstrap_maintenance_domain(
            schemas.DomainBootstrapRequest(actor="foundry_gis_test", run_pipelines=True),
            db,
        )
        assert all(run["status"] == "SUCCESS" for run in bootstrap["pipeline_runs"])

        encoded = encode_gis_mgrs(
            schemas.MGRSEncodeRequest(latitude=37.7924, longitude=-122.4012, precision=5)
        )
        assert encoded["mgrs"].startswith("10S")
        decoded = decode_gis_mgrs(schemas.MGRSDecodeRequest(mgrs=encoded["mgrs"]))
        assert abs(decoded["latitude"] - 37.7924) < 0.0001
        assert abs(decoded["longitude"] + 122.4012) < 0.0001

        pump = db.query(models.ObjectInstance).filter_by(id="asset_pump_4").first()
        assert pump.properties["mgrs"] == encoded["mgrs"]

        saved = create_saved_object_set(
            schemas.SavedObjectSetCreate(
                id="critical_assets",
                display_name="Critical Assets",
                description="Reusable object set for high-criticality assets.",
                object_type_id="asset",
                filters={"criticality": "high"},
                owner="analyst",
            ),
            db,
        )
        assert saved.id == "critical_assets"

        evaluated = evaluate_saved_object_set_endpoint("critical_assets", db=db)
        assert evaluated["count"] == 1
        assert evaluated["objects"][0]["id"] == "asset_pump_4"

        layer = create_map_layer(
            schemas.MapLayerDefinitionCreate(
                id="critical_asset_layer",
                display_name="Critical Asset Layer",
                description="Map layer backed by a saved object set.",
                object_type_id="asset",
                saved_object_set_id="critical_assets",
                geometry_field="geometry",
                style={"marker_color": "#d43f3a", "marker_size": 10},
                owner="analyst",
            ),
            db,
        )
        assert layer.id == "critical_asset_layer"

        rendered = render_gis_map_layer("critical_asset_layer", db=db)
        assert rendered["type"] == "FeatureCollection"
        assert rendered["metadata"]["feature_count"] == 1
        assert rendered["layer"]["style"]["marker_color"] == "#d43f3a"
        assert rendered["features"][0]["properties"]["object_id"] == "asset_pump_4"

        create_link_instance(
            schemas.LinkInstanceCreate(
                link_type_id="facility_has_asset",
                source_object_id="facility_1",
                target_object_id="asset_pump_4",
            ),
            db,
        )
        create_link_instance(
            schemas.LinkInstanceCreate(
                link_type_id="asset_has_work_order",
                source_object_id="asset_pump_4",
                target_object_id="wo_pump_urgent",
            ),
            db,
        )
        profile = get_object_profile("asset", "asset_pump_4", db=db)
        assert profile["object"]["spatial"]["mgrs"] == encoded["mgrs"]
        assert profile["metrics"]["inbound_link_count"] == 1
        assert profile["metrics"]["outbound_link_count"] == 1
        assert {item["id"] for item in profile["linked_objects"]} == {"facility_1", "wo_pump_urgent"}

        validation = validate_ontology(db)
        assert validation["status"] == "PASS"
        assert validation["summary"]["checked"]["saved_object_sets"] == 1
        assert validation["summary"]["checked"]["map_layers"] == 1

        print("Foundry GIS feature scenario passed")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    main()
