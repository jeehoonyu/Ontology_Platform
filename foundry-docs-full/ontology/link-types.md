<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Link Types</b></span><br>
<span style="color:#ABB3BF">The schema definition of a relationship between two object types in the Foundry Ontology.</span>
</td></tr></table>

## What it is

A **link type** is the schema that defines how two object types in the Foundry Ontology are related to one another. A **link** is a single instance of that relationship — one concrete pairing of two objects. Link types are analogous to the join condition between two datasets, while links are analogous to individual joined rows. Links can connect two different object types or an object type to itself, but cross-Ontology links (between object types in different Ontologies) are not supported.

## How it works

Link types are configured in the **Ontology Manager** and are backed by one or more datasources that supply the actual relationship data at runtime. The full mechanical lifecycle is:

1. **Schema declaration.** A link type is created by defining two endpoints (the left and right object types), the cardinality of each side, and display/API names for each traversal direction. This schema record is stored as an Ontology resource and assigned a stable RID.

2. **Cardinality selection.** Three relationship type strategies are available, each mapping to a different backing mechanism:
   - **Object type foreign keys** — used for one-to-one or many-to-one relationships. A property on one object type (the foreign key) is mapped to the primary key of the other object type. No separate join dataset is needed; the mapping lives in the link type's metadata.
   - **Join table dataset** — used for many-to-many relationships. A Foundry dataset containing both primary keys acts as the backing source. Each row in the dataset produces one link instance at query time.
   - **Backing object type** — an advanced many-to-one variant where an intermediary object type stores the link plus additional metadata properties. Each endpoint object type holds a many-to-one link to the intermediary, enabling link-level attributes.

3. **Datasource attachment.** For foreign-key links the datasource is the backing dataset already attached to the object types. For join-table links the join dataset is explicitly added to the link type's **Datasources** page in Ontology Manager. Without a datasource, the link type schema exists but produces zero live links.

4. **Writeback configuration (optional).** To allow users to create or delete links through Foundry applications, a **writeback dataset** is generated from the Datasources page. The writeback dataset stores user-authored link instances separately from the source dataset. Users need Edit permission on the writeback dataset; read-only users see only the source-backed links.

5. **Runtime resolution.** When a downstream consumer (Object Explorer, Workshop app, AIP agent, or the Ontology SDK) queries an object, Foundry's Ontology runtime resolves link types on demand. For each object it traverses the link type's key mapping or join table, filters to matching rows, and returns the linked object instances — with all property values hydrated from those objects' own backing datasets.

6. **Metadata and governance.** Each link type carries a lifecycle **status** (`active`, `experimental`, or `deprecated`) and optional **type classes** that downstream applications interpret for display hints. **Visibility** per side (`prominent`, `normal`, `hidden`) controls how prominently each traversal direction surfaces in UI components. Permissions are inherited from the project in which the link type is saved, or can be set independently under legacy permission models.

7. **API surface.** Link types are addressable by their **API name** (camelCase, unique per object type, 1–100 characters). The Ontology SDK, REST API (Ontologies V2), and Functions/TypeScript code all reference link types by this API name to traverse relationships programmatically.

## User interface

Link types are managed entirely within **Ontology Manager**, a dedicated Foundry application.

**Overall layout.** Ontology Manager has a persistent <span style="color:#8ABBFF">top bar</span> for global search, branch management, and the **New** resource button, plus a <span style="color:#8ABBFF">left sidebar</span> listing resource categories: Object Types, Link Types, Action Types, Functions, Interfaces, and Shared Properties.

**Entering the Link Types area.** Navigate to <span style="color:#2D72D2">Resources → Link Types</span> in the sidebar to see a flat list of all link types in the Ontology. Each row shows the link type display name, the two connected object types, and its current status chip.

**Link type detail view.** Clicking a link type (or selecting one from an object type's link graph on the Overview tab) opens a two-tab view:

- <span style="color:#2D72D2">**Overview tab**</span> — shows identity metadata (RID, API name, status), the two endpoint object types with cardinality labels, and display/visibility settings for each traversal direction.
- <span style="color:#2D72D2">**Datasources tab**</span> — lists attached backing datasources, the column-to-key mappings, and the Writeback dataset section with a **Generate** button.

**Creating a link type.** The <span style="color:#2D72D2">**New → Link type**</span> button (top-right) opens a five-step creation helper:

| Step | What you configure |
|------|-------------------|
| 1 | Relationship type: foreign key / join table / backing object |
| 2 | Endpoint object types, key mappings or join dataset |
| 3 | Display names and API names for each direction |
| 4 | Save location (project) |
| 5 | Confirm — then **Save** in Ontology Manager |

**Status chips used across the UI:**

<span style="color:#238551"><b>● active</b></span> · <span style="color:#C87619"><b>● experimental</b></span> · <span style="color:#CD4246"><b>● deprecated</b></span> · <span style="color:#2D72D2"><b>● primary action</b></span>

**Permissions banner.** When a user lacks edit access to a link type or either of its endpoint object types, all edit fields are disabled and a banner explains the missing permissions. Editing requires holding edit rights on the link type's project and view rights on both referenced object types.

<table>
<tr style="background:#1C2127;color:#ABB3BF">
<td style="padding:8px 12px;border:1px solid #383E47"><b style="color:#FFFFFF">UI element</b></td>
<td style="padding:8px 12px;border:1px solid #383E47"><b style="color:#FFFFFF">Where it lives</b></td>
<td style="padding:8px 12px;border:1px solid #383E47"><b style="color:#FFFFFF">Key action</b></td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Link type list</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Sidebar → Link Types</td>
<td style="padding:8px 12px;border:1px solid #383E47">Browse and search all link types</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Link graph</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Object type → Overview tab</td>
<td style="padding:8px 12px;border:1px solid #383E47">Visual map of all link types for one object type</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Overview tab</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Link type detail view</td>
<td style="padding:8px 12px;border:1px solid #383E47">Edit metadata, names, visibility, status</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Datasources tab</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Link type detail view</td>
<td style="padding:8px 12px;border:1px solid #383E47">Attach join datasets, generate writeback dataset</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">New → Link type</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Top bar</td>
<td style="padding:8px 12px;border:1px solid #383E47">Launch 5-step creation wizard</td>
</tr>
</table>

## Worked example

**Scenario: Flight → Aircraft assignment (many-to-one)**

1. Two object types already exist: `Flight` (primary key: `flight_id`) and `Aircraft` (primary key: `tail_number`).
2. The `Flight` dataset contains a column `assigned_tail_number` — a foreign key pointing to `Aircraft`.
3. In Ontology Manager, click **New → Link type**. Select **Object type foreign keys** as the relationship type.
4. Set the left object type to `Flight` (cardinality: many) and the right to `Aircraft` (cardinality: one). Map `Flight.assigned_tail_number → Aircraft.tail_number`.
5. Name the directions: left-to-right = `assignedAircraft` (display: "Assigned Aircraft"), right-to-left = `scheduledFlights` (display: "Scheduled Flights").
6. Save to the `Airline Ops` project and click **Save** in Ontology Manager. Status is set to `experimental` initially.
7. In Object Explorer, opening the flight record "JFK → SFO 24-02-2021" now shows a **Assigned Aircraft** panel with the linked Boeing 737-123 object and all its properties.
8. To allow dispatchers to reassign aircraft: open the Datasources tab, click **Generate** under Writeback dataset, save the writeback dataset to a writeback project, and grant dispatchers Edit access on that dataset.

## Documentation map

- **Object and link types — Link types**
  - Overview (this tool)
  - Create a link type
  - Link type metadata reference
  - Allow users to edit objects and links
- **Object and link types — Object types**
  - Overview
  - Properties overview
  - Edit-only properties
  - Shared properties (Beta)
- **Ontology**
  - Overview
  - Core concepts
- **Ontology Manager**
  - Overview
  - Migrate to project-based permissions
  - Ontology roles migration (Legacy)
- **API Reference**
  - Ontology basics (Ontologies V2)
  - Ontology SDK — Permissions

## Official documentation

- [Link Types — Overview](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview)
- [Create a Link Type](https://www.palantir.com/docs/foundry/object-link-types/create-link-type)
- [Link Type Metadata Reference](https://www.palantir.com/docs/foundry/object-link-types/link-type-metadata)
- [Allow Users to Edit Objects and Links](https://www.palantir.com/docs/foundry/object-link-types/allow-editing)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology — Core Concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Ontology Manager — Overview](https://www.palantir.com/docs/foundry/ontology-manager/overview)
- [Object and Link Types — Types Reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)
