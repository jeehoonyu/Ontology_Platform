# Ontology Manager

> Ontology Manager (OMA) is the central admin application in Palantir Foundry where you build, edit, govern, and version your organization's Ontology.

## What it is

Ontology Manager is the primary interface for creating and maintaining every resource in the Foundry Ontology — object types, link types, action types, functions, and more. It lives in the Foundry Workspace (accessible at `/workspace/ontology`) and acts as the single control plane for ontology governance. Without OMA, teams would have no structured way to review or approve schema changes before they reach production applications that rely on the Ontology.

## When to use it

- Creating or editing **object types**, **link types**, **action types**, or **function types**
- Connecting datasets or virtual tables as datasources for object types
- Making schema changes in a safe, isolated branch before they affect production apps
- Submitting a **proposal** (analogous to a pull request) for peer review before merging changes to Main
- Reviewing or approving another team member's ontology proposal
- Monitoring usage, observability metrics, and data-update health across ontology resources
- Protecting critical resources so all future changes require branch-and-proposal approval

**When NOT to use it / alternatives:** OMA is the authoring layer. To *query* or *explore* objects, use **Object Explorer**. To build user-facing apps on top of the Ontology, use **Workshop**. To write complex analytical logic, use **Quiver** or **Functions**.

## Key concepts & terminology

- **Ontology** — The semantic layer in Foundry that maps datasets to real-world entities (objects, relationships, actions).
- **Object Type** — A class of real-world entities (e.g., "Aircraft", "Customer") with typed properties and datasource backing.
- **Link Type** — A named relationship between two object types (e.g., "Customer places Order").
- **Action Type** — A defined operation that captures user input and writes back to underlying systems.
- **Function Type** — Custom business logic authored in TypeScript or Python, versioned and tracked in OMA.
- **Branch** — An isolated copy of the Ontology where changes can be made and tested without affecting Main.
- **Main** — The production version of the Ontology that all live applications consume.
- **Proposal** — A request to merge changes from a branch into Main; reviewed and approved before merging (analogous to a Git pull request).
- **Merge Check** — An automated verification that runs when a proposal is created to detect conflicts or errors between the branch and Main.
- **Rebase** — Syncing your branch with the latest state of Main to incorporate upstream changes and resolve conflicts.
- **Protected Resource** — An object type, action type, link type, interface type, or shared property type that requires branch-and-proposal approval for any modification.
- **Global Branching** — A Foundry-wide branching system (GA as of May 2026) that creates a shared branch across multiple applications (including OMA) so changes can be tested end-to-end before merging.

## Core capabilities / features

**Resource Authoring**
- Create and configure object types with properties, datasource mappings, granular security controls, and struct/shared-property reuse.
- Define link types that express directional relationships between object types.
- Build action types with logic, parameters, and observability monitoring.
- Manage function types with version history and direct links to the Functions Code Repository.

**Branching and Isolation**
- Create a new branch directly from the branch selector in OMA's top bar, or choose "Save to new branch" when editing a protected resource.
- Branches are always forked from Main — you cannot branch from another branch.
- Once your branch has object types indexed, their data is available for preview and testing on the branch before production impact.

**Proposals and Governance**
- When changes are ready, create a proposal from the branch taskbar. Merge checks run automatically to flag conflicts.
- The Proposal Overview page shows all edits grouped by author and by task (one task = one ontology resource), reviewer assignments, and overall stage.
- Assign specific colleagues as reviewers; approvers must be editors or owners of the relevant resources.
- Approve or reject individual tasks in bulk; leave task-level comments for collaboration.
- The **Changelog tab** provides a full audit history of every edit, by user and timestamp.
- Proposals are categorized: My proposals / Assigned to me / In review / Merged / Closed.

**Conflict Resolution and Rebasing**
- If Main has been updated while your branch is open, a blue indicator appears. Branches with no ontology changes rebase automatically; branches with changes require manual rebase.
- Conflicts are resolved resource-by-resource: accept Main's version, keep your branch's version, or apply a custom resolution. All conflicts must be cleared before merging.

**Observability and Monitoring**
- Action Type and Function Type views include Observability tabs showing near-real-time usage data over the last 30 days.
- Function Type view tracks version history and which applications have consumed each version.

**Access and Navigation**
- Three access routes: Workspace sidebar Apps section, right-click on an object type in Data Lineage, or direct URL `/workspace/ontology`.
- The Discover page is a customizable landing showing favorites and recently-viewed resources.

## How it works / typical workflow

1. **Open OMA** via the Workspace sidebar or `/workspace/ontology`.
2. **Create a branch** using the branch selector in the top bar ("Create new branch") and give it a descriptive title.
3. **Make changes** — create or edit object types, link types, action types, or functions on your branch. Protected resources automatically require a branch.
4. **Preview and test** — once object types are indexed on the branch, verify their data and behavior without touching production.
5. **Rebase if needed** — if Main has moved ahead, use the rebase option to sync your branch and resolve any conflicts.
6. **Create a proposal** from the branch taskbar. Merge checks run automatically.
7. **Assign reviewers** and iterate — reviewers inspect the Changelog and Review Changes tabs, leave comments, and approve or reject individual tasks.
8. **Merge** — once all required approvals are obtained and merge checks pass, merge the Global Branching proposal to incorporate changes into Main.

## Example

**Scenario:** A data engineer wants to add a new `FlightRoute` object type and link it to the existing `Airport` object type.

1. In OMA, they open the branch selector and click "Create new branch" named `feature/flight-route`.
2. They create a new object type `FlightRoute` with properties `routeId`, `origin`, `destination`, and connect it to the flights dataset.
3. They add a link type `Airport serves FlightRoute` connecting `Airport` to `FlightRoute`.
4. They wait for the object type to index on the branch, then verify data looks correct in the preview.
5. They create a proposal, assign a senior ontology owner as reviewer, and share the proposal link.
6. The reviewer inspects the Changelog tab, approves the `FlightRoute` and link type tasks.
7. The proposal is merged — `FlightRoute` is now live in Main for Workshop apps and Object Explorer to consume.

No code snippet is required here; all steps are UI-driven within OMA.

## How it connects to the rest of Foundry

- **Ontology (core)** — OMA is the editing interface for everything in the Ontology layer; the Ontology itself is consumed by all downstream tools.
- **Object Explorer** — consumes object types defined in OMA for search and analysis.
- **Workshop** — builds user-facing applications on top of object types and action types authored in OMA.
- **Functions** — function logic is written in the Functions Code Repository but versioned and monitored inside OMA's Function Type view.
- **Quiver** — uses object types and link types for complex graph analysis.
- **Data Lineage** — surfaces object types visually; right-clicking opens OMA for that resource.
- **Global Branching** — OMA branches are part of the broader Global Branching system, allowing coordinated cross-application changes (e.g., OMA + Pipeline Builder + Workshop) on one branch.
- **Permissions / Project Permissions** — resources must be migrated to project permissions before they can be protected; approval policies flow from project roles (editor, owner).

## Tips & gotchas for learners

- **You can only branch from Main**, not from another branch. Plan your changes accordingly to avoid long-running branches that diverge significantly.
- **Protection is one-way** — once a resource is protected, every change requires a proposal. Make sure your team is comfortable with the review workflow before enabling protection on high-traffic object types.
- **Merge checks are blocking** — a failed merge check (conflict with Main) must be resolved via rebase before you can merge your proposal, not after.
- **Indexing takes time** — object types on a branch need to be indexed before preview data is available. For large datasets this can take minutes; don't assume data is ready immediately after branching.
- **Approver identity matters** — the approver must be an editor or owner of the specific resource, not just any Foundry user. Coordinate access roles in advance.
- **Global Branching vs. legacy ontology branches** — legacy ontology branches (still documented as "Ontology branches [Legacy]") are a separate, older system. Prefer Global Branching for all new work as it became GA in May 2026 and supports cross-application coordination.
- **Observability data is near-real-time and covers only 30 days** — it is useful for spotting active usage but not a substitute for full audit logs.

## Official documentation

- [Ontology Manager — Overview](https://www.palantir.com/docs/foundry/ontology-manager/overview)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontologies — Branching the Ontology: Overview](https://palantir.com/docs/foundry/ontologies/test-changes-in-ontology)
- [Ontologies — Review Ontology Proposals](https://www.palantir.com/docs/foundry/ontologies/review-ontology-proposals)
- [Ontologies — Proposals](https://www.palantir.com/docs/foundry/ontologies/ontologies-proposals)
- [Ontologies — Ontology Branches (Legacy)](https://www.palantir.com/docs/foundry/ontologies/ontology-branches-legacy)
- [Global Branching — Overview](https://www.palantir.com/docs/foundry/foundry-branching/overview)
