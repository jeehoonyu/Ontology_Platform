<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Properties &amp; Shared Property Types</b></span><br>
<span style="color:#ABB3BF">The schema building blocks that define the typed, named characteristics of every object in the Ontology.</span>
</td></tr></table>

## What it is

A **property** is the schema definition of a single characteristic of a real-world entity or event modeled as an object type. Just as a database column defines what data a table can hold, a property defines what data an object type can carry — its name, data type, display rules, and role in the object's identity. A **Shared Property Type** is a reusable property definition that can be attached to multiple object types, ensuring identical metadata and consistent behavior across the entire Ontology from one managed location.

## How it works

### 1. Properties as schema columns

Every object type is backed by one or more datasets (datasources) in Foundry. Each column in those backing datasets maps to a property on the object type. The **property definition** lives in Ontology Manager and describes the column contract: its base type, display name, API name, and constraints. The **property value** is the actual datum stored per object instance.

### 2. Base types determine the data contract

When you define a property you choose a **base type** that pins the kind of value the property can hold and which operations (search, sort, aggregate, filter) are available to user applications and the Object Storage indexing layer (Phonograph/Object Storage V1). The full set of supported base types is:

| Category | Types | Can be Primary Key | Notes |
|---|---|---|---|
| Common | `String`, `Integer`, `Short` | Yes | Preferred for primary keys |
| Temporal | `Date`, `Timestamp` | Discouraged | Collision risk as primary keys |
| Numeric | `Boolean`, `Byte`, `Long`, `Float`, `Double`, `Decimal` | No | `Long` has JS precision limits above 1e15 |
| Complex | `Array`, `Struct` | No | Arrays support all inner types except `Vector`/`Time series` |
| Specialized | `Geopoint`, `Geoshape`, `Vector`, `Time series`, `Attachment`, `Media Reference`, `Cipher Text` | No | Domain-specific; `Vector` supports only KNN queries, max 2048 dimensions |

All base types except `Map` and `Binary` are valid. `Byte`, `Decimal`, `Float`, `Short`, and `Vector` cannot be used in Action types.

### 3. Property metadata fields

Each property carries a rich metadata envelope that governs how applications read and render it:

- **ID** — programmatic slug (e.g. `start-date`), immutable after creation.
- **Display name** — user-facing label shown in applications.
- **API name** — camelCase identifier used in code and Functions (e.g. `startDate`).
- **RID** — auto-generated resource identifier; used in error messages and cross-service references.
- **Status** — `active`, `experimental`, or `deprecated`; downstream apps can respect deprecation markers.
- **Keys** — designates the property as **title key** (the human-readable display name of the object) and/or **primary key** (the unique identifier used for deduplication and linking).
- **Base type** + **Value formatting** — controls how raw values are transformed for display (numeric formats, date patterns, user-ID resolution, resource-ID resolution).
- **Conditional formatting** — rules that change how a value renders based on its content.
- **Visibility** — `prominent` (surfaced first in apps), `normal`, or `hidden`.
- **Type classes** — arbitrary metadata tags interpreted by applications; merged from both the property and any associated shared property.
- **Render hints** — flags like `searchable` and `sortable` that instruct Object Storage V1 on whether to index a property for aggregation or sort operations, directly affecting reindex performance.

### 4. Shared Property Types — reuse and centralization

A Shared Property Type is a named, standalone property definition stored at the Ontology level rather than inside a single object type. When an object type's property is **linked** to a shared property:

1. The property's metadata (name, description, base type, value formatting, visibility, render hints) is **inherited** from the shared property.
2. Direct edits to inherited metadata fields on the object-type property are **disabled** — changes must be made on the shared property and propagate automatically to all linked object types.
3. Type classes are **merged**: the combined set from both the local property and the shared property is applied at runtime.
4. If the shared property specifies **render hints**, those override the object-type-level settings.
5. The property's **ID and API name are preserved** when converting an existing property into a shared property, protecting downstream code.

Shared properties are created either from scratch in Ontology Manager or by converting an existing property. They can be detached at any time — the detach operation severs the link but keeps the property intact on the object type.

### 5. End-to-end data flow

```
Backing dataset column
        │  (datasource mapping in Ontology Manager)
        ▼
Property definition  ──────────────────────────────┐
  (base type, metadata, render hints)               │ if shared property
        │                                           ▼
        │                             Shared Property Type
        │                             (centralized metadata)
        ▼
Object Storage V1 (Phonograph) index
  (indexed per render hints: searchable / sortable)
        │
        ▼
User applications (Workshop, Slate, AIP, etc.)
  — reads display name, formatting, visibility, type classes
  — queries via OSDK / Ontology SDK using API name
```

## User interface

Properties are managed inside <span style="color:#8ABBFF"><b>Ontology Manager</b></span>, accessible from the Foundry navigation bar. The layout is a three-panel workspace:

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
<td style="padding:10px 14px;color:#8ABBFF;font-weight:bold;width:22%">Panel / Element</td>
<td style="padding:10px 14px;color:#ABB3BF">What you see &amp; do</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><b>Left sidebar</b></td>
<td style="padding:8px 14px;color:#ABB3BF">Object type list; <span style="color:#2D72D2">Shared Properties</span> section appears below object types. A <span style="color:#ABB3BF">globe icon &#127760;</span> marks any property linked to a shared property type.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><b>Properties tab</b></td>
<td style="padding:8px 14px;color:#ABB3BF">Table of all properties on the selected object type — columns for display name, API name, base type, and status chip: <span style="color:#238551"><b>● active</b></span> · <span style="color:#C87619"><b>● experimental</b></span> · <span style="color:#CD4246"><b>● deprecated</b></span></td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><b>Property detail panel</b></td>
<td style="padding:8px 14px;color:#ABB3BF">Right-side slide-out; shows all metadata fields as editable form inputs. Inherited fields from a shared property appear <span style="color:#ABB3BF">greyed out</span> with a lock indicator. The <span style="color:#2D72D2"><b>Shared Property</b></span> section contains a dropdown to link/create a shared property and a <span style="color:#CD4246"><b>Detach</b></span> button.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><b>Render hints checklist</b></td>
<td style="padding:8px 14px;color:#ABB3BF">Supplied checklist of flags (e.g. <code>searchable</code>, <code>sortable</code>) within the property detail panel. Changing these triggers a reindex warning banner.</td>
</tr>
<tr>
<td style="padding:8px 14px;color:#fff"><b>Save button</b></td>
<td style="padding:8px 14px;color:#ABB3BF"><span style="color:#2D72D2"><b>● Save</b></span> appears in the upper-right corner; must be clicked explicitly — changes are not auto-saved.</td>
</tr>
</table>

When viewing a **Shared Property** in the left sidebar panel, the <span style="color:#ABB3BF">**Usage**</span> section lists every object type currently linked to it, giving a cross-ontology impact view before making changes.

## Worked example

**Scenario:** An organization models both `Employee` and `Contractor` object types. Both have a `start date` column in their backing datasets.

1. In Ontology Manager, open the `Employee` object type and select the `start_date` property.
2. In the property detail panel, open the **Shared Property** dropdown and select **Create new shared property**. Name it `Start Date`, set base type `Date`, visibility `prominent`, and render hints `searchable`.
3. Click **Save**. The `start_date` property on `Employee` now inherits all metadata from the `Start Date` shared property. The globe icon appears next to it.
4. Open the `Contractor` object type and select its `start_date` property. In the **Shared Property** dropdown, select the existing `Start Date` shared property. Click **Save**.
5. Both object types now share identical `Start Date` metadata. Navigating to **Shared Properties > Start Date** in the sidebar shows both `Employee` and `Contractor` in the Usage section.
6. To update the display format for all uses at once, edit the shared property's **Value formatting** field — both object types reflect the change immediately without touching each one individually.

## Documentation map

- **Properties**
  - [Properties overview](https://www.palantir.com/docs/foundry/object-link-types/properties-overview)
  - [Base types](https://www.palantir.com/docs/foundry/object-link-types/base-types)
  - [Property metadata reference](https://www.palantir.com/docs/foundry/object-link-types/property-metadata)
  - [Edit object type properties](https://www.palantir.com/docs/foundry/object-link-types/edit-properties)
- **Shared Property Types**
  - [Shared properties overview](https://www.palantir.com/docs/foundry/object-link-types/shared-property-overview)
  - [Create shared properties](https://www.palantir.com/docs/foundry/object-link-types/create-shared-property)
  - [Use shared properties on object types](https://www.palantir.com/docs/foundry/object-link-types/use-shared-property)
  - [Edit shared properties](https://www.palantir.com/docs/foundry/object-link-types/edit-shared-property)
  - [Shared property metadata reference](https://www.palantir.com/docs/foundry/object-link-types/shared-property-metadata)
  - [Structs and shared properties](https://www.palantir.com/docs/foundry/object-link-types/struct-shared-properties)
- **Metadata sub-pages**
  - [Render hints](https://www.palantir.com/docs/foundry/object-link-types/metadata-render-hints)
  - [Type classes](https://www.palantir.com/docs/foundry/object-link-types/metadata-typeclasses)
  - [Types reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)

## Official documentation

- [Properties overview](https://www.palantir.com/docs/foundry/object-link-types/properties-overview)
- [Base types](https://www.palantir.com/docs/foundry/object-link-types/base-types)
- [Shared properties overview](https://www.palantir.com/docs/foundry/object-link-types/shared-property-overview)
- [Property metadata reference](https://www.palantir.com/docs/foundry/object-link-types/property-metadata)
- [Shared property metadata reference](https://www.palantir.com/docs/foundry/object-link-types/shared-property-metadata)
- [Use shared properties on object types](https://www.palantir.com/docs/foundry/object-link-types/use-shared-property)
- [Render hints](https://www.palantir.com/docs/foundry/object-link-types/metadata-render-hints)
