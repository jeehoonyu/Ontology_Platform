"""Protect the real OIDC and executor-loss production acceptance contract."""
from pathlib import Path

import yaml


root = Path(__file__).resolve().parents[1]
compose = yaml.safe_load((root / "docker-compose.rehearsal.yml").read_text(encoding="utf-8"))
services = compose["services"]

for name in ("plugin-registry", "plugin-oci-daemon", "plugin-executor"):
    assert "plugin-execution" in services[name]["profiles"]

api = services["oms-api"]
peer = services["oms-api-peer"]
for service in (api, peer):
    assert service["environment"]["PLUGIN_EXECUTION_MODE"] == "worker"
    assert "rehearsal_plugin_bundles:/var/lib/ontology/plugins" in service["volumes"]

daemon = services["plugin-oci-daemon"]
executor = services["plugin-executor"]
assert "@sha256:" in daemon["image"]
assert daemon["privileged"] is True
assert "--insecure-registry=plugin-registry:5000" in daemon["command"]
assert executor["read_only"] is True
assert executor["cap_drop"] == ["ALL"]
assert "no-new-privileges:true" in executor["security_opt"]
assert executor["environment"]["DOCKER_HOST"] == "tcp://plugin-oci-daemon:2375"
assert executor["environment"]["PLUGIN_SANDBOX_NETWORK"] == "ontology-plugin-egress"
assert executor["environment"]["PLUGIN_EGRESS_PROXY_URL"] == "http://plugin-egress-proxy:8080"
assert executor["environment"]["PLUGIN_EGRESS_ALLOW_PRIVATE"] == "false"
assert "/var/run/docker.sock" not in (root / "docker-compose.rehearsal.yml").read_text(encoding="utf-8")

script = (root / "scripts/rehearse-production-acceptance.ps1").read_text(encoding="utf-8")
for stage in ('"bootstrap"', '"queue_recovery"', '"verify_recovery"'):
    assert stage in script
assert "project:default:execute" not in script  # minted only inside the authenticated browser stage
assert "docker push" in script
assert "RepoDigests" in script
assert "plugin-egress-proxy.Dockerfile" in script
assert "REHEARSAL_PLUGIN_EGRESS_PROXY_IMAGE" in script
assert "REHEARSAL_PLUGIN_EGRESS_TOKEN_SECRET" in script
assert "stop -t 1 plugin-executor" in script
assert "stop plugin-executor plugin-oci-daemon plugin-registry" in script
assert "PLUGIN_REHEARSAL_EVIDENCE_PATH" in script

stop_script = (root / "scripts/stop-production-rehearsal.ps1").read_text(encoding="utf-8")
assert '"--profile", "plugin-execution"' in stop_script
assert '"--profile", "pipeline-workers"' in stop_script
assert '"down", "--remove-orphans"' in stop_script

spec = (root / "frontend/tests/production/plugin-executor.spec.ts").read_text(encoding="utf-8")
for evidence in (
    'scopes: ["project:default:execute"]',
    'event.event_type === "job.requeued"',
    'event.payload?.reason === "lease_expired"',
    'event.event_type === "job.succeeded"',
    'pluginCheck?.status',
    'executorWorker?.labels?.egress_proxy',
    'governed_egress_proxy_provisioned: true',
    'plugin.execution.succeeded',
):
    assert evidence in spec
assert '"token": state.token' not in spec.split("assertions:", 1)[-1]

helper = (root / "oms/build_rehearsal_plugin.py").read_text(encoding="utf-8")
assert "Ed25519PrivateKey.generate()" in helper
assert '"sdk_api_version": 1' in helper
assert '"capabilities": ["scratch_write"]' in helper

print("Production plugin executor rehearsal contract verified: OIDC bootstrap, execute-only token, isolated OCI, lease recovery, and evidence.")
