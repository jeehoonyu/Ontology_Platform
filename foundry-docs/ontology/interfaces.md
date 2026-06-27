# Interfaces

> An Interface is an abstract Ontology type that defines a shared "shape" — a set of properties and link constraints — that multiple concrete object types can implement, enabling polymorphic, type-agnostic workflows.

## What it is

Interfaces solve the problem of writing separate application logic for every similar-but-distinct object type (for example, Airport, Manufacturing Plant, and Maintenance Hangar all being kinds of "Facility"). By defining a common interface, you create a single contract that all implementing object types must satisfy, letting your applications and Functions talk to any conforming object type through one consistent API. Interfaces live inside the Ontology Manager alongside object types, link types, and action types — they are a first-class Ontology construct, not a code library or dataset.

Unlike object types, interfaces are **abstract**: they have no backing dataset and cannot be instantiated directly. They exist purely as schemas that object types opt into.

## When to use it

- You have two or more object types that share meaningful common properties (for example, all asset types share "Name", "Location", and "Owner").
- You want to write a Workshop app, Function, or SDK query that works uniformly over a category of objects without knowing the specific type at query time.
- You are building a Marketplace package and want consumers to plug in their own object types without modifying your application code.
- You need to add a new object type to an existing workflow without touching downstream application code — just implement the interface.
- You want to enforce a governance contract (required properties, required link types) across a family of related object types.

**When NOT to use it / alternatives:** If only one object type ever shares the shape, a plain object type with shared properties is simpler. Interfaces add maintenance overhead — any change to a required property must be propagated to every implementing object type simultaneously.

## Key concepts & terminology

- **Interface** — An abstract Ontology type that declares a named set of properties and optional link type constraints; cannot be instantiated directly.
- **Interface property** — A property defined on (or referenced by) an interface; each is marked required or optional.
- **Local property** — A property defined directly on the interface (recommended approach for clarity and simplicity).
- **Shared property** — A property defined elsewhere in the Ontology and referenced by the interface; useful when the same property must stay consistent across many types.
- **Required property** — A property the implementing object type *must* map; omitting it breaks the implementation.
- **Optional property** — A property the implementing object type *may* map; skipping it is allowed, which prevents "upgrade blockers" in Marketplace scenarios.
- **Implementation** — The declaration on an object type that it satisfies a given interface, including the explicit property mapping.
- **Property mapping** — The per-implementation specification of which object-type property satisfies each interface property.
- **Link type constraint** — A rule on the interface that requires implementing object types to have a link type of a particular shape.
- **Interface extension** — The ability for one interface to inherit the properties of a parent interface and add more specific ones, creating a hierarchy.
- **Polymorphism** — The ability to query or interact with multiple concrete object types through a single abstract interface, without knowing which concrete type is returned.

## Core capabilities / features

- **Polymorphic querying** — Object Set Service searches against an interface return matching objects across *all* implementing object types. This means a single query like "find all Facilities near location X" returns Airports, Plants, and Hangars together.

- **Multiple implementations per interface** — One interface can be implemented by any number of object types, and one object type can implement multiple interfaces.

- **Interface extension / inheritance** — Interfaces can extend parent interfaces. Child interfaces inherit all parent properties and constraints, then add their own. Object types implementing the child interface automatically satisfy the parent interface too.

- **Required vs optional properties** — Marking properties optional lets Marketplace package authors ship interfaces iteratively: new optional properties can be added without forcing every existing implementor to update immediately.

- **Link type constraints** — Beyond properties, interfaces can require that implementing object types define a link type of a specified shape (for example, "must have a link to an Employee object type"). Required constraints must be satisfied; optional constraints are discretionary.

- **API name contract** — Interfaces expose their own API names that SDK clients and Functions can use, so application code is written against the interface rather than any specific object type.

- **Visual distinction in Ontology Manager** — Interface icons display with a dashed border, distinguishing them from solid-bordered object type icons.

- **Supported surfaces (as of current docs):**
  - Fully supported: Ontology Manager, Marketplace, TypeScript v2 Functions
  - Partially supported: Actions, Object Set Service, Ontology SDK
  - Not yet supported: Workshop, TypeScript v1 Functions, Python Functions

## How it works / typical workflow

1. **Open Ontology Manager** and select **New > Interface** (or **Interfaces > + New interface** in the Resources panel).
2. **Define metadata** — provide a display name, API name, and optional description and icon.
3. **Add properties** — define each property as local (recommended) or shared; mark each required or optional.
4. **Add link type constraints** (optional) — specify required or optional link shapes that implementors must satisfy.
5. **Save** the interface.
6. **Navigate to each object type** that should implement it. Open its **Interfaces** tab and select **Implement new interface**.
7. **Map properties** — for each required interface property, select the corresponding property on the object type. Skip optional properties if not applicable.
8. **Satisfy link constraints** — if the interface has required link type constraints, select or create matching link types on the object type.
9. **Save** the implementation. The object type now participates in all interface-based queries and SDK calls.
10. **Write application logic** (Functions, SDK, Object Set Service queries) against the interface API name — it will work for all current and future implementing object types without code changes.

## Example

**Scenario:** Your organization tracks physical locations across three domains: Airports, Warehouses, and Data Centers. You create a `Facility` interface so that a single Workshop map tile can pin all locations regardless of type.

**Interface definition (conceptual):**

```
Interface: Facility
  Properties:
    facilityName  (string)  — required
    latitude      (double)  — required
    longitude     (double)  — required
    operatorName  (string)  — optional

  Link type constraint:
    hasIncident → Incident  — optional
```

**Implementation on Airport object type:**
- `facilityName` maps to `Airport.airportName`
- `latitude` maps to `Airport.lat`
- `longitude` maps to `Airport.lon`
- `operatorName` maps to `Airport.airlineOperator` (optional, mapped)

A TypeScript v2 Function written against `Facility` can now call `.facilityName` and `.latitude` on any returned object, whether it is an Airport, Warehouse, or Data Center, with no type-specific branching.

## How it connects to the rest of Foundry

- **Ontology Manager** — where interfaces are created, extended, and implemented. This is the primary authoring surface.
- **Object types** — interfaces are meaningless without implementing object types; the two are tightly coupled.
- **Shared properties** — interface properties can reference shared property definitions to stay in sync with object type schemas.
- **TypeScript v2 Functions** — the main code surface that can import and call interface API names for polymorphic business logic.
- **Ontology SDK** — generated SDK clients expose interface types for use in external applications.
- **Object Set Service** — cross-type queries via interfaces flow through this service.
- **Actions** — partial support means some action types can target interface-defined object sets.
- **Marketplace** — interfaces are a key packaging primitive; they let Marketplace templates remain object-type-agnostic, so any customer can plug in their own types.
- **Workshop** (future) — not yet fully supported, but the roadmap direction is to allow Workshop widgets to bind to interface types.

## Tips & gotchas for learners

- **Changing required properties is a breaking change.** Any edit to an interface's required properties must be rolled out to all implementing object types at the same time; otherwise implementations break. Plan schema changes carefully, or use optional properties while migrating.
- **Prefer local properties over shared properties** for new interfaces — it keeps the definition self-contained and easier to understand.
- **Use optional properties in Marketplace packages** to avoid forcing downstream customers to update all implementing object types every time you add a new property.
- **Pipeline Builder has limited interface support** — you can implement an interface there, but link type constraint mapping is not available; use Ontology Manager for anything beyond simple property mapping.
- **Interfaces are not Workshop-ready yet** — if your primary target is a Workshop app, you may need to fall back to object-type-specific bindings until Workshop support is complete.
- **One object type can implement many interfaces** — this is encouraged for composability, not an anti-pattern.
- **You cannot instantiate an interface** — there are no "interface objects" in search results; you always get back the concrete object type that implemented it.
- **API names are permanent contracts** — once an interface API name is published and consumed by Functions or SDK clients, renaming it is a breaking change for all consumers.

## Official documentation

- [Interfaces — Overview](https://www.palantir.com/docs/foundry/interfaces/interface-overview)
- [Interfaces — Create an interface](https://www.palantir.com/docs/foundry/interfaces/create-interface)
- [Interfaces — Implement an interface](https://www.palantir.com/docs/foundry/interfaces/implement-interface)
- [Interfaces — Edit an interface definition](https://www.palantir.com/docs/foundry/interfaces/edit-interface-definition)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology — Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [API Reference — Ontology Interface basics](https://www.palantir.com/docs/foundry/api/ontologies-v2-resources/ontology-interfaces/ontology-interface-basics)
