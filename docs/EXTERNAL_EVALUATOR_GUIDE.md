# Independent Evaluator Guide

This guide is for a team that did not develop OntologyOS. Its purpose is to prove
that a new organization can deploy the platform and complete the Asset Reliability
`Connect -> Transform -> Model -> Analyze -> Approve -> Act -> Report` workflow
with its own data and visible UI controls.

An evaluation is evidence, not a product survey. Do not edit database rows, call
workflow APIs manually, use the bundled sample scenario, or mark an incomplete step
as complete. The server derives completion from persisted resources.

## Before You Start

1. Use a clean production deployment with PostgreSQL, OIDC, TLS, migrations, and
   persistent snapshot storage as described in [Production Pilot Operations](PRODUCTION_PILOT.md).
2. Deploy an immutable release image and set `ONTOLOGYOS_RELEASE_COMMIT` to the full
   Git commit represented by that image. A development or unpinned build cannot
   produce qualifying evidence.
3. Create a new organization and project for the evaluation. Do not reuse another
   evaluator's database, project, deployment, or identity provider account.
4. Prepare a CSV or JSON file containing at least one real or safely de-identified
   asset. It must include a stable identifier and should include name, status,
   criticality, failure probability, latitude, and longitude fields.
5. Choose non-sensitive identifiers for the evaluator team, organization, and
   deployment. The evaluator alias is hashed by the server and is not returned.

Do not submit names, email addresses, source records, credentials, or proprietary
operational values with the evaluator bundle. The bundle contains resource IDs,
counts, content hashes, workflow evidence, and the generated decision report only.

## Complete the Workflow

1. Sign in through OIDC and open **Data Onboarding**.
2. Upload or paste the organization's CSV/JSON, inspect the raw preview, apply any
   required mapping/transforms, validate it, and select **Promote to dataset**.
3. Open **Command Center**. Under **Use your promoted dataset**, enter the project,
   promoted dataset, and field mappings. Select **Compile and run workflow**.
4. Wait for the workflow to show a successful immutable source snapshot, pipeline
   plan/run, published ontology contract, hydrated objects, and risk result.
5. Select **Analyze your highest-risk asset**. Read the explanation and cited proof
   before making an approval decision.
6. Enter an approval reason and approve the proposed inspection action. Then select
   **Execute approved action**. Confirm that execution evidence names the approval,
   outbox event, and mutated object.
7. Select **Export proof report** and inspect the decision, findings, approval,
   action, incident, investigation, and evidence references.
8. Confirm that every flow step through **Report** has server-backed evidence.

## Export the Sealed Bundle

In **Independent evaluator evidence**:

1. Enter unique team, organization, and deployment IDs plus a non-sensitive alias.
2. Confirm that the team is independent from OntologyOS development.
3. Confirm that the workflow used the organization's data rather than sample data.
4. Select **Export sealed evaluator evidence**.
5. The panel must show `QUALIFYING` and no corrective reasons. A downloaded but
   non-qualifying bundle does not satisfy the gate.

The bundle binds the immutable dataset content hash, migration head, release commit,
authenticated principal hash, all seven workflow steps, report hash, and canonical
bundle hash. Changing any field after export invalidates it.

## Submit and Verify

Place each team's unmodified JSON file in `docs/external-evaluations/` on the release
candidate branch, or pass explicit paths:

```bash
python oms/validate_external_evaluations.py team-alpha.json team-beta.json
```

The command exits nonzero unless at least two bundles:

- pass every server-side and offline integrity check;
- represent distinct teams, organizations, deployments, evaluator identities,
  authenticated principals, and dataset fingerprints;
- use the same immutable release commit and migration head; and
- contain evidence for every Connect-to-Report step.

For readiness reporting before submissions exist, use:

```bash
python oms/validate_external_evaluations.py --allow-incomplete
```

`--allow-incomplete` never changes the reported `FAIL`; it only prevents the
readiness command from failing a build. Release acceptance must use strict mode.

## Escalate Problems

Record the route, visible operation, timestamp, browser, deployment release commit,
and whether retrying changed the result. Do not include credentials or raw source
records. A P0/P1 defect blocks external acceptance; a P2 must have an owner,
workaround, and scheduled milestone.
