# Ontology — Overview

> The Ontology is Foundry's semantic layer — a structured, digital-twin representation of an organization's real-world entities, relationships, business logic, and actions, built on top of raw integrated data.

## What it is

The Ontology sits above Foundry's raw datasets and acts as an operational layer that maps data to the real world: physical assets (plants, equipment, products) and abstract concepts (customer orders, financial transactions). Rather than forcing users to think in tables and columns, the Ontology lets them work with meaningful business objects like "Aircraft", "Supplier", or "Work Order". It solves the gap between raw data integration and decision-making at scale by providing a shared, governed vocabulary that every Foundry application and tool can build on. Unlike a simple data catalog, the Ontology is designed to represent the *decisions* of an enterprise — not just the data — by embedding logic and actions alongside the objects themselves.

## When to use it

- When you need a shared semantic model that multiple applications, teams, and AI agents can all reference consistently.
- When building operational workflows that must read and write back to source systems (not just report on data).
- When different datasets describe the same real-world entity and need to be unified under one object type.
- When you want to enforce fine-grained security and governance rules on who can see or modify specific objects.
- When building Workshop applications, Quiver analyses, or AIP Logic pipelines that must reason about business entities.
- When enabling human-AI collaboration where agents need structured, trustworthy context about organizational entities.

**When NOT to use it / alternatives:** If you only need to run a one-off data transformation or produce a static report, working directly with datasets and Contour/Code Repositories may be simpler. The Ontology adds value when the same entities need to be reused, acted upon, or governed across many tools.

## Key concepts & terminology

- **Object Type**: The schema (blueprint) for a category of real-world entity — e.g., "Flight", "Employee", "Invoice". Analogous to a table definition.
- **Object**: A single instance of an Object Type — e.g., one specific flight. Analogous to a table row.
- **Property**: A characteristic or field of an Object Type — e.g., `departure_airport` on a Flight. Analogous to a column.
- **Property Value**: The actual data stored in a property for one specific object.
- **Shared Property**: A property defined once and reused consistently across multiple Object Types.
- **Link Type**: The schema for a relationship between two Object Types — e.g., "Flight has Aircraft".
- **Link**: A single instance of a Link Type connecting two specific objects.
- **Action Type**: A defined, transactional operation that modifies objects, property values, or links — e.g., "Reassign Flight". Enforces business rules and can trigger side effects in downstream systems.
- **Function**: A piece of TypeScript/Python code-based logic integrated with the Ontology; can accept objects or object sets as input, read property values, and be used inside Action Types or Workshop apps.
- **Object Set**: A collection of objects, typically filtered by criteria — the primary unit of analysis across Foundry tools.
- **Interface**: An Ontology type describing a common shape (set of properties) shared by multiple Object Types, enabling polymorphism.
- **Object View**: A reusable configuration that aggregates all information, workflows, linked objects, metrics, and dashboards related to a specific object type.
- **Roles**: The permissioning model governing who can access, see, or act on ontological resources at varying levels of granularity.

## Core capabilities / features

**Semantic modeling**
- Define Object Types backed by datasets, virtual tables, or models.
- Attach rich properties and shared properties for cross-type consistency.
- Declare Link Types to capture relationships and dependencies between entity types.
- Use Interfaces to model polymorphism — e.g., multiple asset types that share common properties like `location` or `status`.

**Action layer**
- Action Types define precisely how objects can be changed in a single transaction.
- Actions can trigger write-backs to external operational systems (ERPs, databases) through integrations.
- Users interact with actions in plain business terms — "Approve Order", "Reassign Technician" — without needing to understand the underlying data structure.

**Logic layer (Functions)**
- Functions are code-based logic (TypeScript) natively integrated with the Ontology.
- They can query object sets, read property values, and return computed results.
- Functions power computed properties, action validation logic, and AIP agent reasoning.
- Logic can evolve independently of the data model, enabling continuous improvement.

**Security and governance**
- Granular row- and column-level access controls are applied directly to objects and properties.
- Permissions are inherited and composable across the Ontology graph.
- All changes are governed and traceable, supporting compliance and audit requirements.

**Toolchain and SDK**
- The Ontology SDK lets developers build type-safe applications using Ontology objects directly.
- DevOps tooling supports versioning and deployment of Ontology changes.
- Deep integration with Workshop (apps), Quiver (analysis), Object Explorer (search), and AIP (AI agents).

## How it works / typical workflow

1. **Ingest data**: Connect raw datasets (from pipelines, Fusion, or external sources) into Foundry.
2. **Define Object Types**: In the Ontology Manager, create Object Types that represent key business entities. Map dataset columns to properties.
3. **Declare Link Types**: Define relationships between Object Types (e.g., "Order is placed by Customer").
4. **Configure Shared Properties and Interfaces**: Identify common properties across types; use Interfaces to standardize them.
5. **Define Action Types**: Specify what operations users (or AI agents) can perform — what changes, what validations apply, what side effects fire.
6. **Write Functions**: Implement business logic in TypeScript that operates on object sets and feeds into actions or app computations.
7. **Set Roles and permissions**: Apply row/column-level security so each user or agent sees only what they are allowed to.
8. **Build on the Ontology**: Use Workshop to build operational apps, Quiver for ad-hoc analysis, Object Explorer to search and inspect objects, or AIP to power AI-assisted decision workflows — all referencing the same Ontology layer.

## Example

A logistics company models its supply chain. They create an Object Type `Supplier` (backed by a CRM dataset) with properties like `supplier_name`, `country`, and `on_time_delivery_rate`. They create an Object Type `PurchaseOrder` and a Link Type "PurchaseOrder is fulfilled by Supplier". An Action Type called `Flag Supplier for Review` lets an operations manager mark a supplier as at-risk with a single click, triggering a notification and updating a status property. A Function calculates a dynamic `risk_score` for each supplier by combining on-time delivery data with current open orders. A Workshop application surfaces all of this — the risk scores, the linked orders, and the "Flag" action button — in one screen without any user needing to write SQL.

## How it connects to the rest of Foundry

- **Data Integration / Pipelines**: Raw datasets produced by Code Repositories or Transforms feed directly into Object Type backing sources.
- **Workshop**: Applications built in Workshop consume Ontology objects, object sets, Actions, and Functions as their core data and interactivity model.
- **Quiver**: Analytical tool for ad-hoc exploration of object sets; operates directly on the Ontology.
- **Object Explorer**: Out-of-the-box Foundry interface for searching, filtering, and inspecting objects and their links.
- **AIP (AI Platform)**: AI agents and Logic pipelines use the Ontology as their structured context — reading objects, calling Functions, and invoking Actions to close decision loops.
- **Ontology SDK**: Exposes Ontology types and operations to custom application code in a type-safe way, bridging Foundry and external developer tools.
- **Security / Roles**: Foundry's platform-level access controls integrate tightly with Ontology Roles, ensuring consistent governance across all consuming tools.

## Tips & gotchas for learners

- **The Ontology ≠ a database.** It is a semantic layer over your data, not a place to store raw data. Always back Object Types with upstream datasets.
- **Object Types mirror dataset structure.** Think of Object Types as "smart views" on datasets — an Object Type is like a dataset, an object is like a row, a property is like a column.
- **Link Types require careful design.** Many-to-many relationships need explicit cardinality decisions upfront; changing link structure later can affect downstream apps.
- **Actions enforce business rules, not just data edits.** Always think about validation logic and side effects when designing Action Types — they are transactions, not simple form submissions.
- **Functions are versioned and deployed.** Treat Functions like production code: test them, version-control them, and be mindful of performance when operating over large object sets.
- **Interfaces are optional but powerful.** Use them once you have multiple Object Types sharing common semantics (e.g., multiple asset types); they simplify app development significantly.
- **Permissions apply at the Ontology level.** A user who cannot see a property in the Ontology cannot see it anywhere — in Workshop, Quiver, or via the SDK — making the Ontology the single source of security truth.
- **Start small.** New users should begin with one or two Object Types and a simple Action before expanding. A bloated Ontology with hundreds of unmaintained object types is harder to govern.

## Official documentation

- [Ontology Overview — Palantir Foundry](https://www.palantir.com/docs/foundry/ontology/overview)
- [Core Concepts — Palantir Foundry Ontology](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Why Create an Ontology? — Palantir Foundry](https://www.palantir.com/docs/foundry/ontology/why-ontology)
- [The Ontology System — Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/ontology-system)
- [Action Types Overview — Palantir Foundry](https://www.palantir.com/docs/foundry/action-types/overview)
