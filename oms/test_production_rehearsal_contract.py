"""Static contract for the real OIDC, load, restart, and recovery release gate."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
realm = json.loads((root / "deploy" / "keycloak-realm.json").read_text(encoding="utf-8"))
profile = json.loads((root / "deploy" / "keycloak-user-profile.json").read_text(encoding="utf-8"))
compose = (root / "docker-compose.rehearsal.yml").read_text(encoding="utf-8")
start = (root / "scripts" / "start-production-rehearsal.ps1").read_text(encoding="utf-8")
acceptance = (root / "scripts" / "rehearse-production-acceptance.ps1").read_text(encoding="utf-8")
browser = (root / "frontend" / "tests" / "production" / "oidc-rbac.spec.ts").read_text(encoding="utf-8")
workflow = (root / ".github" / "workflows" / "production-acceptance.yml").read_text(encoding="utf-8")

client = next(row for row in realm["clients"] if row["clientId"] == "ontology-platform")
mapper_claims = {row["config"].get("claim.name") for row in client["protocolMappers"]}
assert {"realm_access.roles", "organization_id", "project_ids"} <= mapper_claims
assert client["publicClient"] is True and client["standardFlowEnabled"] is True
assert client["directAccessGrantsEnabled"] is False

attributes = {row["name"]: row for row in profile["attributes"]}
assert attributes["organization_id"]["permissions"]["edit"] == ["admin"]
assert attributes["organization_id"]["multivalued"] is False
assert attributes["project_ids"]["permissions"]["edit"] == ["admin"]
assert attributes["project_ids"]["multivalued"] is True

assert "keycloak-user-profile.json:/opt/keycloak/conf/ontology-user-profile.json:ro" in compose
assert "@sha256:" in compose and "AUTH_MODE: oidc" in compose
assert "update users/profile" in start
assert "attributes.organization_id=pilot" in start and "attributes.project_ids=default" in start
assert "Tenant attributes were not persisted" in start

for required in (
    "test:production-oidc",
    "restart oms-api",
    "rehearse-recovery.ps1",
    "PRODUCTION_ACCEPTANCE_PASSED",
):
    assert required in acceptance, required
assert "Array.from({ length: 50 }" in browser
assert 'fetch("/tenancy/organizations"' in browser
assert "APPROVAL_REQUIRED" in browser and 'toBe("SUCCESS")' in browser
assert "rehearse-production-acceptance.ps1" in workflow
assert "playwright install --with-deps chrome" in workflow

print("Production rehearsal contract verified: OIDC claims, tenant RBAC, load, restart, and restore gates are wired.")
