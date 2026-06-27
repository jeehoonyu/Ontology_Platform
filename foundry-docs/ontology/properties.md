# Properties & Shared Property Types

> Properties are the typed attributes (like columns in a table) attached to object types in the Foundry Ontology, and shared property types are reusable property definitions that can be applied consistently across multiple object types.

## What it is

Properties define the schema-level characteristics of objects — think of them as the columns of a database table, where each individual property value on an object is the equivalent of a field entry. They live inside the **Ontology Manager** application and are configured on **object types**. Properties solve the problem of translating raw dataset columns into semantically meaningful, consistently-named, and visually rich attributes that business applications can use directly. Shared property types take this further by letting you define a property once (name, description, base type, render hints, formatting) and reuse that definition across many object types, so changes propagate centrally rather than having to be repeated everywhere.

## When to use it

- When you are building or editing an object type and need to expose a dataset column as a meaningful attribute (e.g., "Employee Name", "Contract Value").
- When the same concept — such as "Status" or "Location" — appears on several different object types and you want consistent naming, formatting, and behavior everywhere.
- When you need computed attributes that are not stored in a dataset but calculated at query time from linked objects (use **derived properties**).
- When you want to control how a property renders in Workshop, Object Explorer, or Quiver (use render hints and conditional formatting).
- When you need to enable search, sort, or filter capabilities on a property inside applications (configure render hints like Searchable, Sortable, Selectable).

**When NOT to use shared properties:** If a property is truly unique to one object type and will never be reused, a regular (non-shared) property is simpler. Shared properties carry a Beta label and involve a slightly heavier governance workflow.

## Key concepts & terminology

- **Property**: A schema-level attribute on an object type, analogous to a dataset column.
- **Property value**: The actual data on a single object instance, analogous to a field value.
- **Base type**: The data type of the property (e.g., String, Integer, Timestamp, Geopoint). It determines which operations and applications are available.
- **Shared property**: A property definition that can be applied to multiple object types; metadata is centralized but the underlying data per object type stays separate.
- **Render hint**: Metadata that tells user applications how to index or display a property (e.g., Searchable, Sortable, Long text).
- **Type class**: Additional metadata tags interpreted by user applications to modify behavior (e.g., marking a property as editable).
- **Conditional formatting**: Rules applied to a property that control its visual presentation (color, alignment) in supported applications based on property values.
- **Derived property**: A read-only property calculated at runtime by aggregating or selecting values from linked objects; not stored in a dataset.
- **Visibility**: A metadata setting (prominent, normal, or hidden) that controls how prominently applications display the property.
- **Value formatting**: Display-level formatting for numeric, date/time, or resource-ID property values.

## Core capabilities / features

### Base types
Every property must have a base type. Common types include **String**, **Integer**, **Long**, **Double**, **Decimal**, **Boolean**, **Date**, and **Timestamp**. Advanced types include:
- **Geopoint** and **Geoshape** for geographic data.
- **Time series** for streaming or historical values over time.
- **Attachment** for storing files on objects.
- **Media reference** for linking to media sets.
- **Vector** for semantic-search embeddings (up to 2,048 dimensions).
- **Struct** for schema-based composite values with multiple sub-fields.
- **Cipher text** for encrypted string values.

Most types support arrays (multi-valued properties), with the exception of Vector and Time series. `Map` and `Binary` are not valid base types.

### Render hints
Render hints are advisory signals from the Ontology to applications about how to handle a property. Many hints add a raw index (requiring a reindex operation):
- **Searchable** — enables search/sort; required before most other hints.
- **Sortable** — allows timeline and chart sorting.
- **Selectable** — enables aggregations and exact-match filters.
- **Low cardinality** — signals a small set of possible values.
- **Enable leading wildcards** / **Enable regex queries** — allow advanced text query patterns.
- **Long text** — improves rendering of large text bodies.
- **Identifier** — optimizes display for primary/foreign key-style strings.
- **Keywords** — surfaces the property in its own highlighted section in apps.
- **Disable formatting** — prevents locale-based numeric formatting in Object Views.

### Conditional formatting
Rules configured on a property that dictate visual rendering (color, alignment) in Object Explorer, Object Views, Quiver, and Workshop. Rules can be:
- **Standard** — condition-based (string comparison, numeric range, null check, exact match).
- **Always true** — a fallback rule that applies when no other rule matches.
- **Math rules** — numeric expression-based conditions.

Conditional formatting overrides type-class-based formatting and can be copied from one property to many others at once. It does not apply to properties using the legacy `hubble:editable` type class.

### Shared properties
A shared property centralizes the definition — name, description, base type, value formatting, type classes, render hints, visibility — so that all object types using it stay in sync. The globe icon in Ontology Manager identifies shared properties. You can either create a new shared property from scratch or promote an existing object-type property to a shared one. Crucially, the metadata is shared but each object type's actual data remains independent.

### Derived properties
Derived properties are computed at query time from linked objects rather than stored in a backing dataset. They traverse up to **3 levels** of link types and support aggregations: Count, Average, Sum, Min, Max, Collect list, Collect set, and cardinality estimates. They are always read-only, security-aware (respecting permissions of all traversed objects), and cannot be used as primary keys, in text search, or with OSv1-indexed object types.

### Other property features
- **Required properties**: Enforce mandatory data entry.
- **Edit-only properties**: Visible only during action/edit contexts, not in read views.
- **Value formatting**: Control how numbers, dates, or IDs display to end users.
- **Visibility settings**: Prominent, normal, or hidden — controls default display prominence in apps.

## How it works / typical workflow

1. **Open Ontology Manager** and navigate to the object type you want to configure.
2. **Add or select a property.** Either map a column from a backing dataset or create a new property. Assign a display name, description, API name, and base type.
3. **Configure metadata.** Set value formatting, visibility, type classes, and render hints appropriate for how the property will be used (e.g., enable Searchable + Sortable if users will filter or sort on it in Workshop).
4. **Add conditional formatting (optional).** Define rules so that property values render with meaningful colors or alignment in applications.
5. **Promote to shared property (optional).** If the same property concept will appear on other object types, convert it to a shared property so all instances share the same metadata definition.
6. **Configure derived properties (optional).** If you need computed values from linked objects, add a derived property, choose the traversal path, and select an aggregation function.
7. **Reindex if needed.** Render hints that add raw indexes require a reindex operation before they take effect in applications.
8. **Verify in Object Explorer or Workshop** that the property displays, filters, and formats as expected.

## Example

**Scenario:** You have two object types — `Employee` and `Contractor` — and both should expose a "Home Country" string property with the same display name, description, and Searchable + Selectable render hints.

1. In Ontology Manager, create a new shared property: display name `Home Country`, base type `String`, render hints `Searchable` and `Selectable`.
2. Apply the shared property to both the `Employee` and `Contractor` object types.
3. Back the property with the appropriate dataset columns for each type.
4. Add a conditional formatting rule: if `Home Country` equals `"USA"`, display in blue; otherwise display in default color.
5. Both object types now show `Home Country` with identical metadata, render hints, and formatting rules — updated from a single place.

Additionally, on the `Department` object type you could add a **derived property** `Average Employee Salary` that traverses the `Department → Employee` link and applies an Average aggregation over the `Salary` property.

## How it connects to the rest of Foundry

- **Object types and link types**: Properties are always children of an object type. Derived properties depend on link types to traverse the graph.
- **Ontology Manager**: The central tool for creating and managing all property configuration.
- **Workshop**: Reads render hints, conditional formatting, and visibility settings to display tables, filters, and property cards correctly.
- **Object Explorer and Quiver**: Respect searchable/sortable/selectable render hints and conditional formatting rules.
- **Object Views**: Use value formatting, conditional formatting, and the Long text / Keywords render hints for rich display.
- **Functions and Actions**: Functions can read and compute over properties; Actions can write to non-derived, non-edit-only properties. Derived properties are read-only and cannot be written by actions.
- **OSDK (Ontology SDK)**: References properties by their API name; struct types in derived properties have query limitations.
- **Pipelines / Datasets**: Regular (non-derived) properties are backed by dataset columns mapped through Object Storage.

## Tips & gotchas for learners

- **Render hints require reindexing.** Adding Searchable, Sortable, Selectable, or wildcard/regex hints after an object type is already populated triggers a reindex — plan for this in production rollouts.
- **Searchable must come first.** Sortable, Selectable, Low cardinality, leading wildcards, and regex all depend on Searchable being enabled. Enabling them without Searchable has no effect.
- **Shared property data is NOT shared.** The definition is shared; each object type's values still come from its own backing dataset column. Do not expect a write to one object type's column to appear on another.
- **Derived properties cannot be used in text search or as primary keys.** Trying to filter by a derived property using keyword search will silently fail.
- **Derived properties are limited to 3 link traversal levels.** If you need deeper traversal, consider persisting the value as a regular property via a pipeline.
- **Conditional formatting overrides type classes.** If you have both a type-class-based color and a conditional formatting rule, the conditional formatting wins.
- **`Map` and `Binary` are not valid base types** for properties even though they exist in other contexts.
- **Some base types have limited action support.** `byte`, `decimal`, `float`, `short`, and `vector` have restrictions in action types — check compatibility before modeling a workflow around them.
- **The globe icon** in Ontology Manager is the quick visual cue that a property is a shared property type.

## Official documentation

- [Properties - Overview](https://www.palantir.com/docs/foundry/object-link-types/properties-overview)
- [Properties - Base types](https://www.palantir.com/docs/foundry/object-link-types/base-types)
- [Properties - Metadata reference](https://www.palantir.com/docs/foundry/object-link-types/property-metadata)
- [Properties - Add conditional formatting](https://www.palantir.com/docs/foundry/object-link-types/conditional-formatting)
- [Properties - Derived properties](https://www.palantir.com/docs/foundry/object-link-types/derived-properties)
- [Metadata - Render hints](https://www.palantir.com/docs/foundry/object-link-types/metadata-render-hints)
- [Shared properties - Overview](https://www.palantir.com/docs/foundry/object-link-types/shared-property-overview)
- [Shared properties - Create shared properties](https://www.palantir.com/docs/foundry/object-link-types/create-shared-property)
- [Shared properties - Use shared properties on object types](https://www.palantir.com/docs/foundry/object-link-types/use-shared-property)
- [Shared properties - Metadata reference](https://www.palantir.com/docs/foundry/object-link-types/shared-property-metadata)
- [Ontology - Overview](https://www.palantir.com/docs/foundry/ontology/overview)
