"""Verify production plugin execution is isolated from the API container."""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
compose = (root / "docker-compose.production.yml").read_text(encoding="utf-8")
dockerfile = (root / "oms" / "plugin-executor.Dockerfile").read_text(encoding="utf-8")
environment = (root / "deploy" / ".env.production.example").read_text(encoding="utf-8")
workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

api_section, executor_section = compose.split("  plugin-executor:", 1)
assert "PLUGIN_EXECUTION_MODE: ${PLUGIN_EXECUTION_MODE:-worker}" in api_section
assert "/var/run/docker.sock" not in api_section
assert "DOCKER_HOST" not in api_section
assert 'profiles: ["plugin-execution"]' in executor_section
assert "DOCKER_HOST: tcp://plugin-oci-daemon:2375" in executor_section
assert "PLUGIN_EXECUTOR_TOKEN" in executor_section
assert "PLUGIN_EGRESS_PROXY_IMAGE" in executor_section
assert "PLUGIN_EGRESS_TOKEN_SECRET" in executor_section
assert "PLUGIN_SANDBOX_NETWORK: ${PLUGIN_SANDBOX_NETWORK:-ontology-plugin-egress}" in executor_section
assert 'cap_drop: ["ALL"]' in executor_section
assert 'security_opt: ["no-new-privileges:true"]' in executor_section
assert "USER 10001:10001" in dockerfile
assert "docker:27-cli@sha256:" in dockerfile
assert "plugin_egress.py" in dockerfile
assert "PLUGIN_EXECUTION_MODE=worker" in environment
assert "execute-only-service-token" in environment
assert "Build isolated plugin executor image" in workflow
assert "Build governed plugin egress proxy image" in workflow
assert "Rehearse governed plugin egress" in workflow

print("Plugin executor deployment verified: worker mode, isolated OCI daemon, no API socket, non-root image, and CI build contract.")
