# Signed Plugin Runtime

OntologyOS extensions are immutable, project-scoped versions whose canonical manifest is signed with an organization trust key. The API never imports third-party extension modules into its own Python process.

## Manifest Contract

A version 1 manifest contains:

- `plugin_id`, semantic `version`, and one of `connector`, `transform`, `widget`, `ontology_package`, or `model_provider`;
- `sdk_api_version: 1`, which is checked at registration and again inside the sandbox;
- `runtime: python3` and a relative Python `entrypoint`;
- the exact ZIP `bundle_sha256`;
- named `operations`, declared capabilities, configuration schemas, and execution limits;
- optional network policy metadata.

The vendor signs the canonical JSON manifest with Ed25519. Registration verifies the organization-scoped public key, signature, bundle digest, ZIP paths, expansion limits, entrypoint, capabilities, and operation names before persisting a `VERIFIED` version. Activation is a separate administrator operation and supersedes the prior active version without mutating it.

## API Lifecycle

1. `POST /api/v1/plugins/trust-keys`
2. `POST /api/v1/plugins/register`
3. `POST /api/v1/plugins/{version_id}/activate`
4. `GET /api/v1/plugins/catalog?project_id=...`
5. `POST /api/v1/plugins/{version_id}/invoke-async`
6. `GET /api/v1/plugins/executions/{execution_id}`
7. `GET /api/v1/plugins/{version_id}/executions`
8. `POST /api/v1/plugins/trust-keys/{key_id}/revoke`

Invocation is request-hashed and optionally idempotent. In production, both `invoke` and `invoke-async` atomically create a `PluginExecution` and a generic `plugin.execute` platform job. The durable execution record contains its job ID, input shape, output, status, duration, sandbox policy, bundle/manifest evidence, signer identity, and audit/outbox evidence. Cancellation, retry, stale-lease recovery, and retry exhaustion remain synchronized across both records. Revoking a trust key immediately removes affected versions from active catalogs and prevents queued work from receiving the bundle.

## Isolation Modes

`process` is a development/test mode only. It launches an isolated Python child with a minimal environment, no child processes, filesystem reads constrained to the bundle/Python runtime, writes constrained to scratch space, bounded input/output, and a deadline. Python audit hooks reduce accidental access but are not treated as a production security boundary. Production explicitly rejects this mode.

`oci` is the production mode. Each execution uses a digest-pinned image, read-only root filesystem, non-root UID, dropped Linux capabilities, `no-new-privileges`, bounded PIDs/CPU/memory, bounded tmpfs scratch, and no network by default. The verified ZIP is streamed over stdin, re-hashed in the container, and extracted into ephemeral tmpfs, avoiding host filesystem mounts.

A plugin declaring `network` must sign an exact `network_policy` containing DNS names, TCP ports, and whether plain HTTP is allowed. Wildcards, missing destinations, invalid ports, unknown policy fields, and HTTP on an undeclared non-TLS policy are rejected at registration. For every execution the isolated executor creates a short-lived HMAC credential bound to that signed policy. The sandbox receives only credentialed `HTTP_PROXY` and `HTTPS_PROXY` values and remains attached solely to an internal Docker network. A separately digest-pinned, non-root, read-only proxy is dual-homed to the uplink, verifies the credential and destination, re-resolves DNS, and denies loopback, link-local, private, reserved, multicast, and unspecified addresses by default. `bridge`, `host`, default, and `none` remain invalid sandbox network settings. Direct socket bypass has no route to the uplink.

For an enterprise endpoint signed by a private CA, `network_policy.tls_ca_bundle_pem` may contain up to 32 public CA certificates and 128 KiB of ASCII PEM. Registration parses the complete bundle, rejects private keys and non-certificate content, and binds it to the signed manifest. The worker writes it into ephemeral sandbox scratch and sets standard Python/OpenSSL trust variables for that execution only. The proxy continues to authorize and tunnel CONNECT without terminating TLS. Runtime evidence contains only `ca_bundle_sha256` and `certificate_count`, never PEM content.

`PLUGIN_EGRESS_ALLOW_PRIVATE=true` exists only for controlled private connector networks and the deterministic mock rehearsal. It is hard-coded to `false` in the production Compose profile. Rotate `PLUGIN_EGRESS_TOKEN_SECRET` like a worker credential; it is never written to execution evidence or proxy logs.

The API does not receive an OCI socket in the production profile. A dedicated pull executor registers only the `plugin.execute` capability, claims a fenced lease, fetches the exact verified bundle, heartbeats while the sandbox runs, and commits through signed-plugin-specific completion/failure endpoints. Generic job completion is rejected for plugin jobs so output-contract verification cannot be bypassed. The executor has no database credentials.

`PLUGIN_SANDBOX_IMAGE` must contain `/app/app/plugin_sandbox_runner.py` (or the configured runner path) and must use an immutable repository digest or exact `sha256:` image ID in production. Without those settings, execution fails closed. The repository provides `oms/plugin-sandbox.Dockerfile` and a pinned, non-root `oms/plugin-executor.Dockerfile`. The optional `plugin-execution` Compose profile uses a separate OCI daemon network and persistent image cache; it never mounts the host Docker socket into the API.

Start the isolated execution tier after issuing an execute-only service token:

```powershell
docker compose --env-file deploy/.env.production -f docker-compose.yml -f docker-compose.production.yml --profile plugin-execution up -d
```

Plugins execute with at-least-once worker semantics. Plugin operations that call external systems must use the stable execution/job identity as their downstream idempotency key. Manifests and task inputs must contain secret references, not secret values.

## Plugin SDK

`plugin-sdk/python` defines the versioned runtime contract and typed result helpers for connectors, transforms, widgets, ontology packages, and model providers. The SDK is installed in the sandbox image and is intentionally dependency-free. `plugin-sdk/examples/normalize_transform/plugin.py` is an executable transform example. Plugins should use these result envelopes instead of depending on internal API models.

## Backup and Recovery

Portable project exports include referenced public trust keys, signed manifests, exact bundle bytes, and execution evidence. Import validates the project checksum and independently re-verifies every plugin signature, manifest digest, bundle digest, and archive path before restoring files.

Production database backup remains authoritative. Use both `-IncludeSnapshots` and `-IncludePlugins`; restore with `-RestoreSnapshots` and `-RestorePlugins`. Dataset and plugin archives have independent SHA-256 sidecars and manifest entries. Trust-key private material is never stored by OntologyOS.

## Verification

```powershell
cd oms
python test_signed_plugin_runtime.py
python test_signed_plugin_runtime_migration.py
python test_async_plugin_execution_migration.py
python test_async_plugin_execution.py
python test_plugin_executor.py
python test_plugin_executor_deployment.py
python test_plugin_executor_production_rehearsal.py
python test_plugin_egress_policy.py
python test_plugin_egress_rehearsal.py
python test_plugin_sdk_contract.py
python test_recovery_scripts.py
../scripts/rehearse-plugin-oci.ps1
../scripts/rehearse-plugin-egress.ps1
```

The automated evidence covers cryptographic acceptance/rejection, immutable versions, SDK compatibility, catalog activation, durable idempotent queueing, fenced work delivery, output-contract enforcement, retry/cancel/stale recovery, filesystem/network/process denial, timeout, production fail-closed behavior, real digest-pinned OCI execution, key revocation, signed portable restore, migration idempotency, and checksummed archive orchestration. CI builds both dedicated images, validates the production and OIDC rehearsal Compose profiles, and runs the real-container sandbox rehearsal.

The release rehearsal adds the real identity and failure boundary. An OIDC administrator registers an ephemeral Ed25519-signed plugin and creates a service account with only `project:default:execute`. It publishes digest-pinned sandbox and egress-proxy images to the isolated registry, provisions the internal proxy boundary in the nested OCI daemon, and requires the executor inventory to report `egress_proxy=ready`. The executor then runs a fast operation, begins a slow operation, is force-stopped, loses its lease, and restarts. Acceptance requires `job.requeued` with `lease_expired`, a later successful attempt, exactly one terminal success, signed execution audit evidence, and a passing project-readiness worker check. One-time service and egress credentials are held only in process environment or a temporary state file and are excluded from `docs/plugin-executor-production-evidence.json`.

`docs/plugin-egress-rehearsal-evidence.json` records the separate real-container egress gate. It proves allowed HTTP proxying, custom-CA HTTPS through CONNECT, rejection of the same private CA when it is absent from the signed manifest, undeclared-destination denial, direct-socket bypass denial, internal-only sandbox networking, and credential/PEM-redacted evidence. The fixture enables private destinations only to reach its isolated mock servers; production keeps private-address denial enabled.
