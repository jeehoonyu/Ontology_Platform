# Project Tenancy And Ontology Packages

Production resources are scoped by both a global role and project membership. A global permission alone does not grant access to a project.

## Identity Claims

OIDC sessions recognize:

- `organization_id` or `org_id`: the organization boundary;
- `project_ids` or `projects`: a string array of directly assigned projects; and
- the configured roles claim: global capabilities such as `view`, `edit`, `publish`, and `restore`.

Persisted project memberships can grant `viewer`, `editor`, `operator`, `publisher`, `approver`, or `administrator` capabilities within a project. Effective permission is the intersection of global capability and project capability. Local development is explicitly represented as the wildcard project principal; this bypass is unavailable in the production profile.

Service-account tokens can use scopes such as `project:operations:execute`. The middle segment grants project visibility and the final segment grants the corresponding global capability for that token.

Administrative APIs are under `/tenancy/*`. `POST /tenancy/bootstrap` idempotently creates a first organization, project, and administrator membership.

## Governed Ontology Packages

An ontology package has an owning organization and project. Each version is immutable and contains:

- schema version and package ID;
- object types and property schemas;
- link types and cardinality;
- governed action types;
- exact package-version dependencies;
- validation evidence; and
- a canonical SHA-256 checksum.

The lifecycle is:

1. Create a package with `POST /ontology-packages`.
2. Capture existing object types or submit a structured manifest.
3. Validate the version.
4. Publish it with the expected checksum.
5. Install it into an authorized target project and namespace.
6. Upgrade by installing a newer published version into the same namespace.
7. Roll back the active installation when necessary.

Installations create namespaced resource IDs and persistent ownership records. An installer cannot overwrite a resource owned outside that package and namespace. Dependencies must already be active in the target project. Rollback restores the prior schema and installation; it refuses to remove a newly installed object type when live object instances depend on it.

Every create, publish, install, and rollback operation emits audit evidence. Package versions, installations, ownership records, tenancy records, durable builder command receipts, and collaboration events are included in project JSON snapshot export/import. Database backup remains the authoritative disaster-recovery mechanism.

## User Interface

Ontology Manager includes a Governed Packages panel. Administrators can initialize a workspace, create a package from the selected object type, capture a semantic version, publish it, and install it without editing JSON.
