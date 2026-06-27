<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Object Types</b></span><br>
<span style="color:#ABB3BF">The schema definition of a real-world entity or event, backed by a Foundry datasource, that forms the atomic unit of the Ontology.</span>
</td></tr></table>

## What it is

An **Object Type** is the template — analogous to a database table schema — that defines what a real-world entity looks like inside Foundry's Ontology. A single row in the backing datasource becomes one **object** (e.g., a specific employee "Melissa Chang"), while a filtered collection of rows becomes an **object set** (e.g., "all tenured employees"). Object Types are the foundation on which properties, link types, action types, interfaces, and downstream applications are all built.

## How it works

Object Types live inside the **Ontology Metadata Service (OMS)**, which stores the structural definition (schema), while actual indexed data is stored and queried by the **Object Storage** layer. The end-to-end pipeline from raw data to a queryable object follows these steps:

1. **Register a backing datasource.** An Object Type must point to at least one Foundry resource — typically a dataset (Pipeline Builder output, a Contour save, a CSV upload) or a restricted view. In Object Storage V2 an object type may span multiple datasources, with property-level permissions per source.

2. **Define properties.** Each column in the datasource is mapped to a **property** — a named, typed characteristic of the entity. Properties have an API name (camelCase, e.g., `employeeId`), a display name, a value type (string, integer, timestamp, boolean, geo-point, array, struct, media reference, etc.), and optional metadata such as description and value-type constraints. Up to 2,000 properties are supported in Object Storage V2.

3. **Set the primary key.** One or more properties are designated as the **primary key** — the set of values that uniquely identifies each object. Duplicate primary-key values cause Funnel pipeline failures in V2 and undefined behavior in V1. Keys must be deterministic; changing them can break links and lose user edits.

4. **Set the title key.** A separate property is designated as the **title key** — the human-readable display name surfaced in Object Views, Workshop, and search results.

5. **Assign an API name.** The object type receives a PascalCase API name (e.g., `EmployeeRecord`, 1–100 chars, alphanumeric only) used by Functions, Action Types, the REST API, and TypeScript/Python SDKs. Reserved keywords (`ontology`, `object`, `rid`, etc.) are disallowed.

6. **Materialize via the Object Data Funnel.** On save, the **Object Data Funnel** microservice reads the registered datasource, applies any user edits already in the system, and writes indexed data into the **Object Database** (Object Storage V2, formerly Phonograph). Indexing is incremental in V2 — only changed rows are re-processed, enabling billions of objects and streaming datasource support.

7. **Query via Object Set Service (OSS).** Consumer applications (Object Views, Workshop, Quiver, OSDK apps, the REST API) submit read requests to the **Object Set Service**, which searches, filters, aggregates, and loads objects from the Object Database without touching the raw datasource.

8. **Write-back via Actions Service.** When a user submits an Action Type, the **Actions Service** validates permissions, applies structured edits to the object databases with full audit logging, and propagates changes back upstream if configured.

Object Storage V1 (Phonograph) consolidated indexing, storage, and querying in a single service and is scheduled for deprecation on June 30, 2026. Object Storage V2 decouples these responsibilities for horizontal scaling, lower latency, and multi-datasource support.

## User interface

The **Ontology Manager** (`/workspace/ontology`) is the primary tool for authoring Object Types. It is accessible from the Workspace sidebar Apps section, from Data Lineage right-click, or by direct URL.

### Overall layout

<table style="border-collapse:collapse;background:#1C2127;color:#fff;width:100%;font-size:14px">
<tr style="background:#252A31">
  <th style="padding:8px 12px;border:1px solid #383E47;color:#8ABBFF">Area</th>
  <th style="padding:8px 12px;border:1px solid #383E47;color:#8ABBFF">Description</th>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Top bar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Global search across Ontology resources, <b>+ New</b> dropdown for creating object/link/action types, and branch selector for staging changes before publishing.</td>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Left sidebar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Navigation between the Discover view (favorites, recents, groups) and individual resource pages (object types, link types, action types, interfaces, value types).</td>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Discover view</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Customizable landing page showing pinned favorites, recently modified items, and group sections. New users see recently modified and prominent types.</td>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Object Type view</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Per-type panel with a sub-sidebar (Overview, Datasources, etc.) and a main editing surface. The Overview page shows metadata, properties list, action types, link type graph, dependents, data info, and usage metrics.</td>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Property editor</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">A dedicated panel opened by clicking a property in the Overview. Shows column mapping, data type, API name, display name/description tabs, primary/title key toggles, and struct field configuration.</td>
</tr>
</table>

### Creation wizard

The **guided helper** (launched via <span style="color:#2D72D2">**New > Create object type**</span>) walks through five screens in sequence: (1) select or create a backing datasource, (2) set icon/color/display name/description/group, (3) map columns to properties, (4) assign primary and title keys, (5) optionally generate standard edit actions and assign permissions, then choose a project location and click <span style="color:#238551">**Create**</span>. Changes are staged — not yet live — until explicitly published.

### Status indicators

<span style="color:#238551"><b>● Published</b></span> — Object type is live in the Ontology and queryable.
<span style="color:#C87619"><b>● Staged / Pending</b></span> — Changes saved locally but not yet published to the branch.
<span style="color:#CD4246"><b>● Pipeline failure</b></span> — Funnel encountered duplicate primary keys or datasource errors; objects are stale.
<span style="color:#2D72D2"><b>● Primary action</b></span> — Save, Publish, Add property buttons.

## Worked example

**Scenario: Modeling an `Employee` object type backed by an HR pipeline dataset.**

1. In Ontology Manager, click <span style="color:#2D72D2">**New > Create object type**</span> to open the guided helper.
2. Select the Pipeline Builder output dataset `/HR/clean/employees` as the backing datasource.
3. Set display name to `Employee` (singular) / `Employees` (plural), choose a person icon and a teal color (`#00A396`), and add a description: "Represents a current or former employee."
4. In the properties screen, map columns: `employee_id` → property `employeeId` (integer), `full_name` → `fullName` (string), `department` → `department` (string), `hire_date` → `hireDate` (timestamp), `tenure_years` → `tenureYears` (double).
5. Designate `employeeId` as the **primary key** (guaranteed unique per row) and `fullName` as the **title key**.
6. Accept API name `Employee` (auto-generated PascalCase). Optionally generate an `EditEmployee` action type.
7. Save to the branch; the Object Data Funnel picks up the datasource, indexes all rows into Object Storage V2, and marks the type <span style="color:#238551"><b>● Published</b></span>.
8. In Workshop or Object Views, a search for "Melissa Chang" now resolves instantly via OSS, displaying all five properties and any configured linked types (e.g., linked `Department` objects via a `worksIn` link type).

## Documentation map

The Object Types topic spans the following sub-pages in the Foundry docs:

- **Ontology > Overview** — What the Ontology is; semantic + kinetic elements
- **Ontology > Core concepts** — Object types, properties, link types, action types, interfaces, roles, functions
- **Ontology > Best practices and anti-patterns** — Design guidance
- **Object and link types > Types reference** — Definitions of all Ontology type primitives and data/value types
- **Object and link types > Object types > Create an object type** — Guided helper and manual creation steps
- **Object and link types > Object types > Edit object types** — Modifying existing object types post-creation
- **Object and link types > Properties > Edit object type properties** — Property editor walkthrough, struct types, shared properties
- **Object and link types > Link types > Create a link type** — Linking object types with cardinality rules
- **Ontology architecture** — OMS, Object Data Funnel, OSS, Object Storage V1 vs V2
- **Ontology Manager > Overview** — UI navigation, Discover view, branch management
- **Time series > Sensor object types use case** — Specialized object type backed by time-series data
- **SQL in Foundry > Ontology SQL** — Querying object types via SQL interface

## Official documentation

- [Object Types Overview](https://www.palantir.com/docs/foundry/object-link-types/object-types-overview)
- [Ontology Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology Core Concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Object and Link Types — Types Reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)
- [Create an Object Type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type)
- [Edit Object Types](https://www.palantir.com/docs/foundry/object-link-types/edit-object-type/index.html)
- [Edit Object Type Properties](https://www.palantir.com/docs/foundry/object-link-types/edit-properties)
- [Ontology Manager UI Overview](https://www.palantir.com/docs/foundry/ontology-manager/overview)
- [Ontology Architecture (Object Backend)](https://www.palantir.com/docs/foundry/object-backend/overview)
- [Ontology Best Practices and Anti-patterns](https://www.palantir.com/docs/foundry/ontology/ontology-best-practices-and-anti-patterns)
