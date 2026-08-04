from ontologyos_plugin_sdk import TransformResult, dispatch


def normalize(payload):
    rows = [
        {**row, "asset_name": str(row.get("asset_name", "")).strip(), "criticality": str(row.get("criticality", "unknown")).lower()}
        for row in payload.get("records", [])
    ]
    return TransformResult(
        records=rows,
        schema=[{"name": "asset_name", "type": "string"}, {"name": "criticality", "type": "string"}],
        metrics={"rows": len(rows)},
    ).to_output()


def handle(request):
    return dispatch({"normalize": normalize}, request)
