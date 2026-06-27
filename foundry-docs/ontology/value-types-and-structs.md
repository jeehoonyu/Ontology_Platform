# Value Types & Structs

> Value types are reusable, versioned semantic wrappers around primitive field types that attach metadata and validation constraints to Ontology properties; structs are a special property base type that groups multiple fields into a single schema-based property.

## What it is

Value types and structs both live inside the **Ontology** layer of Palantir Foundry and extend how properties are defined on object types.

A **value type** solves the problem of duplicating validation logic. Instead of writing an email regex on every property that stores an email address, you define it once as a value type and reuse it across as many properties and pipelines as you like. Value types are managed in the **Value Type Manager** application and are scoped to a single Foundry *space*.

A **struct** solves the problem of storing compound, multi-field data in one property. Rather than creating separate `street`, `city`, and `postal_code` properties, you define a single `address` struct property with all three fields embedded. Structs are a property base type configured in **Ontology Manager**.

## When to use it

**Use a value type when:**
- The same semantic concept (e.g., email, UUID, currency code, status enum) appears on many object type properties and you want one place to update constraints.
- You need formal validation rules — regex patterns, range limits, or fixed enumerations — enforced consistently across the Ontology.
- You want versioning and governance history for how a data type's rules evolve over time.
- You want to expose reusable, documented types to downstream consumers (Functions, Ontology SDK, Workshop).

**Use a struct property when:**
- A single logical concept naturally contains multiple subfields (address, name, bounding box, sensor reading).
- You are sourcing data from a dataset column that is already a struct type.
- You need to display or query compound data as a unit inside Actions, Workshop, or Functions.

**When NOT to use:**
- Do not use structs when you need to *nest* structs inside structs — structs have a hard depth limit of one.
- Do not use value types to share types across different Foundry spaces — value types are space-scoped and cannot cross space boundaries.

## Key concepts & terminology

- **Value type** — A named, versioned semantic layer (metadata + constraints) placed over a primitive base type (e.g., `String`, `Integer`).
- **Base type** — The underlying primitive type a value type wraps (e.g., `String`, `Double`, `Boolean`, `Date`, `Timestamp`, `Decimal`).
- **Constraint** — A validation rule attached to a value type that limits which values are accepted (enum, range, regex, UUID format, etc.).
- **Value Type Manager** — The Foundry application used to create and manage value types.
- **Versioning** — Every constraint change on a value type creates a new version; metadata-only changes (name, description, apiName) do not.
- **Non-breaking change** — A constraint update that does not conflict with existing consumers; it auto-propagates across the Ontology.
- **Breaking change** — A constraint update that would conflict with existing usage; Foundry warns you and recommends deprecation + replacement instead.
- **Struct** — An Ontology property base type that bundles multiple typed subfields into one property.
- **Struct field** — A named, typed slot inside a struct (allowed types: `STRING`, `INTEGER`, `LONG`, `DOUBLE`, `DECIMAL`, `DATE`, `TIMESTAMP`, `GEOPOINT`, `BOOLEAN`, and others).
- **Element constraint** — A constraint type specific to structs that maps each struct field to a value type reference.
- **Space** — A Foundry organizational boundary; value types are only usable within the space where they were defined.

## Core capabilities / features

### Value type features

- **Semantic metadata** — Each value type carries a human-readable name, description, and an `apiName` used in code, making properties self-documenting across the platform.
- **Constraint types:**
  - *Enum (one of)* — Restricts a property to a fixed set of allowed values. Supported on `String`, `Boolean`, `Decimal`, `Double`, `Float`, `Integer`, `Short`. String enums can be case-sensitive or case-insensitive.
  - *Range* — Sets minimum and/or maximum bounds. Works on numeric types, `Date`, `Timestamp`, and `String` (constrains string length) and `Array` (constrains array size).
  - *Regex* — Validates string values against a pattern (substring match supported).
  - *RID / UUID format* — Built-in validators for Foundry Resource Identifier or UUID string formats.
  - *Array uniqueness* — Enforces that no two elements in an array property are duplicates.
  - *Element constraints* — For struct properties, maps individual struct fields to specific value type references.
- **Versioning and governance** — Constraint edits always produce a new version. Non-breaking new versions automatically propagate to every Ontology property that uses the value type. The base type of a value type is immutable once created.
- **Permissions** — Access control can be configured per value type, restricting who may read or apply it.
- **Reusability** — One value type can be applied to multiple properties across multiple object types within the same space.

### Struct features

- **Multi-field properties** — A single struct property can hold several fields, each with its own type, all stored and queried as one unit.
- **Depth of one** — Structs are flat; nesting a struct inside another struct is not supported.
- **Dataset-backed** — Struct properties originate from dataset columns of struct type. Fields from different sources can be combined as long as the pipeline outputs a single struct column before Ontology ingestion.
- **Value type integration** — Struct fields can themselves reference value types via element constraints, bringing validation to individual subfields.
- **Cross-platform support** — Structs are usable in Ontology Manager, Actions, Pipeline Builder, Workshop, Functions (TypeScript v2 and Python), Object Explorer, and the Ontology SDK (with feature support varying by service).
- **ElasticSearch semantics** — When querying arrays of structs, field conditions are evaluated independently (not as a matched pair within the same array element). Keep this in mind when building filters.

## How it works / typical workflow

### Creating and using a value type

1. Open **Value Type Manager** from the Foundry home or navigation.
2. Click **Create value type**, enter a name, description, and `apiName`.
3. Choose a **base type** (e.g., `String`).
4. Optionally add a **constraint** (e.g., Regex for email format, or Enum for a status field).
5. Save — the value type is now available in your space.
6. In **Ontology Manager**, open an object type and navigate to a property.
7. Assign the value type to the property — the property inherits the constraint and semantic label.
8. When constraints need to change, edit the value type; Foundry creates a new version and propagates non-breaking changes automatically.

### Creating a struct property

1. Prepare a dataset that contains a column of struct type (e.g., via Pipeline Builder or a transform that combines fields into a struct).
2. In **Ontology Manager**, add a new property to an object type and set the base type to **Struct**.
3. Define the struct fields (name and type for each subfield), or let Foundry infer them from the dataset column schema.
4. Save the property — it is now queryable and visible in Workshop, Actions, and Functions as a single compound value.

## Example

**Scenario:** You manage a `Customer` object type. Customers have an email and a mailing address.

- **Email** — Create a value type `EmailAddress` with base type `String` and a Regex constraint (e.g., `^[^@\s]+@[^@\s]+\.[^@\s]+$`). Apply `EmailAddress` to the `email` property on `Customer`. Every other object type that also stores emails (e.g., `Contact`, `Vendor`) can reuse the same `EmailAddress` value type.

- **Mailing address** — Define a struct property `mailingAddress` on `Customer` with fields: `street` (STRING), `city` (STRING), `postalCode` (STRING), `country` (STRING). The struct is sourced from a pipeline column that consolidates address data before ingestion.

In Functions (TypeScript), the struct is accessed as:

```typescript
const addr = object.mailingAddress;
console.log(addr?.city, addr?.postalCode);
```

## How it connects to the rest of Foundry

- **Object types & properties** — Value types and structs are applied at the property level on object types, enriching the Ontology's type system.
- **Pipeline Builder / Transforms** — Struct properties require a struct-typed dataset column produced upstream in a pipeline.
- **Ontology SDK & Functions** — Value type metadata (including `apiName`) surfaces in the generated SDK. Struct fields are accessed as nested objects in TypeScript/Python Functions.
- **Workshop** — Struct properties render as compound values in widgets; enum value types can drive dropdowns or filter chips.
- **Actions** — Struct fields and value type constraints can inform input validation in Action forms.
- **Object Explorer** — Struct properties display their subfields inline when browsing object instances.
- **Ontology API (v2)** — Value types are queryable via the `Get Ontology Value Type` endpoint, making them introspectable programmatically.

## Tips & gotchas for learners

- **Space boundary is strict** — A value type created in Space A cannot be used in Space B. Plan your value type library within the right space from the start.
- **Base type is permanent** — Once you create a value type with base type `String`, you cannot change it to `Integer`. Create a new value type instead.
- **Breaking changes require deprecation** — Never edit constraints in a way that invalidates existing data. Foundry will warn you; heed the warning and create a replacement type.
- **Structs are flat** — A struct field cannot itself be a struct. If you need nested compound data, reconsider your data model or flatten it in a pipeline.
- **Array-of-struct query semantics** — If a property is an array of structs, a filter like `city = "Paris" AND postalCode = "75001"` does NOT guarantee both conditions come from the same array element. Test queries carefully.
- **Minimum one field** — A struct must have at least one field; an empty struct definition is invalid.
- **Metadata changes are free** — Renaming or re-describing a value type (name, description, apiName) does not create a new version and has no downstream impact on constraints.
- **Auto-propagation is convenient but watch consumers** — Non-breaking version updates roll out automatically to all users of a value type. Coordinate with consumers before making any constraint changes.

## Official documentation

- [Value types overview](https://www.palantir.com/docs/foundry/object-link-types/value-types-overview)
- [Value type constraints](https://www.palantir.com/docs/foundry/object-link-types/value-type-constraints)
- [Value type versions](https://www.palantir.com/docs/foundry/object-link-types/value-types-versions)
- [Structs overview](https://www.palantir.com/docs/foundry/object-link-types/structs-overview)
- [Types reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)
- [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)
