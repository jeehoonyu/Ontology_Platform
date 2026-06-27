<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Ontology Manager</b></span><br>
<span style="color:#ABB3BF">The central application for constructing, configuring, and maintaining a Foundry Ontology — mapping raw datasets to typed real-world objects, relationships, and actions.</span>
</td></tr></table>

## What it is

**Ontology Manager** (often abbreviated OMA) is the first-class Foundry application in which teams design and govern their organizational Ontology. It is the place where engineers and data modelers translate raw datasets and virtual tables into semantically rich **object types**, **link types**, **action types**, **functions**, and **interfaces** — the five building blocks that power every downstream Foundry application, AIP agent, and automated workflow. Once published, these definitions are consumed at runtime by the Ontology Engine, which handles high-scale SQL queries, real-time state subscriptions, and write-backs to operational systems.

## How it works

The Ontology is Foundry's **operational semantic layer** — not a copy of data, but a live schema bound to underlying datasets. Ontology Manager is the authoring surface for that schema. The mechanics follow a clear layered model:

### 1. Datasource Binding

Every object type must be backed by one or more Foundry datasources (datasets, virtual tables, or data connections). When a datasource is attached, the Ontology Engine reads the datasource schema and surfaces its columns as candidate properties. No data is duplicated: objects are materialised on read by querying the backing datasource through the Engine.

### 2. Schema Definition

Inside OMA the modeler configures the object type's schema:

- **Primary key** — one property designated as the unique identifier for each object instance.
- **Title property** — the human-readable display name shown in applications.
- **Properties** — each maps to a datasource column; supports types (string, boolean, timestamp, geo-shape, etc.), formatting rules, and derived/computed values. **Shared properties** can be declared once and reused across multiple object types, ensuring consistent semantics.
- **Link types** — relationship schemas between two object types, analogous to joins. Cardinality (one-to-many, many-to-many, self-referential) is declared at definition time. Many-to-many links require their own backing datasource; one-to-many links derive from the related object types' datasources. **Cross-Ontology links are not supported** — cross-boundary relationships use shared Ontologies instead.

### 3. Kinetic Layer: Action Types and Functions

Static schema is extended with *kinetics* — the mechanisms for mutating state:

- **Action types** define a set of changes (create, edit, or delete objects; modify property values; add or remove links) that a user or agent can execute as a single atomic operation. Each action type has a **Logic** tab where parameters are declared and effects are wired to target properties and links.
- **Functions** are code-backed units of reusable business logic (TypeScript/Python) that accept objects or object sets as input. They integrate into action types, Workshop applications, and AIP agents. The Function Type View in OMA provides version selection, usage history, and code repository access.

### 4. Interfaces (Polymorphism)

Interfaces define a contractual shape — a named set of shared properties and link declarations — that multiple object types can implement. This enables polymorphic queries: downstream applications can operate on "any object that implements the `Asset` interface" without knowing the concrete type, allowing flexible modeling of heterogeneous domains.

### 5. Publish and Runtime

After editing, changes can be saved on a **branch** before being merged to production, allowing safe iterative development. Once published, the Ontology Engine exposes objects via:

- High-scale SQL-style reads (object search, filtering, aggregation)
- Real-time subscription to state changes (used by Workshop live-update and AIP)
- Write operations from action type executions, which are written back to the backing datasource (or an action-specific write dataset), creating a continuous loop between operational systems and the semantic layer

Security is applied at every layer: roles grant access at the Ontology level or per-resource, with row- and column-level restrictions reconciling thousands of users and automated agents.

### Data flow summary

```
Enterprise datasets / CRMs / ERPs
        ↓  (datasource binding in OMA)
Object types + Link types + Properties
        ↓  (Ontology Engine — read path)
Object Explorer · Workshop · AIP Agents · Ontology SDK
        ↓  (action type execution — write path)
Write-back datasets → upstream operational systems
```

## User interface

Ontology Manager is accessed from the Foundry Workspace sidebar (Apps section) or by navigating to `/workspace/ontology`.

### Overall layout

| Region | Description |
|---|---|
| <span style="color:#8ABBFF"><b>Top bar</b></span> | Global search for any ontology resource; branch selector; create-new button |
| <span style="color:#8ABBFF"><b>Left sidebar</b></span> | Navigation between Discover, object types, link types, action types, function types |
| <span style="color:#8ABBFF"><b>Main canvas</b></span> | Context-dependent detail view for the selected resource |

### Key screens

**Discover view** — The landing page. Displays <span style="color:#2D72D2"><b>Favorites</b></span>, <span style="color:#2D72D2"><b>Recently viewed</b></span>, and prominent/recently modified types. Configurable: users choose which sections appear and how many items each shows.

**Object Type view** — The primary authoring screen. Selecting an object type opens a sidebar of sub-pages:

- <span style="color:#2D72D2"><b>Overview</b></span> — metadata, property summary, action type list, link type graph, dependents, and usage metrics
- <span style="color:#2D72D2"><b>Properties</b></span> — table of all properties; clicking one opens the **Property Editor** panel for type, formatting, and derivation configuration
- <span style="color:#2D72D2"><b>Datasources</b></span> — attached backing datasets and column-to-property mapping

**Link Type view** — Accessed by clicking a link in the object type's link graph. Shows Overview and Datasources pages.

**Action Type view** — Three tabs:
- <span style="color:#2D72D2"><b>Overview</b></span> — parameters, effects summary, linked object types
- <span style="color:#2D72D2"><b>Logic</b></span> — wires parameters to property edits, object creation/deletion, and link mutations
- <span style="color:#2D72D2"><b>Observability</b></span> — 30-day usage metrics and configured monitoring rules

**Function Type view** — Overview, Configuration (version selection, input/output types), and Observability (usage history, monitoring rules, code repository link).

### Status indicators

<span style="background:#1C2127;padding:4px 8px;border-radius:4px"><span style="color:#238551"><b>● Published</b></span></span> &nbsp; <span style="background:#1C2127;padding:4px 8px;border-radius:4px"><span style="color:#C87619"><b>● Draft / Pending</b></span></span> &nbsp; <span style="background:#1C2127;padding:4px 8px;border-radius:4px"><span style="color:#CD4246"><b>● Error / Conflict</b></span></span> &nbsp; <span style="background:#1C2127;padding:4px 8px;border-radius:4px"><span style="color:#2D72D2"><b>● Primary action</b></span></span>

### What you see — at a glance

<table style="background:#1C2127;color:#fff;border:1px solid #383E47;border-radius:6px;padding:0;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 14px;color:#ABB3BF;font-size:12px">ELEMENT</td>
  <td style="padding:8px 14px;color:#ABB3BF;font-size:12px">APPEARANCE / INTERACTION</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 14px"><span style="color:#8ABBFF">Object type card</span></td>
  <td style="padding:8px 14px">Icon + name + property count + datasource badge; click to open</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 14px"><span style="color:#8ABBFF">Link graph</span></td>
  <td style="padding:8px 14px">Force-directed diagram of connected types; click edge to open Link Type view</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 14px"><span style="color:#8ABBFF">Property Editor</span></td>
  <td style="padding:8px 14px">Right-side panel; type picker, display name, derived formula, security tags</td>
</tr>
<tr>
  <td style="padding:8px 14px"><span style="color:#8ABBFF">Branch selector</span></td>
  <td style="padding:8px 14px">Top-bar dropdown; create feature branch, merge to production</td>
</tr>
</table>

## Worked example

**Goal:** model an `Employee` entity from an HR dataset and link it to a `Department` type.

1. In OMA, click <span style="color:#2D72D2"><b>+ New object type</b></span> and name it `Employee`.
2. On the Datasources sub-page, attach the `hr_employees` dataset. OMA reads its schema and lists all columns as candidate properties.
3. Designate `employee_id` as the **primary key** and `full_name` as the **title property**.
4. Map additional columns — `start_date` (timestamp), `is_active` (boolean), `department_id` (string) — as properties. Mark `department_id` as a shared property if it is also used in other object types.
5. Switch to the `Department` object type (or create it similarly from a `hr_departments` dataset).
6. On either type's **Overview**, open the link type graph and click <span style="color:#2D72D2"><b>+ Add link type</b></span>. Define the relationship: `Employee` ↔ `Department`, cardinality one-to-many, backed by the foreign-key relationship between `department_id` columns.
7. Create an <span style="color:#2D72D2"><b>Action type</b></span> named `Transfer Employee`. In the **Logic** tab, declare a parameter `new_department` (object of type `Department`) and an effect that sets the `department_id` property on the target `Employee` object.
8. Merge the branch to production. The `Employee` and `Department` types, their link, and the `Transfer Employee` action are now live — queryable through Object Explorer, embeddable in Workshop, and callable by AIP agents.

## Documentation map

Sub-pages and sections available beneath Ontology Manager and the Ontology building documentation:

- **Ontology Manager / Overview** — application entry points, sidebar, Discover view
- **Object and link types / Object types — Overview** — object type vs. object vs. object set
- **Object and link types / Create an object type** — step-by-step creation walkthrough
- **Object and link types / Properties — Overview** — property types, shared properties, derivation
- **Object and link types / Link types — Overview** — cardinality, datasource backing, cross-Ontology limits
- **Object and link types / Create a link type** — configuration guide
- **Ontology / Core concepts** — authoritative definitions of all five building blocks
- **Ontology / Why create an Ontology?** — business rationale and use-case framing
- **Ontology / Ontology design: Best practices and anti-patterns**
- **Architecture Center / The Ontology system** — Engine, Language, Toolchain pillars
- **Action types / Logic configuration** — parameter declaration, effects, write-back targets
- **Functions** — language support, integration with action types and AIP
- **Interfaces** — declaring interface shapes, implementing on object types

## Official documentation

- [Ontology Manager — Overview](https://www.palantir.com/docs/foundry/ontology-manager/overview)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology — Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Object and link types — Object types: Overview](https://www.palantir.com/docs/foundry/object-link-types/object-types-overview)
- [Object and link types — Link types: Overview](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview)
- [Architecture Center — The Ontology system](https://www.palantir.com/docs/foundry/architecture-center/ontology-system)
