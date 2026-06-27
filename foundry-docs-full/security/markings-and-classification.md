<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · SECURITY & GOVERNANCE</b><br>
<span style="font-size:22px"><b>Markings &amp; Classification</b></span><br>
<span style="color:#ABB3BF">Mandatory access controls that bind sensitivity labels to resources and data lineage, restricting visibility and action to users who hold every required credential.</span>
</td></tr></table>

## What it is

Markings and Classification are Foundry's mandatory access control (MAC) layer — a step above discretionary role-based permissions. A **Marking** is a named credential requirement attached to a file, folder, project, or ontology property; a user must belong to every Marking on a resource to interact with it in any way. **Classification-based Access Controls (CBAC)** extend this with a hierarchical system for protecting government-grade sensitive information, where a user's clearance level must meet or exceed the classification of the data they are requesting.

## How it works

### 1 — The two layers of mandatory control

Foundry stacks two distinct MAC mechanisms. **Markings** enforce conjunctive (AND) membership logic: a resource tagged with marking A and marking B is accessible only when the requesting user belongs to both. **CBAC markings** (classification markings) enforce a strict hierarchy — a user cleared at "Top Secret" automatically satisfies "Secret" requirements, but the reverse is never true. CBAC also supports disjunctive (OR) logic within category groups, so a user possessing *either* Country-A or Country-B clearance can satisfy a combined category requirement.

### 2 — Marking anatomy

Every marking lives inside a **Marking Category**. Categories carry visibility settings (Visible to all users, or Hidden so only explicit Category Viewers can see it exists), organization restrictions (scoping the category to a single Foundry Organization), and two administrative roles: **Category Administrators** (can create markings and change metadata) and **Category Viewers** (can see the category and all markings within it). Within a category, each individual marking carries four independent permissions:

- **Manage permissions** — grant or revoke any of the four permissions to other users.
- **Apply marking** — place the marking on a resource (requires the resource Owner role separately).
- **Remove marking** — strip the marking from a resource (requires Apply permission as well).
- **Members** — grants actual read/view access to marking-protected resources.

None of these automatically implies any other. Holding "Apply marking" does not make you a member; being a member does not let you apply the marking elsewhere.

### 3 — Propagation along file hierarchy

When a Marking is placed on a **folder** or **Project**, it cascades automatically to every resource nested beneath it. Folder inheritance is indicated by a sidecar icon in the file browser. This hierarchy-based propagation is immediate and requires no rebuild.

### 4 — Propagation along data lineage

Markings also travel through **data dependencies** — the most powerful and consequential propagation path. When a pipeline reads from a marked dataset, the output dataset inherits that marking automatically. This prevents accidental leakage of sensitive data through derived datasets. The Data Lineage application (filtered to "Permissions type: Data access in datasets") shows exactly how markings flow through a pipeline. To stop lineage-based propagation, a data engineer must use `stop_propagating` syntax inside a transformation on a **protected branch** with "Require security approvals before merging" enabled, then rebuild the dataset and all downstream dependencies.

### 5 — Classification: file vs. data classification

CBAC introduces an important split:

| Classification type | What it controls | Editable? |
|---|---|---|
| **File classification** | Discoverability and metadata visibility | Yes, manually |
| **Data classification** | Actual data viewing | No — auto-computed as the most restrictive combination of upstream sources |
| **Project classification** | Project discovery and resource access | Yes — does NOT propagate via lineage |
| **Project maximum classification** | Upper bound for resources in a project | Yes — blocks creation of over-classified resources |

Data classification is always the most restrictive union of all upstream file and data classifications. A dataset touching "Secret" and "Unclassified" sources always surfaces as "Secret" — it cannot be manually downgraded.

### 6 — CBAC is opt-in

CBAC is not enabled by default on Foundry instances. It requires Palantir configuration and is designed for regulated government deployments. When enabled, every project must carry a classification, and every dataset must carry a classification marking — there is no classification-free resource.

### 7 — Enforcement is binary

Regardless of role (Owner, Editor, Viewer), a user without full marking membership receives zero access — no discovery, no metadata preview, no lineage view. The control is additive on top of roles, not replaceable by them.

## User interface

### Platform Settings — Markings admin console

Accessed via <span style="color:#8ABBFF">**Settings → Markings**</span>, this is the primary administrative surface. The left panel lists <span style="color:#2D72D2">**Marking Categories**</span> as a collapsible tree. Selecting a category opens a detail pane showing:

- Category name and description
- Visibility toggle (<span style="color:#238551"><b>Visible</b></span> / <span style="color:#ABB3BF">Hidden</span>)
- Organization restriction selector
- Roles table for Category Administrators and Viewers

Within a category, each <span style="color:#2D72D2">**Marking**</span> row shows membership count and a permissions grid. The <span style="color:#2D72D2">**+ New marking**</span> and **+ New marking category** buttons sit in the top-right of the console.

### Resource sidebar — applying markings

On any dataset, folder, or Project, opening the <span style="color:#8ABBFF">**Security & Access**</span> sidebar panel (accessible from the right-click context menu or the resource details drawer) shows:

- Current markings as <span style="color:#2D72D2">**label chips**</span>
- A dropdown to add markings (filtered to those where the current user holds "Apply marking")
- A lineage inheritance indicator showing where the marking came from

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;padding:8px;width:100%;margin:8px 0">
<tr style="color:#ABB3BF;font-size:12px">
<td style="padding:6px 10px"><b>State</b></td>
<td style="padding:6px 10px"><b>Chip appearance</b></td>
<td style="padding:6px 10px"><b>Meaning</b></td>
</tr>
<tr>
<td style="padding:6px 10px"><span style="color:#CD4246"><b>● BLOCKED</b></span></td>
<td style="padding:6px 10px">Red pill, lock icon</td>
<td style="padding:6px 10px">User lacks membership — no access granted</td>
</tr>
<tr>
<td style="padding:6px 10px"><span style="color:#238551"><b>● SATISFIED</b></span></td>
<td style="padding:6px 10px">Green pill, check icon</td>
<td style="padding:6px 10px">User is a member of this marking</td>
</tr>
<tr>
<td style="padding:6px 10px"><span style="color:#C87619"><b>● INHERITED</b></span></td>
<td style="padding:6px 10px">Orange pill, chain icon</td>
<td style="padding:6px 10px">Marking came from parent folder or upstream dataset</td>
</tr>
<tr>
<td style="padding:6px 10px"><span style="color:#2D72D2"><b>● CLASSIFICATION</b></span></td>
<td style="padding:6px 10px">Blue pill, shield icon</td>
<td style="padding:6px 10px">CBAC classification level label</td>
</tr>
</table>

### Workshop — property security markings

In Workshop widgets (Property List, Object List, Object Table), property-level markings appear as a <span style="color:#ABB3BF">**condensed gray pill**</span> next to the property value. Clicking the pill expands a popover showing the full marking and classification labels applied to that property. Admins configure display density in the **Widget setup** tab with three modes: **Responsive** (full label with hover tooltip), **Full Tag** (always expanded), or **Icon Only** (icon with hover-revealed text).

### Data Lineage — tracing propagation

The Data Lineage application provides a <span style="color:#2D72D2">**"Permissions type: Data access in datasets"**</span> filter that overlays marking flow on the pipeline graph, highlighting which nodes carry a given marking and where propagation stops.

## Worked example

**Scenario:** A healthcare analytics team ingests a raw patient dataset marked `PII` and `HIPAA`. They want analysts to work on a de-identified version without those restrictions.

1. An administrator creates the `PII` and `HIPAA` markings under a "Data Sensitivity" category in Platform Settings. Membership is granted only to data stewards.
2. The raw ingest pipeline lands data into `/datasets/raw/patients`. A data steward applies both markings to the folder — all files inside immediately inherit them.
3. A data engineer writes a de-identification transform on a **protected branch**. The output dataset initially inherits `PII` and `HIPAA` via lineage.
4. The engineer adds `stop_propagating(marking="PII", marking="HIPAA")` calls to the transform and opens a pull request. The protected branch requires a **security approval** from a marking Category Administrator before merging.
5. After approval and merge, the transform is rebuilt. The output dataset no longer carries `PII` or `HIPAA`; downstream analyst pipelines can now be accessed by the full analyst group.
6. In Workshop, an analyst building a patient dashboard sees gray classification pills next to any property sourced from an upstream marked dataset — a reminder of provenance even on otherwise-accessible data.

## Documentation map

- **Concepts — Markings** — core model, propagation, conjunctive logic
- **Concepts — Classification-based Access Controls** — CBAC hierarchy, file/data/project classification, project max classification
- **Concepts — Property security markings** — column-level marking display in Workshop
- **Management — Manage markings** — creating categories and markings, applying/removing, `stop_propagating` syntax, protected branches
- **Getting started — Protecting sensitive data** — end-to-end guide for a marking rollout
- **Object and link types — Mandatory control properties** — marking enforcement on Ontology objects
- **Object permissioning — Object security policies** — row/column security layered with markings
- **API Reference — Marking basics** — Admin V2 REST endpoints for programmatic marking management
- **Concepts — Audit logs** — tracking marking-related events and access decisions

## Official documentation

- [Concepts — Markings](https://www.palantir.com/docs/foundry/security/markings)
- [Overview — Security](https://www.palantir.com/docs/foundry/security/overview)
- [Concepts — Classification-based Access Controls](https://www.palantir.com/docs/foundry/security/classification-based-access-controls)
- [Management — Manage markings](https://www.palantir.com/docs/foundry/platform-security-management/manage-markings)
- [Concepts — Property security markings](https://www.palantir.com/docs/foundry/security/property-security-markings)
- [Getting started — Protecting sensitive data](https://www.palantir.com/docs/foundry/security/protecting-sensitive-data)
- [API Reference — Marking basics](https://www.palantir.com/docs/foundry/api/admin-v2-resources/markings/marking-basics)
