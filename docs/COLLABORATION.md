# Visual Builder Collaboration

The artifact runtime supports shared editing sessions for Pipeline, Ontology, Workshop, AIP Logic, investigation, graph, and entity-resolution artifacts. Collaboration is local and deterministic: every accepted command creates an immutable artifact revision, an audit record, and an ordered collaboration event.

## Session Lifecycle

1. Join with `POST /artifacts/{id}/collaboration/join` and a stable browser `client_id`.
2. Keep the returned `participant_token` private. It is scoped to the authenticated principal, browser client, and artifact.
3. Send selection and cursor state to `POST /artifacts/{id}/collaboration/heartbeat`.
4. Read active participants from `GET /artifacts/{id}/collaboration`.
5. Subscribe to `GET /artifacts/{id}/collaboration/stream` for ordered server-sent events. Reconnects resume from the greater of the `after` query cursor and the standard `Last-Event-ID` header, so a native `EventSource` does not replay already-observed events.
6. Leave explicitly or allow the session to expire. Expired participants are pruned and recorded as presence events.

The React builders use a 90-second session and heartbeat every 20 seconds. When live collaboration is unavailable, the editor falls back to the existing exclusive editing lease and clearly labels that state.

## Optimistic Commands

Collaborative saves use `POST /artifacts/{id}/collaboration/commands` with:

- the participant token;
- the artifact lock version last observed by the client;
- an idempotency key;
- granular builder commands; and
- a human-readable revision message.

The browser derives commands for added, updated, moved, and removed nodes and edges. It does not replace the complete canvas for normal collaborative saves.

If another user changed a different target after the client's observed lock version, the server rebases the command batch onto the latest revision. If targets overlap, the server rejects the batch with `409`, records an `artifact.conflict` event, and returns the incoming and concurrent targets. The UI preserves local work and asks the user to reload the shared revision deliberately.

## Evidence And Recovery

Accepted command batches produce:

- a new `ArtifactRevision`;
- an `artifact.collaboration.commands_applied` audit entry;
- an ordered `artifact.commands` collaboration event;
- an append-only idempotency receipt in `platform_artifact_command_receipts`, bound to a canonical request hash; and
- the normal version compare, restore, publish, and rollback path.

Presence events do not create artifact revisions. Publish, restore, and whole-artifact edits conflict with stale command batches because they affect the complete artifact. Receipts are not truncated as an artifact accumulates edits. Reusing a key with different commands returns `409`; retrying the same commands returns the original receipt and does not create a revision.

## Permissions And Deployment

Viewing room state and events requires `view`. Joining, heartbeats, leaving, and command submission require `edit`. The participant token is additionally bound to the authenticated principal. OIDC/RBAC therefore remains the authorization boundary; collaboration tokens do not grant permissions.

Migration `0005_artifact_collaboration` creates the participant and event tables. Migration `0012_artifact_receipts` adds durable receipts for both standard and collaborative builder commands and migrates retained legacy metadata receipts. These tables are included in startup schema health checks and portable snapshots. Production deployments should preserve receipts and event rows with artifact revision and audit history during backup and restore. PostgreSQL API replicas serialize Alembic startup with a transaction-scoped advisory lock so simultaneous container starts cannot race schema DDL.

## Current Scope

- Ordered events use server-sent events, which works across API replicas when all replicas share the same Postgres database.
- The production acceptance rehearsal starts two API replicas, submits a builder command to the peer, requires the primary replica's SSE stream and artifact read to observe the same committed revision, and then retries the command through the primary to prove cross-replica durable idempotency.
- Presence is ephemeral and expires automatically.
- Command application is atomic and uses row locking on databases that support it.
- The current conflict model is target-based, not a free-form CRDT. This is intentional: governed visual artifacts retain deterministic revisions and explicit recovery semantics.
- SQLite remains suitable for single-process development. Shared PostgreSQL is required for multi-replica collaboration and production rehearsal.
