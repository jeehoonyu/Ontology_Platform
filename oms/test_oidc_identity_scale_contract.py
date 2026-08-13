"""Static release contract for 200 distinct production OIDC identities."""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
provisioner = (root / "oms" / "provision_oidc_scale_users.py").read_text(encoding="utf-8")
browser = (root / "frontend" / "tests" / "production" / "oidc-scale.spec.ts").read_text(encoding="utf-8")
rehearsal = (root / "scripts" / "rehearse-production-acceptance.ps1").read_text(encoding="utf-8")

for required in (
    'OIDC_SCALE_USER_COUNT", "200"',
    "ThreadPoolExecutor",
    '"organization_id": ["pilot"]',
    '"project_ids": ["default"]',
    "role-mappings/realm",
):
    assert required in provisioner, required
for required in (
    "authorization_code_pkce",
    "unique_principals",
    "localhost:18001",
    "expect(forbidden.status()).toBe(403)",
    "login_p95_limit_ms: 15_000",
    "expect(userCount).toBeGreaterThanOrEqual(200)",
):
    assert required in browser, required
assert "provision_oidc_scale_users.py" in rehearsal
assert "test:production-oidc-scale" in rehearsal
print("OIDC identity scale contract verified: 200 PKCE identities, tenant claims, two replicas, RBAC denial, and p95 gate are required.")
