# Projects, Roles & Permissions

> Foundry's core access model organizes resources into projects (via Compass), governed by organizations and spaces, with roles and groups granting permissions that inherit down the hierarchy.

## What it is

Everything in Foundry lives somewhere in a hierarchy, and access is governed by where it lives and who you are. **Organizations** enforce top-level silos between user populations; **projects** (browsed in **Compass**) group related resources; **roles** define what operations a user can perform; and **groups** bundle users so permissions are managed at scale. Permissions generally **inherit** from a project down to its contents, making projects the primary unit of access control.

## When to use it

- Structuring who can view/edit datasets, pipelines, ontologies, and apps.
- Onboarding teams with the right access via groups and roles.
- Enforcing separation between business units or classification levels.

**When NOT to use it / alternatives:** For row/column-level data restrictions, use **markings and classification-based access**; for encryption of values, use **Cipher**.

## Key concepts & terminology

- **Organization** — A mandatory top-level silo separating user populations.
- **Space** — A subdivision within an organization for resource management.
- **Project** — The primary grouping of resources; the main permission boundary.
- **Compass** — The application for browsing/navigating projects and resources.
- **Role** — A named set of allowed operations (viewer, editor, owner, etc.).
- **Group** — A collection of users granted roles together.
- **Permission inheritance** — Access flowing from a project down to its contents.
- **Sharing** — Granting roles on a resource/project to users/groups.

## Core capabilities / features

- **Hierarchical organization** — Orgs → spaces → projects → resources.
- **Role-based access** — Assign viewer/editor/owner-style roles per project/resource.
- **Group-based management** — Manage access at scale through groups.
- **Inheritance** — Project-level grants cascade to contained resources.
- **External identity integration** — Users/groups can come from external providers (SSO/SCIM).
- **Sharing controls** — Explicit grants and constraints on who can access what.

## How it works / typical workflow

1. **Organize resources into projects** under the right organization/space.
2. **Create or use groups** representing teams/roles.
3. **Assign roles** on projects (and specific resources where needed) to those groups.
4. Rely on **inheritance** so contents get the project's access by default.
5. **Refine** with resource-level grants and constraints where exceptions are needed.
6. **Review** access periodically.

## Example

A "Supply Chain Analytics" project is created in the Operations organization. The `supply-chain-analysts` group gets the **Viewer** role and `supply-chain-engineers` gets **Editor**. New datasets added to the project automatically inherit these grants — no per-dataset configuration needed — while a sensitive sub-folder gets a tighter explicit grant.

## How it connects to the rest of Foundry

- **All resources** — Datasets, pipelines, ontologies, and apps live in projects and inherit access.
- **Markings** — Layer mandatory data controls on top of project permissions.
- **Ontology** — Object/Action permissions integrate with this model.
- **Marketplace/DevOps** — Installed products land in projects with governed access.
- **Audit logs** — Access and grants are audited.

## Tips & gotchas for learners

- **Projects are the main boundary** — structure them around access needs.
- **Manage access via groups, not individuals** — far easier to maintain.
- **Inheritance is powerful but implicit** — know what a project grants before adding sensitive data.
- **Permissions ≠ markings** — roles grant access; markings add mandatory restrictions that even editors can't bypass.
- **Review access regularly** as teams change.

## Official documentation

- [Security: Overview](https://www.palantir.com/docs/foundry/security/overview)
- [Security: Projects](https://www.palantir.com/docs/foundry/security/projects)
- [Compass: Overview](https://www.palantir.com/docs/foundry/compass/overview)
