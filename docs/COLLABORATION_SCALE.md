# Collaboration Scale and Correctness

OntologyOS visual artifacts use a server-authoritative PostgreSQL command log. This document defines the measured collaboration boundary for the current modular-monolith deployment.

## Correctness Model

- Every accepted command batch locks the artifact row before allocating its revision and lock version.
- PostgreSQL locks refresh the SQLAlchemy identity-map value after waiting. This prevents a replica that authorized against stale state from allocating a duplicate revision.
- Target-disjoint stale-base commands rebase against the current revision. Overlapping targets return a durable conflict instead of overwriting work.
- The artifact revision, command receipt, and collaboration event commit atomically. Together they are the authoritative recovery record for an accepted command.
- Audit and operational outbox evidence is written immediately after releasing the artifact lock. This keeps the serialized section bounded while retaining actor and operations evidence.
- Request-hashed idempotency receipts make retries safe across replicas. A reused key with different commands is rejected.

## Rehearsal

`oms/verify_collaboration_scale_postgres.py` starts two independent Uvicorn API processes against one migrated PostgreSQL database and uses real HTTP sockets. It then:

1. Creates one pipeline artifact with 20 independently addressable nodes.
2. Joins 20 editor sessions across both replicas.
3. Submits 20 target-disjoint commands simultaneously from the same base revision.
4. Requires contiguous revisions 2 through 21, 19 explicit rebases, and zero lost node movements.
5. Enforces command acknowledgement p95 below 250 ms.
6. Performs 200 simultaneous reads across both replicas and verifies identical committed state.
7. Verifies the durable collaboration event count and unique lock versions.

Two consecutive local rehearsals on July 31, 2026 produced:

| Run | Editor acknowledgement p50 | Editor acknowledgement p95 | 200-reader batch | Lost updates |
|---|---:|---:|---:|---:|
| 1 | 127.460 ms | 206.458 ms | 0.567 s | 0 |
| 2 | 134.197 ms | 224.866 ms | 0.623 s | 0 |

These figures are regression evidence from the development host, not a universal capacity claim. CI repeats the same correctness and 250 ms p95 contract on its PostgreSQL job.

## Run It

Apply migrations to a disposable PostgreSQL database, then run:

```bash
python oms/verify_collaboration_scale_postgres.py
```

Optional limits:

- `COLLABORATION_ACK_P95_LIMIT_MS`, default `250`
- `COLLABORATION_READ_BATCH_LIMIT_SECONDS`, default `15`

## OIDC Identity Scale

The clean July 31 production rehearsal provisioned and authenticated 200 distinct Keycloak users using authorization code with PKCE at concurrency 20. Every identity carried the expected `pilot/default` scope, read through both API replicas, and received `403` for an artifact mutation. The run measured login p50 3,532.616 ms and p95 4,582.792 ms against a 15-second gate. Machine-readable evidence is stored in `docs/oidc-identity-scale-evidence.json`.

## WebSocket Recovery

Collaboration events are fanned out through `/artifacts/{artifact_id}/collaboration/ws` from the same append-only PostgreSQL command log used by HTTP commands and SSE compatibility clients. The WebSocket authenticates the OIDC session or bearer token, enforces project `view` permission and production origin policy, emits a durable integer cursor, and accepts reconnects with `after={cursor}`. Mutations remain on the idempotent HTTP command endpoint so revision allocation and receipts retain one transaction boundary.

`oms/verify_collaboration_websocket_chaos_postgres.py` starts two Uvicorn replicas, receives an edit through the first replica, terminates that process, reconnects to the peer from the last cursor, restarts the first replica, and resumes again. The July 31 rehearsal observed three ordered command events, zero duplicates, zero missed events, final revision 4, and maximum reconnect 209.067 ms against a five-second gate. Real Keycloak acceptance separately proves cookie-authenticated browser WebSockets and origin enforcement before and after API restart. Evidence is stored in `docs/collaboration-websocket-chaos-evidence.json`.

## Remaining Production Gates

- Long-duration WebSocket presence, rolling multi-replica deployment, and repeated network partition testing remain beyond the verified process-loss/restart rehearsal.
- The clean production rehearsal proves 200 distinct OIDC identities, two-replica reads, backend RBAC denial, API restart, tenant isolation, and fresh-volume backup/restore. Sustained availability and repeated scheduled RPO/RTO evidence remain open.
- External evaluator teams must still complete the workflow independently.
