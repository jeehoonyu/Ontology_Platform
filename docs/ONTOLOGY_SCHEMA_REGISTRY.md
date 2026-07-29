# Ontology Schema Registry

The schema registry publishes immutable, approved ontology revisions for downstream applications. A registry entry contains revision provenance, semantic compatibility, a strict JSON Schema contract, and a content checksum. TypeScript and Python client bundles are generated from that same immutable manifest.

## Publish

Only revisions with `PUBLISHED` or `SUPERSEDED` status can be registered. A breaking change is rejected unless the publisher passes `allow_breaking: true` after reviewing the semantic diff.

```http
POST /ontology/registry/publish
Content-Type: application/json

{
  "project_id": "default",
  "revision_id": "ontology_revision_...",
  "version": "1.0.0",
  "channel": "production",
  "allow_breaking": false
}
```

## Consume

```powershell
python oms/ontology_cli.py --base-url http://127.0.0.1:8000 list --project default
python oms/ontology_cli.py --base-url http://127.0.0.1:8000 schema --entry ontology_registry_... --output generated/ontology.schema.json
python oms/ontology_cli.py --base-url http://127.0.0.1:8000 sdk --entry ontology_registry_... --language typescript --output-dir generated/typescript
```

Set `ONTOLOGY_BASE_URL` and `ONTOLOGY_TOKEN` to avoid repeating connection options. Generated files are written atomically and server-provided file names are restricted to safe local names.
