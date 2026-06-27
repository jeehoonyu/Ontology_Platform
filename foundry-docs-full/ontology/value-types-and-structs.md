<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Value Types &amp; Structs</b></span><br>
<span style="color:#ABB3BF">Semantic type wrappers and structured multi-field properties for the Ontology.</span>
</td></tr></table>

## What it is

**Value Types** are reusable, space-scoped semantic wrappers around a primitive field type that attach metadata, validation constraints, and domain context to raw data (for example, wrapping a `string` into an `email` type that enforces a regex pattern). **Structs** are a property base type that packages multiple typed fields into a single composite property (for example, an `address` property with sub-fields for street, city, and postal code). Together they give Ontology builders a way to model rich, validated, domain-specific data beyond flat primitive columns.

---

## How it works

### Value Types — mechanics

1. **Definition in Value Type Manager.** A developer opens the <span style="color:#8ABBFF">Value Type Manager</span> application inside a Foundry space and clicks **Create value type**. They choose a base type (string, integer, decimal, double, float, boolean, date, timestamp, short, byte, long, array, or struct) and supply a name, API name, and description.

2. **Constraint attachment.** Zero or one constraint is added to the value type. Available constraints are:
   - <span style="color:#2D72D2">**Enum (One Of)**</span> — restricts to a static allowed-value set; applies to string, boolean, and numeric base types; string matching can be case-sensitive or case-insensitive.
   - <span style="color:#2D72D2">**Range**</span> — enforces min/max bounds; for strings this constrains string length; for arrays it constrains array size.
   - <span style="color:#2D72D2">**Regex**</span> — requires the string value to match a pattern; optional substring-match mode.
   - <span style="color:#2D72D2">**RID**</span> — string must be a valid Foundry Resource Identifier.
   - <span style="color:#2D72D2">**UUID**</span> — string must be a valid UUID.
   - <span style="color:#2D72D2">**Array Uniqueness**</span> — all array elements must be distinct.
   - <span style="color:#2D72D2">**Nested**</span> — applies a value type's constraints to each element inside an array.
   - <span style="color:#2D72D2">**Struct Element Constraints**</span> — maps struct field identifiers to individual value type references.

3. **Versioning on change.** The base type and constraints are immutable after creation. Any constraint modification produces a **new version**. Non-breaking version changes automatically propagate to every Ontology property and pipeline that consumes the type. Breaking changes (changes that invalidate existing data) require the owner to deprecate the current value type and create a replacement; this prevents silent runtime errors for existing consumers.

4. **Permissioning.** Value types are permissioned independently within the space so that different teams can control which pipelines and object types may apply a given type.

5. **Consumption in properties.** When an ontology builder maps a dataset column to an object-type property, they can select a value type instead of a raw base type. The Ontology then enforces the attached constraints during data ingest and in downstream Builder pipelines.

### Structs — mechanics

1. **Backing column requirement.** A struct property must derive from a single struct-type column in a dataset (for example a JSON-object column). The column must already exist in a datasource before the struct can be defined in the Ontology Manager.

2. **Field definition.** Each struct has one or more fields. Supported field types are: boolean, byte, date, decimal, double, float, geopoint, integer, long, short, string, and timestamp. Structs have a **depth of one** — nested structs are not permitted.

3. **Query indexing model.** Structs are indexed following the Elasticsearch object field type model. This means that when a property holds an **array of structs**, field conditions are evaluated independently across the whole array rather than per-element. A search for `firstName: "Harvey" AND lastName: "Face"` will match a record containing `[{firstName:"Harvey", lastName:"Dent"}, {firstName:"Two", lastName:"Face"}]` because both conditions are satisfied somewhere in the array, even if not in the same element.

4. **Platform support.** Structs are fully supported in Ontology Manager, Actions, Pipeline Builder, Workshop, Marketplace, and TypeScript v2 / Python Functions. Object Explorer supports basic struct search (field-level search is in development). Object Storage V1 (Phonograph) does not support structs.

5. **Struct-aware value type constraints.** A value type whose base type is `struct` can attach element-level constraints that map individual struct field identifiers to value type references, composing validation at the field level within the struct.

---

## User interface

### Ontology Manager — Property editor

The <span style="color:#8ABBFF">Ontology Manager</span> is the primary surface for attaching value types and creating struct properties. The layout is:

- **Left sidebar** — object type list, filtered by space.
- **Main panel** — object type detail view with tabs: <span style="color:#2D72D2">Overview</span>, <span style="color:#2D72D2">Properties</span>, <span style="color:#2D72D2">Link types</span>, <span style="color:#2D72D2">Actions</span>.
- **Properties tab** — table of all properties. A <span style="color:#2D72D2">**Create property**</span> button in the top-right opens the Property Editor panel.
- **Property Editor panel** — right-side slide-in: name field, description field, **Base type** dropdown (includes Struct and any defined value types), **Data** section for backing column selection, and (for structs) a **Struct fields** section with **Add field → New field** controls.

### Value Type Manager — standalone app

<table>
<tr style="background:#1C2127;color:#ABB3BF">
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Panel</th>
<th style="padding:8px 12px;border:1px solid #383E47;text-align:left">What you see</th>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Value type list</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">All value types in the space, with name, base type, version number, and consumer count.</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Detail view</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Metadata (name, API name, description), base type badge, constraint configuration, version history timeline.</td>
</tr>
<tr style="background:#252A31">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Consumers tab</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">List of all object type properties and pipelines consuming this value type, with links to each.</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Versions tab</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Immutable version history; active version highlighted; deprecated versions shown in muted text.</td>
</tr>
</table>

**Status chips used across both UIs:**

<span style="color:#238551"><b>● Active</b></span> · <span style="color:#C87619"><b>● Deprecated</b></span> · <span style="color:#CD4246"><b>● Breaking change detected</b></span> · <span style="color:#2D72D2"><b>● Latest version</b></span>

Metadata fields (name, description, API name) are editable at any time without triggering a new version. Constraint edits open a **confirmation dialog** that lists all consumers and warns if the change is breaking.

---

## Worked example

**Goal:** Model an `Employee` object type with a validated `workEmail` property and a composite `homeAddress` property.

1. **Create the `workEmail` value type.** Open Value Type Manager, click **Create value type**, set base type to `string`, name it `Work Email`, API name `workEmail`. Add a **Regex** constraint: `^[a-zA-Z0-9._%+\-]+@company\.com$`. Save — version 1 is created.

2. **Create the `homeAddress` struct column.** In the upstream dataset (Pipeline Builder), ensure the backing dataset has a struct-typed column `home_address` with sub-fields `street` (string), `city` (string), `state` (string), `postal_code` (string).

3. **Define the `Employee` object type.** In Ontology Manager, open (or create) the `Employee` object type and go to the **Properties** tab.

4. **Add `workEmail` property.** Click **Create property**, name it `Work Email`, select `workEmail` (value type) as the base type, map the backing column `work_email`. The Ontology now enforces the regex across all data ingest.

5. **Add `homeAddress` struct property.** Click **Create property**, name it `Home Address`, set base type to `Struct`, select backing column `home_address`. In the **Struct fields** section, click **Add field → New field** for each sub-field (`street`, `city`, `state`, `postal_code`), mapping each to the corresponding dataset sub-column.

6. **Publish the ontology branch.** Both properties are live. Actions and Workshop can now read/write the `workEmail` field with constraint validation and display `homeAddress` as a structured card.

---

## Documentation map

- **Object and link types**
  - Properties
    - [Overview](https://www.palantir.com/docs/foundry/object-link-types/properties-overview)
    - [Base types](https://www.palantir.com/docs/foundry/object-link-types/base-types)
    - [Type reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)
    - Mandatory control properties
  - Value types
    - [Overview](https://www.palantir.com/docs/foundry/object-link-types/value-types-overview)
    - Create a value type
    - Use value types on properties
    - [Value type constraints](https://www.palantir.com/docs/foundry/object-link-types/value-type-constraints)
    - [Value type versions](https://www.palantir.com/docs/foundry/object-link-types/value-types-versions)
    - Value type permissions
  - Structs
    - [Overview](https://www.palantir.com/docs/foundry/object-link-types/structs-overview)
    - [Create a struct type](https://www.palantir.com/docs/foundry/object-link-types/create-struct-type)
    - Edit a struct type
    - [Structs and shared properties](https://www.palantir.com/docs/foundry/object-link-types/struct-shared-properties)
    - Designating main fields
    - Automapping
  - Action types
    - [Actions on structs](https://www.palantir.com/docs/foundry/action-types/actions-on-structs)

---

## Official documentation

- [Value Types — Overview](https://www.palantir.com/docs/foundry/object-link-types/value-types-overview)
- [Value Type Constraints](https://www.palantir.com/docs/foundry/object-link-types/value-type-constraints)
- [Value Type Versions](https://www.palantir.com/docs/foundry/object-link-types/value-types-versions)
- [Structs — Overview](https://www.palantir.com/docs/foundry/object-link-types/structs-overview)
- [Create a Struct Type](https://www.palantir.com/docs/foundry/object-link-types/create-struct-type)
- [Structs and Shared Properties](https://www.palantir.com/docs/foundry/object-link-types/struct-shared-properties)
- [Actions on Structs](https://www.palantir.com/docs/foundry/action-types/actions-on-structs)
- [Ontology Core Concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
