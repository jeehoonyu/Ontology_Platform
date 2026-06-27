# Object Types

> An object type is the schema definition of a real-world entity or event in the Palantir Foundry Ontology, mapping one or more backing datasets to a named, queryable concept your organization can reason about.

## What it is

Object types are the foundational building blocks of the Foundry Ontology — the semantic layer that sits on top of raw datasets and models integrated into Foundry. They solve the problem of data living in isolated tables with no shared meaning: instead of referencing a dataset called `employees_v3_final`, teams work with an `Employee` object type that carries rich metadata, properties, and relationships. Object types live inside the Ontology Manager application and are organized into ontology projects. Each row in a backing dataset becomes an individual object instance; a collection of instances is called an object set.

## When to use it

- You want to model a real-world entity (employee, facility, customer, shipment) so that downstream tools like Workshop, Object Explorer, and AIP can reason about it.
- You need to attach relationships between entities (e.g., `Employee` linked to `Department`) using link types.
- You want to expose consistent, governed data to non-technical users without giving them direct dataset access.
- You are building Foundry Actions or Functions that operate on business objects rather than raw rows.
- You need fine-grained, property-level security and governance on top of a dataset.

**When NOT to use it / alternatives:** If you only need ad-hoc analysis on a single dataset and do not need downstream applications or Actions, querying the dataset directly in Code Workbook or Contour may be simpler. Object types add overhead (sync pipelines, Ontology governance) that is not always warranted for purely exploratory work.

## Key concepts & terminology

- **Object type** — The schema (like a table definition) describing all entities of a given kind (e.g., "Employee").
- **Object** — A single instance of an object type; analogous to one row in a dataset (e.g., "Melissa Chang").
- **Object set** — A filtered or grouped collection of objects (e.g., "All tenured employees").
- **Backing datasource** — The Foundry dataset or stream whose rows are turned into object instances; one datasource can back only one object type.
- **Primary key** — The property (column) that uniquely identifies every object instance; must be unique, non-null, and deterministic across pipeline rebuilds.
- **Title key** — The property used as the human-readable display name for an object (shown in Object Explorer, Workshop cards, etc.).
- **Property** — A typed attribute of an object type, analogous to a column; the schema is the property, and the value on a specific object is the property value.
- **Status** — A metadata signal on a property indicating its maturity: `active` (production-ready), `experimental` (in development), or `deprecated` (being phased out).
- **API name** — A machine-readable identifier auto-generated in PascalCase (object types) or camelCase (properties); used by Functions, the REST API, and AIP agents.
- **Link type** — A relationship definition connecting two object types, similar to a foreign-key join.
- **Action type** — A schema definition for allowed changes to object property values or links.
- **Ontology Manager** — The Foundry application where object types are created and configured.

## Core capabilities / features

- **Backing datasource connection** — Attach one or more Foundry datasets (or streams) as the data source. Columns automatically map to properties. Note: datasources cannot contain `MapType` or `StructType` columns.
- **Property mapping** — Each column in the backing dataset can be exposed as a typed property. Supported base types include String, Integer, Long, Boolean, Date, Timestamp, Double, Decimal, Geopoint, Geoshape, Array, Time Series, Attachment, and Media Reference.
- **Primary key designation** — Exactly one property must be marked as the primary key. Best practice is a stable String or Integer column. Time-based and floating-point columns are discouraged because of collision risk. Changing the primary key after objects have edits applied requires deleting those edits first.
- **Title key designation** — One property is marked as the display name. String columns are typical; most base types are eligible.
- **Property status** — Each property carries a status (`active`, `experimental`, `deprecated`) so Ontology builders can communicate stability to downstream users.
- **API name configuration** — Auto-generated but fully customizable. Object type API names are PascalCase, 1-100 alphanumeric characters, unique across the entire ontology. Property API names are camelCase, 1-100 alphanumeric characters, unique within the object type.
- **Metadata** — Each object type has an icon, color, display name, plural name, description, and organizational groups for discoverability.
- **Derived and shared properties** — Properties can be shared across multiple object types (for consistent modeling) or derived from other property values via Functions.
- **Permissions** — Editing permissions can be set at the object type level, controlling who can trigger Actions against objects.
- **Integrations** — Optional integrations (e.g., Gotham) can be enabled per object type.

## How it works / typical workflow

1. **Open Ontology Manager** and select "New > Create object type" (or use the guided helper "Create your first object type").
2. **Choose a backing datasource** — select an existing Foundry dataset or create a new empty one. The wizard warns you if the dataset is already backing another object type (each datasource backs only one type).
3. **Configure metadata** — set the icon, color, display name, plural name, description, and groups.
4. **Map properties** — dataset columns auto-map; remove any columns you do not want exposed, and set the data type for each property.
5. **Set the primary key** — select the property whose values are unique and deterministic for every row.
6. **Set the title key** — select the property that will serve as the human-readable name.
7. **Assign property statuses** — mark properties as `active`, `experimental`, or `deprecated` as appropriate.
8. **Optionally generate Actions** — the wizard can scaffold standard create/edit/delete Actions and assign permissions.
9. **Choose a save location** (project), then click **Create** to stage and **Save** to publish changes to the Ontology.

## Example

**Scenario:** You have a Foundry dataset `warehouse_inventory` with columns `sku_id` (String, unique), `product_name` (String), `quantity_on_hand` (Integer), and `last_updated` (Timestamp).

**Object type configuration:**
- Display name: `Inventory Item` / Plural: `Inventory Items`
- Backing datasource: `warehouse_inventory`
- Primary key: `sku_id` (unique String — ideal choice)
- Title key: `product_name`
- Properties: `quantity_on_hand` (Integer, status: active), `last_updated` (Timestamp, status: active)
- API name: `InventoryItem`

After saving, each row in `warehouse_inventory` becomes an `InventoryItem` object. Workshop builders can then drop an Object Table widget pointing at `InventoryItem` objects, and operations teams can search inventory in Object Explorer without ever seeing the raw dataset.

## How it connects to the rest of Foundry

- **Ontology** — Object types are the primary building block; they are connected by **link types** and acted upon by **action types**.
- **Properties / Shared Properties** — Properties belong to object types; shared properties can span multiple types for consistent modeling.
- **Functions** — TypeScript Functions accept object types as typed inputs and can return derived property values or filtered object sets; they are invoked via Actions or Workshop.
- **Workshop** — The no-code app builder consumes object types natively; widgets such as Object Table, Object View, and filters all operate on object sets.
- **AIP / AI Platform** — AIP agents use object types as a structured knowledge layer, querying and writing back through Action types.
- **Object Explorer** — A built-in Foundry interface for browsing and searching objects of any type.
- **Pipelines / Object Storage** — After saving an object type, Foundry provisions an Object Storage V2 pipeline that syncs the backing dataset into the ontology index on a schedule.
- **Interfaces** — Polymorphic type definitions that group multiple object types sharing common properties, enabling uniform querying across them.

## Tips & gotchas for learners

- **Primary key stability is critical.** If the primary key changes between pipeline runs (non-deterministic generation like UUIDs created at runtime), user edits applied via Actions will be lost and link types will break.
- **One datasource, one object type.** A dataset can only back a single object type. If you try to reuse it, you will see a `DatasetAndBranchAlreadyRegistered` error. Create a derived dataset if you need a second object type from the same source.
- **No MapType or StructType columns.** Flatten complex nested columns before using a dataset as a backing source.
- **Changing the primary key is destructive.** If objects already have edits, you must delete those edits before switching primary key columns.
- **API names are permanent (practically).** Downstream Functions, Workshop apps, and API clients depend on API names. Rename them early; renaming later is a breaking change.
- **Property status is advisory.** Marking a property `deprecated` does not remove it — it signals to other builders that they should migrate away from it.
- **Duplicate primary key values cause pipeline failures** in Object Storage V2. Validate uniqueness in your dataset pipeline before registering it.
- **The guided helper is the safest starting point** for new builders; exiting it early leaves the object type in a partially configured state that you must complete manually.

## Official documentation

- [Object and link types: Object types overview](https://www.palantir.com/docs/foundry/object-link-types/object-types-overview)
- [Object and link types: Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type)
- [Object and link types: Properties overview](https://www.palantir.com/docs/foundry/object-link-types/properties-overview)
- [Object and link types: Properties base types](https://www.palantir.com/docs/foundry/object-link-types/base-types)
- [Ontology: Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology: Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
