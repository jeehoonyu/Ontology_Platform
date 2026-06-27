<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Interfaces</b></span><br>
<span style="color:#ABB3BF">Abstract Ontology types that define a shared shape and capabilities contract for multiple object types, enabling polymorphic access across the Ontology.</span>
</td></tr></table>

## What it is

An **Interface** is an abstract Ontology type in Palantir Foundry that describes the structure (properties and link type constraints) that a set of concrete object types agree to implement. Interfaces are not backed by any dataset and cannot be instantiated directly — they exist solely as a schema contract. Their primary purpose is **object type polymorphism**: once several object types implement the same interface, application code and API queries can interact with all of them uniformly without knowing which specific type they are handling at runtime.

## How it works

### Building blocks

An interface is composed of three elements:

1. **Interface properties** — typed property definitions declared either locally on the interface (recommended) or sourced from shared properties in the Ontology catalog. Each property is flagged as **required** (implementing object types _must_ map a concrete property to it) or **optional** (the mapping may be omitted, which is useful for iterative Marketplace development).
2. **Link type constraints** — declarations that implementing object types must expose certain link types. These constraints define the relational shape the interface promises at the API layer.
3. **Metadata** — a display name, an API name (used in SDK and REST calls), an optional description, and an icon.

### Inheritance via extension

An interface can **extend** one or more other interfaces. The child interface inherits all properties and link type constraints from its parents. This layered composition pattern lets teams build a hierarchy — e.g., a generic `Asset` interface extended by a `Facility` interface, which is then extended by `InspectableFacility`. Multi-level and multiple-parent extension are both supported.

### End-to-end mechanics

**Design time (Ontology Manager):**

1. A modeler creates an interface, names it, and adds interface properties (local or shared). For each property a base type (string, integer, timestamp, etc.) is chosen, and required/optional status is set.
2. Optionally, the modeler adds link type constraints requiring implementors to expose certain link types.
3. The modeler optionally extends existing interfaces to inherit their properties.
4. Changes are staged in Ontology Manager; the **Save** button in the upper-right corner commits them to the Ontology.

**Implementation (connecting concrete object types):**

5. A modeler navigates to an object type's **Interfaces** tab and selects "Implement new interface." Alternatively they start from the interface overview and choose the object type.
6. The modeler maps each _required_ interface property to an existing property on the object type. Optional properties may be left unmapped.
7. If the interface declares required link type constraints, the modeler maps them to existing link types on the object type or creates new ones. (Pipeline Builder auto-maps shared properties but does not support link type constraint mapping — Ontology Manager is required for that step.)
8. Changes are saved. The object type now _implements_ the interface.

**Runtime (queries and SDK):**

9. Object Set Service searches against an interface return matching objects from _all_ implementing object types simultaneously, regardless of their concrete types.
10. Objects can be accessed via both their local API names and the interface API names for properties and links, enabling truly polymorphic code paths.
11. TypeScript v2 Functions and the Ontology SDK (TypeScript) fully support interface-based queries. Actions and the Object Set Service have partial support. Workshop and TypeScript v1/Python Functions do not yet support interfaces natively.

## User interface

Interfaces are authored and managed in **Ontology Manager**, the same application used for object types and link types.

### Overall layout

<span style="color:#8ABBFF">**Ontology Manager**</span> opens with a left-hand navigation panel listing the Ontology's resource categories. <span style="color:#2D72D2">**Interfaces**</span> appears as its own section in that left panel. Interfaces are distinguished from object types by a **dashed-line icon** (vs. the solid icon used for object types), reinforcing their abstract nature throughout the UI.

### Creating an interface

The creation flow is launched via <span style="color:#2D72D2">**New > Interface**</span> (top-right button) or <span style="color:#2D72D2">**Interfaces > + New interface**</span> in the left panel. A multi-step helper wizard guides the user through:

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;border-collapse:collapse;width:100%">
<tr style="background:#252A31">
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">Step</th>
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">Screen / Panel</th>
  <th style="padding:8px 12px;color:#8ABBFF;text-align:left;border-bottom:1px solid #383E47">Key action</th>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">1</td>
  <td style="padding:8px 12px;color:#fff;border-bottom:1px solid #383E47">Information screen</td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Read concept overview; select <b>Next</b></td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">2</td>
  <td style="padding:8px 12px;color:#fff;border-bottom:1px solid #383E47">Metadata screen</td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Enter display name, API name, optional description and icon</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">3</td>
  <td style="padding:8px 12px;color:#fff;border-bottom:1px solid #383E47">Properties screen</td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Add local or shared properties; toggle required / optional</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">4</td>
  <td style="padding:8px 12px;color:#fff;border-bottom:1px solid #383E47">Project selection</td>
  <td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Choose destination project; confirm creation</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#ABB3BF">5</td>
  <td style="padding:8px 12px;color:#fff">Ontology Manager main view</td>
  <td style="padding:8px 12px;color:#ABB3BF">Select <b>Save</b> (upper right) to publish the interface</td>
</tr>
</table>

### Interface detail view

After creation, selecting an interface opens a detail pane with dedicated tabs for **Properties**, **Extension**, and **Link Type Constraints**. Within the <span style="color:#2D72D2">**Extension**</span> tab, an **Add extension** control lets the modeler select parent interfaces from a dropdown; a confirmation dialog previews all inherited properties and links before saving.

### Status indicators

<span style="color:#238551"><b>● Saved / Published</b></span> — interface is live in the Ontology<br>
<span style="color:#C87619"><b>● Unsaved changes</b></span> — staged edits await the Save action<br>
<span style="color:#CD4246"><b>● Conflict / Error</b></span> — required property mapping missing or type mismatch<br>
<span style="color:#2D72D2"><b>● Primary action</b></span> — Save, New Interface, Implement, Add extension buttons

## Worked example

**Scenario:** A logistics company has three object types — `Warehouse`, `DistributionHub`, and `CrossdockFacility` — each with dozens of unique properties but all sharing a location, name, and capacity. A developer wants a single TypeScript v2 Function that can compute utilization across all three.

1. In Ontology Manager, the modeler creates a `LogisticsFacility` interface with three **required** local properties: `facilityName` (string), `geoLocation` (geo point), and `capacityUnits` (integer).
2. For each of the three object types, the modeler opens the **Interfaces** tab, selects "Implement new interface → LogisticsFacility," and maps the concrete object properties (`warehouse_name → facilityName`, `lat_lng → geoLocation`, `max_units → capacityUnits`).
3. A TypeScript v2 Function declares its input as `InterfaceObjectSet<LogisticsFacility>`. At runtime, Object Set Service resolves the search against all three implementing types and returns a unified set.
4. The function computes total utilization without any type-specific branching. Future object types (e.g., `FreezeWarehouse`) can adopt the interface without changing the function.

## Documentation map

The Interfaces section of the Foundry docs includes the following sub-pages:

- **Overview** — interface concepts, differences from object types, polymorphism model, support matrix
- **Create an interface** — wizard walkthrough, property types, required vs. optional, link type constraints
- **Implement an interface** — mapping object properties to interface properties, Pipeline Builder path, link type constraint mapping
- **Extend an interface** — parent-child composition, multiple inheritance, removing extensions
- *(API Reference)* **Ontology Interface basics** — List Interface Types and Get Interface Type REST endpoints, the interface-as-contract model

## Official documentation

- [Interfaces · Overview](https://www.palantir.com/docs/foundry/interfaces/interface-overview)
- [Interfaces · Create an interface](https://www.palantir.com/docs/foundry/interfaces/create-interface)
- [Interfaces · Implement an interface](https://www.palantir.com/docs/foundry/interfaces/implement-interface)
- [Interfaces · Extend an interface](https://www.palantir.com/docs/foundry/interfaces/extend-interface)
- [Ontology · Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Ontology Interface basics · API Reference](https://www.palantir.com/docs/foundry/api/ontologies-v2-resources/ontology-interfaces/ontology-interface-basics)
