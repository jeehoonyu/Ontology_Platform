# Artifact Review Collaboration

OntologyOS visual artifacts support persistent, target-scoped review on top of the server-authoritative command log. The workflow applies to Pipeline, Ontology, Workshop, AIP Logic, Investigation, Platform Graph, and Entity Resolution artifacts.

## Review Model

- Comments are anchored to an artifact, node, edge, or configuration field at a specific revision.
- Threads remain append-only; comments can be resolved and reopened without losing evidence.
- Change proposals contain validated builder commands, their affected targets, and the exact base revision and lock version.
- Reviewers approve or reject proposals through the backend permission boundary.
- Production defaults prevent proposal authors from approving their own work. `ARTIFACT_ALLOW_SELF_REVIEW=true` is an explicit exception for controlled deployments.
- Approved proposals apply under an artifact row lock. Non-overlapping changes rebase; overlapping changes become durable conflicts instead of overwriting published work.
- Applied proposals create a normal artifact revision, idempotency receipt, collaboration event, and audit record.

## User Workflow

1. Select an artifact or node in a visual builder.
2. Add a review comment, or prepare local visual edits and select **Propose**.
3. A user with `approve` permission reviews the affected targets and validation result.
4. An editor applies the approved proposal.
5. The builder receives the new revision through the collaboration event stream.

The visual review panel keeps structured commands and conflict evidence behind human-readable controls. Raw command JSON remains an optional developer concern.

## Recovery and Portability

Review comments and proposals are project-scoped database records. Project snapshots include both resources, preserving thread status, reviewer identity, conflicts, and applied revision references. Migration `0031_artifact_review_workflows` installs the durable tables on SQLite and PostgreSQL.

## Verification

```bash
python oms/test_artifact_review_workflows.py
python oms/test_artifact_review_workflows_migration.py
python oms/verify_artifact_review_postgres.py  # requires PostgreSQL DATABASE_URL
cd frontend && npm run build
```

The browser acceptance suite also creates, reviews, and applies a proposal from the React visual builder.
