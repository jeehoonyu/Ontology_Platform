"""Provision distinct Keycloak users for the production OIDC scale rehearsal."""

from __future__ import annotations

import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


KEYCLOAK_URL = os.environ.get("OIDC_SCALE_KEYCLOAK_URL", "http://127.0.0.1:18080").rstrip("/")
REALM = os.environ.get("OIDC_SCALE_REALM", "ontology")
ADMIN_USER = os.environ.get("OIDC_SCALE_ADMIN_USER", "rehearsal-admin")
ADMIN_PASSWORD = os.environ.get("OIDC_SCALE_ADMIN_PASSWORD", "")
USER_PASSWORD = os.environ.get("OIDC_SCALE_USER_PASSWORD", "")
USER_COUNT = int(os.environ.get("OIDC_SCALE_USER_COUNT", "200"))
CONCURRENCY = int(os.environ.get("OIDC_SCALE_PROVISION_CONCURRENCY", "20"))
USERNAME_PREFIX = os.environ.get("OIDC_SCALE_USERNAME_PREFIX", "oidc-scale-viewer-")
GROUP_NAME = os.environ.get("OIDC_SCALE_GROUP", "ontology-scale-viewers")

if not ADMIN_PASSWORD or not USER_PASSWORD:
    raise SystemExit("OIDC scale admin and user passwords are required")
if USER_COUNT < 1 or CONCURRENCY < 1 or USER_COUNT > 1000:
    raise SystemExit("OIDC scale user count must be 1..1000 and concurrency must be positive")

with httpx.Client(timeout=30) as client:
    token_response = client.post(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
        },
    )
    token_response.raise_for_status()
    token = token_response.json()["access_token"]

headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
admin_root = f"{KEYCLOAK_URL}/admin/realms/{REALM}"
with httpx.Client(timeout=30, headers=headers) as client:
    groups = client.get(f"{admin_root}/groups", params={"search": GROUP_NAME, "exact": "true"})
    groups.raise_for_status()
    matches = [group for group in groups.json() if group.get("name") == GROUP_NAME]
    if not matches:
        created = client.post(f"{admin_root}/groups", json={"name": GROUP_NAME})
        created.raise_for_status()
        group_id = created.headers["location"].rstrip("/").split("/")[-1]
    else:
        group_id = matches[0]["id"]
    role = client.get(f"{admin_root}/roles/viewer")
    role.raise_for_status()
    mapped = client.post(f"{admin_root}/groups/{group_id}/role-mappings/realm", json=[role.json()])
    if mapped.status_code not in {204, 409}:
        mapped.raise_for_status()


def provision(index: int) -> tuple[str, float]:
    username = f"{USERNAME_PREFIX}{index:04d}"
    started = time.perf_counter()
    with httpx.Client(timeout=30, headers=headers) as client:
        payload = {
            "username": username,
            "enabled": True,
            "emailVerified": True,
            "firstName": "Scale",
            "lastName": f"Viewer {index:04d}",
            "email": f"{username}@rehearsal.local",
            "requiredActions": [],
            "attributes": {"organization_id": ["pilot"], "project_ids": ["default"]},
            "credentials": [{"type": "password", "value": USER_PASSWORD, "temporary": False}],
        }
        created = client.post(f"{admin_root}/users", json=payload)
        if created.status_code == 201:
            user_id = created.headers["location"].rstrip("/").split("/")[-1]
        elif created.status_code == 409:
            existing = client.get(
                f"{admin_root}/users", params={"username": username, "exact": "true"},
            )
            existing.raise_for_status()
            users = [user for user in existing.json() if user.get("username") == username]
            if len(users) != 1:
                raise AssertionError({"username": username, "matches": len(users)})
            user_id = users[0]["id"]
            updated = client.put(f"{admin_root}/users/{user_id}", json=payload)
            updated.raise_for_status()
            reset = client.put(
                f"{admin_root}/users/{user_id}/reset-password",
                json={"type": "password", "value": USER_PASSWORD, "temporary": False},
            )
            reset.raise_for_status()
        else:
            created.raise_for_status()
        membership = client.put(f"{admin_root}/users/{user_id}/groups/{group_id}")
        membership.raise_for_status()
    return user_id, (time.perf_counter() - started) * 1000.0


started = time.perf_counter()
results = []
with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
    futures = [executor.submit(provision, index) for index in range(1, USER_COUNT + 1)]
    for future in as_completed(futures):
        results.append(future.result())
elapsed = time.perf_counter() - started
latencies = sorted(item[1] for item in results)
p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
assert len({item[0] for item in results}) == USER_COUNT
print(json.dumps({
    "status": "PASS",
    "users": USER_COUNT,
    "unique_user_ids": USER_COUNT,
    "group": GROUP_NAME,
    "role": "viewer",
    "concurrency": CONCURRENCY,
    "elapsed_seconds": round(elapsed, 3),
    "provision_p50_ms": round(statistics.median(latencies), 3),
    "provision_p95_ms": round(p95, 3),
}, indent=2, sort_keys=True))
