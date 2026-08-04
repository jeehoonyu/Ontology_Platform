# OntologyOS Python Plugin SDK

This dependency-free package is installed in the governed plugin sandbox image. A plugin exports `handle(request)` and uses the SDK to dispatch named operations and return stable, typed result envelopes.

```python
from ontologyos_plugin_sdk import TransformResult, dispatch

def normalize(payload):
    records = [{**row, "name": str(row.get("name", "")).strip()} for row in payload.get("records", [])]
    return TransformResult(records=records, metrics={"rows": len(records)}).to_output()

def handle(request):
    return dispatch({"normalize": normalize}, request)
```

Plugin manifests declare `sdk_api_version: 1`. Registration rejects unsupported versions before activation. Plugins receive only the declared operation and validated input object; secrets must be referenced through governed capabilities rather than embedded in bundles.

Network access is default-deny. A networked plugin declares the `network` capability and signs exact destinations into `network_policy`. Enterprise HTTPS endpoints may include a public CA chain in `tls_ca_bundle_pem`; private keys and arbitrary PEM content are rejected, and execution evidence records only the bundle digest and certificate count.

```json
{
  "capabilities": ["network"],
  "network_policy": {
    "allowed_hosts": ["api.operations.example"],
    "allowed_ports": [443],
    "allow_http": false,
    "tls_ca_bundle_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
  }
}
```
