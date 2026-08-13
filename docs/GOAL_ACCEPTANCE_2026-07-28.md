# Collaborative Operational Intelligence Runtime Acceptance

Originally validated on 2026-07-28 and extended on 2026-07-31 from `codex/builder-ux-production`.
This record maps the production-runtime goal to executable evidence. It does not claim
Palantir source or infrastructure compatibility.

## Requirement Evidence

| Requirement | Authoritative evidence | Result |
| --- | --- | --- |
| Clean organization deployment | `docker-compose.production.yml`, `docker-compose.rehearsal.yml`, `scripts/rehearse-production-acceptance.ps1` | PASS |
| Real OIDC and tenant/project permissions | Two successful `frontend/tests/production/oidc-rbac.spec.ts` runs before and after API restart | PASS |
| OIDC identity scale and replica consistency | 200 distinct Keycloak PKCE identities at concurrency 20, two API replicas, tenant/project claim checks, read checks, and 200 backend-enforced mutation denials | PASS |
| Own-data onboarding | Production browser flow creates and validates an import, generates/applies ontology, delivers a pipeline, and hydrates two objects | PASS |
| Collaborative artifact authoring | Cross-replica join, SSE event delivery, atomic commands, optimistic lock update, and idempotent replay in the production browser flow | PASS |
| Pipeline, Workshop, ontology, and AIP publication | Production browser flow creates/delivers Pipeline Builder output, renders/publishes Workshop, applies ontology, and runs AIP Logic | PASS |
| Scalable asynchronous execution | Durable job/worker tests plus cross-replica idempotency, 50 concurrent readers, abandoned lease recovery, stale-token fencing, and successful replacement completion | PASS |
| Governed ontology packages | `oms/test_tenancy_ontology_packages.py` covers capture, integrity, publish, namespaced installation, upgrade, guarded rollback, and project boundaries | PASS |
| Explainable governed automation | Decision, AIP agent, policy, approval, action, audit, and operational-event tests; production workflow reaches `APPROVAL_REQUIRED`, approval, action success, and report | PASS |
| Connectors and streaming ingestion | REST/PostgreSQL/S3/SFTP/Kafka adapter tests, durable cursors, credential protections, budgets, dead letters, retries, and stream replay tests | PASS |
| Observability and cost/performance controls | Runtime observations, budgets, SLOs, fair queues, worker fleet controls, and Control Panel browser acceptance | PASS |
| Human-usable responsive experience | 156 Playwright cases across 375, 768, 1280, and 1600 pixel profiles; 73 applicable cases passed and 83 profile-specific cases were intentionally skipped, including WCAG serious/critical checks, stateful builder workflows, and signed-extension onboarding | PASS |
| Failure and version recovery | Artifact compare/restore tests, version 3 project snapshots, 48-request readiness concurrency test, API restart recovery, and fresh-volume PostgreSQL staged backup/restore | PASS |
| Security boundaries | Zero production npm audit vulnerabilities; viewer mutation/execution denial, cross-project denial, cross-organization denial, hashed worker tokens, and encrypted connector credentials | PASS |
| Migration safety | Idempotent SQLite migration chain, signed-plugin, async-execution, Decision Intelligence project-scope, and object-materialization rollback/upgrade verification at head `0037_cross_stream_joins`, serialized replica startup, and restored-head verification | PASS |

## Executed Release Gates

- `155` backend test scripts: PASS in one sequential run (490.1 seconds).
- `python oms/validate_docs_conformance.py`: PASS, 72 rows, 276 executable assertions, and no required P0 gap.
- Digest-pinned plugin OCI rehearsal: PASS with typed SDK execution and filesystem, network, subprocess, and incompatible-SDK denial evidence.
- P0/P1 matrix audit: `0` `PARTIAL` or `MISSING` rows.
- `npm audit --omit=dev --audit-level=high`: PASS, zero vulnerabilities.
- `npm run build`: PASS.
- `npm run test:e2e`: PASS, 73 applicable cases and 83 intentional profile skips across 156 cases in 74.6 seconds.
- Production Compose validation and multi-stage Docker image build: PASS.
- `scripts/rehearse-production-acceptance.ps1`: PASS in 121 seconds.
- Extended clean production rehearsal: PASS in 147.8 seconds, including 200 distinct identities with login p95 4,582.792 ms and migration head `0031_artifact_review_workflows`.
- Authenticated WebSocket production rehearsal: PASS before and after API restart; PostgreSQL process-loss chaos resumed across replicas with zero missed/duplicate command events and 209.067 ms maximum reconnect.
- Integrated fresh-volume backup/restore: `RECOVERY_REHEARSAL_PASSED`.
- Isolated acceptance containers, network, and volumes were removed after the run.

## Defect Gate

No unresolved product P0 or P1 defect was found. The docs conformance matrix contains
no P0/P1 `PARTIAL` or `MISSING` row.

Two non-blocking conditions remain:

1. GitHub-hosted Actions cannot currently allocate a runner because the repository
   account reports a payment/spending-limit issue. The workflow is registered and
   triggers correctly, but jobs terminate before checkout with zero steps. The exact
   local equivalents above pass. Owner: repository administrator; resolution is an
   account billing/spending-limit change, not a product patch.
2. Route-level splitting reduced the prior 635.4 KB main chunk to approximately 231 KB. Remaining legacy workspace migration is a P2 product-cohesion follow-up. Owner: frontend platform.

## Acceptance Decision

The self-hosted production-pilot contract is accepted for the stated scope: one
organization, project-enforced access, 5-50 concurrent users, deterministic local
execution by default, and optional independently deployed workers/connectors. Broader
internet-scale multi-region operation and proprietary managed-service parity remain
outside this local platform contract.
