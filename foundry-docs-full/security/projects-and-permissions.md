<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · SECURITY & GOVERNANCE</b><br>
<span style="font-size:22px"><b>Projects, Roles & Permissions</b></span><br>
<span style="color:#ABB3BF">The layered access-control system that determines who can discover, view, edit, and own every resource in Foundry.</span>
</td></tr></table>

---

## What it is

Projects, Roles & Permissions is Foundry's primary security and organizational model. A **Project** is a bounded collaboration space that groups users, datasets, pipelines, applications, and other resources under a shared set of access rules. **Roles** define what operations (view, edit, own) a principal can perform within that space, and **Permissions** encode which users or groups hold which roles. Together these three concepts form the discretionary layer of Foundry's access-control stack, sitting above the platform's mandatory controls (Organizations and Markings).

---

## How it works

### 1. The two-layer access model

Foundry enforces access through two independent mechanisms that must both be satisfied:

- **Mandatory controls** — Organizations and Markings propagate automatically with data via provenance and lineage. They create absolute gates: even an Owner-role holder cannot access a resource if they lack the required marking eligibility.
- **Discretionary controls** — Role grants on Projects, folders, and files. These expand what an eligible user *can do* once mandatory gates are passed.

### 2. Organizations as hard silos

An **Organization** is the top-level mandatory control. It creates a strict silo: users in different organizations cannot see each other's resources unless cross-organization sharing is explicitly configured. Organizations are provisioned in **Control Panel**; each user belongs to one or more organizations, and each resource carries an organization access requirement. Two permissions govern org interactions:

- **Apply organization** — lets a user stamp an organization requirement onto a resource.
- **Expand access** — lets a user remove or broaden an organization requirement.

### 3. Spaces as resource containers

A **Space** (formerly "namespace") is a logical container that sits above Projects. When an administrator creates a Space in Control Panel, they configure its billing account, compute queue, data-storage filesystem, deletion policy, and the **role set** that will govern all Projects within it. Projects inherit these settings unless overridden. Custom roles created at the Space level are "frozen" — Palantir's periodic additions to the default role set do not automatically flow into them.

### 4. Projects as the primary security boundary

A **Project** is the unit around which permissions are practically managed. Core mechanics:

1. **Creation** — Any user with Editor or Owner access on a Space may create a Project within it.
2. **Security boundary** — Inputs and outputs of a pipeline must reside in the same Project. Cross-Project data access is possible only through **file references** (lightweight wrappers that forward read access without granting access to the upstream Project itself).
3. **Uniform baseline, varied levels** — The recommended design is that all collaborators on a Project share a common baseline role (e.g., Viewer) while subgroups hold elevated roles (e.g., Editor or Owner).
4. **Role inheritance** — A role granted at the Project level cascades automatically to every folder and file inside it. This inheritance can be restricted by an Owner who disables folder/file-level role grants in Project Settings; doing so removes all existing sub-resource grants and prevents new ones.

### 5. The four default roles

| Role | Key operations | Can grant |
|---|---|---|
| **Owner** | All edit operations + delete, change settings, manage markings | Owner, Editor, Viewer, Discoverer |
| **Editor** | Read, write, build, publish | Editor, Viewer, Discoverer |
| **Viewer** | Read-only access to content | Viewer, Discoverer |
| **Discoverer** | Can see the resource name/metadata but not content | Discoverer only |

Role grants are **hierarchical but not independent**: each role is a superset of the one below it. Roles live inside **Role Sets** — named bundles tied to a specific context (Projects, Ontology, Marketplace). All Projects in a Space share the same Role Set unless an administrator applies a different one.

### 6. Custom role sets

Administrators with Organization Administrator permission in Control Panel can:

1. Navigate to **Platform Settings → Roles**.
2. Create a new Role Set (optionally copying an existing one to inherit its permissions).
3. Add, remove, or modify operations within each role — for example, adding "Merge to protected branch" to the Editor role to create a **Merger** role.
4. Assign the Role Set to a Space (or remap existing role grants when switching sets).

Custom roles are frozen snapshots; default roles in a copied set still receive automatic Palantir updates, but entirely custom roles do not.

### 7. Group-based permission management

Foundry strongly recommends granting roles to **Groups** at the Project level rather than to individual users. A canonical Project setup uses three groups: one for Viewers, one for Editors, one for Owners. Groups are managed internally in Foundry or federated from an external identity provider. This approach makes audit trails legible and reduces the surface area for permission drift.

### 8. Access requests

Users without Project access can submit a request directly from the **Projects & Files** view, the Project view, or the Actions dropdown. The request captures the reason, the desired access level, and the approving group or user. Requests routed through group administrators are preferred over direct user grants.

### 9. Markings (mandatory overlay)

**Markings** are binary eligibility requirements applied to files, folders, or Projects. A user must satisfy the requirements for **every** marking on a resource simultaneously (conjunctive logic). Markings propagate down the file hierarchy and upstream through data lineage — a derived dataset inherits all markings of its source datasets. Common strategies:

- One marking per sensitivity category (PII, PHI, financial).
- Per-owner markings where data owners control their own datasets.
- Pipeline-stage markings (raw vs. processed).
- Discovery restriction markings that hide resources from search.

Markings are independent of roles: an Owner-role holder cannot remove a marking without also holding the marking's **Expand Access** permission.

---

## User interface

### Overall layout

The primary entry point is the <span style="color:#8ABBFF">**Compass / Home**</span> navigation in the left sidebar. From there, <span style="color:#8ABBFF">**Projects & Files**</span> opens the main resource browser.

<table style="background:#1C2127;border:1px solid #383E47;border-collapse:collapse;width:100%">
<tr style="background:#252A31">
  <th style="padding:8px 12px;color:#ABB3BF;text-align:left">Screen / Panel</th>
  <th style="padding:8px 12px;color:#ABB3BF;text-align:left">What you see</th>
</tr>
<tr>
  <td style="padding:8px 12px;color:#fff;border-top:1px solid #383E47"><span style="color:#8ABBFF"><b>Projects & Files</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-top:1px solid #383E47">Card grid of all Projects you can discover. Each card shows Project name, space, owner group, and your current role chip.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#fff;border-top:1px solid #383E47"><span style="color:#8ABBFF"><b>Project Settings → Permissions</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-top:1px solid #383E47">Table of principals (users/groups) and their assigned roles. Add/remove role grants here. Toggle to disable sub-resource grants.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#fff;border-top:1px solid #383E47"><span style="color:#8ABBFF"><b>Platform Settings → Roles</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-top:1px solid #383E47">List of all Role Sets. Click into a set to see each role's operations. "New Role" button at top-right. Each role shows inherited roles and individual operations.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#fff;border-top:1px solid #383E47"><span style="color:#8ABBFF"><b>Control Panel → Space management</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-top:1px solid #383E47">Table of all Spaces. Actions dropdown exposes role set assignment, inherited role configuration, and billing/compute settings.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#fff;border-top:1px solid #383E47"><span style="color:#8ABBFF"><b>Access Request modal</b></span></td>
  <td style="padding:8px 12px;color:#ABB3BF;border-top:1px solid #383E47">Multi-field form: reason for request, desired role level, target group/user for approval routing.</td>
</tr>
</table>

**Role state chips used across the UI:**

<span style="color:#238551"><b>● Owner</b></span> · <span style="color:#2D72D2"><b>● Editor</b></span> · <span style="color:#C87619"><b>● Viewer</b></span> · <span style="color:#ABB3BF"><b>● Discoverer</b></span>

**Key interactions:**
- Dragging a resource into a Project folder triggers a permission-remapping dialog if the destination has a different Role Set.
- Disabling file/folder-level role grants shows a confirmation warning that all existing sub-resource grants will be destroyed.
- When creating a file reference, Foundry validates that you hold Viewer on the source Project and Editor on the destination Project before allowing the operation.

---

## Worked example

**Scenario:** An analytics team wants to build a pipeline that reads raw HR data (marked PII) and produces a de-identified report for the finance team.

1. **Organization check** — The HR and finance teams belong to the same Organization, so the org silo is not an obstacle.
2. **Marking eligibility** — The raw HR dataset carries the `PII` marking. The three pipeline engineers are added to the `PII-Eligible` group in Control Panel, satisfying the mandatory gate.
3. **Project setup** — An Owner creates `HR-Pipeline` Project in the `Analytics` Space. Three groups are added at Project level: `hr-pipeline-owners` (Owner), `hr-pipeline-editors` (Editor), `hr-pipeline-viewers` (Viewer).
4. **File reference** — The pipeline reads the raw HR dataset from the `HR-Raw` Project via a file reference. The pipeline engineers hold Viewer on `HR-Raw` and Editor on `HR-Pipeline`, so Foundry permits the reference.
5. **Output dataset** — The de-identified output is written into `HR-Pipeline`. Because it is derived from the PII-marked source, it inherits the `PII` marking automatically. The team applies a separate `De-identified` marking to signal that the data itself is safe — they hold Expand Access permission to do so.
6. **Finance access** — The finance group is granted Viewer on `HR-Pipeline` and is added to the `De-identified` marking's eligibility list. They can now read the output without ever touching the raw PII source.

---

## Documentation map

- **Concepts**
  - [Projects and roles](https://www.palantir.com/docs/foundry/security/projects-and-roles) — core mechanics, role hierarchy, references
  - [Markings](https://www.palantir.com/docs/foundry/security/markings) — mandatory controls, inheritance, scoped sessions
  - [Security overview](https://www.palantir.com/docs/foundry/security/overview) — four-pillar model, mandatory vs. discretionary controls
- **Management**
  - [Manage roles](https://www.palantir.com/docs/foundry/platform-security-management/manage-roles) — creating/editing roles and role sets, custom roles
  - [Manage organizations and spaces](https://www.palantir.com/docs/foundry/platform-security-management/manage-orgs-and-spaces) — org creation, Space setup, role set assignment
  - [Manage groups](https://www.palantir.com/docs/foundry/platform-security-management/manage-groups) — internal and federated group administration
- **Building pipelines**
  - [Recommended project and team structure](https://www.palantir.com/docs/foundry/building-pipelines/recommended-project-structure) — three-group pattern, Project layout best practices
  - [Remove inherited markings and organizations](https://www.palantir.com/docs/foundry/building-pipelines/remove-inherited-markings) — pipeline-level marking management
- **Reference**
  - [Data Connection permissions reference](https://www.palantir.com/docs/foundry/data-connection/permissions) — source-system role operations

---

## Official documentation

- [Security overview](https://www.palantir.com/docs/foundry/security/overview)
- [Concepts: Projects and roles](https://www.palantir.com/docs/foundry/security/projects-and-roles)
- [Concepts: Markings](https://www.palantir.com/docs/foundry/security/markings)
- [Management: Manage roles](https://www.palantir.com/docs/foundry/platform-security-management/manage-roles)
- [Management: Manage organizations and spaces](https://www.palantir.com/docs/foundry/platform-security-management/manage-orgs-and-spaces)
