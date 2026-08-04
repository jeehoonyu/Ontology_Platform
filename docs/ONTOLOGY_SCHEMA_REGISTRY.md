# Ontology Schema Registry

The schema registry publishes immutable, approved ontology revisions for downstream applications. A registry entry contains revision provenance, semantic compatibility, a strict JSON Schema contract, and a content checksum. TypeScript and Python clients and installable packages are generated from that same immutable manifest.

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

Ontology Studio exposes these resources under **Schema Registry**. Source downloads are intended for inspection. Installable packages are the normal application integration path.

```http
GET /ontology/registry/{entry_id}/packages
GET /ontology/registry/{entry_id}/packages/typescript/download
GET /ontology/registry/{entry_id}/packages/python/download
```

The first endpoint returns the npm/Python package names, filenames, sizes, SHA-256 checksums, and governed download URLs. Downloads require project `export` permission and emit `ontology.registry.package.downloaded` audit evidence.

Install a downloaded package without contacting a public registry:

```powershell
npm install ./ontologyos-default-production-1.0.0.tgz
python -m pip install ./ontologyos_default_production-1.0.0-py3-none-any.whl
```

The archives are reproducible: the same registry entry always produces identical bytes and checksums. npm archives have normalized tar and gzip metadata; wheels have normalized ZIP metadata and a complete `RECORD`. CI installs both packages into clean temporary consumer projects and imports their generated clients in `oms/test_ontology_sdk_installation.py`.

The source-generation CLI remains available for inspection and code-generation workflows:

```powershell
python oms/ontology_cli.py --base-url http://127.0.0.1:8000 list --project default
python oms/ontology_cli.py --base-url http://127.0.0.1:8000 schema --entry ontology_registry_... --output generated/ontology.schema.json
python oms/ontology_cli.py --base-url http://127.0.0.1:8000 sdk --entry ontology_registry_... --language typescript --output-dir generated/typescript
```

Set `ONTOLOGY_BASE_URL` and `ONTOLOGY_TOKEN` to avoid repeating connection options. Generated files are written atomically and server-provided file names are restricted to safe local names.
