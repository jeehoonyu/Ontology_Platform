# Link Types

> A link type is the schema definition of a relationship between two object types in the Foundry Ontology, enabling objects to be connected and traversed like a knowledge graph.

## What it is

A link type defines *how* two object types are related — the same role a foreign-key constraint or join plays in a relational database, but elevated to the semantic layer of the Ontology. While object types represent real-world entities (e.g., `Employee`, `Company`), link types capture the relationships between them (e.g., "works for"). A **link** (lowercase) is a single instance of that relationship between two specific objects. Link types live in the Ontology Manager and are governed, versioned, and secured the same way as object types.

## When to use it

- You need to navigate from one object to a related object in Workshop apps, Object Explorer, or Functions (e.g., click an Employee to see their Employer).
- Your data model includes parent-child hierarchies (e.g., Order → Line Item), network graphs (e.g., Person → Person), or many-to-many associations (e.g., Employee → Project).
- You want Functions or actions to traverse relationships programmatically via the Ontology API.
- You are representing an entity-relationship (ER) model inside Foundry, replacing raw dataset joins with governed semantic connections.

**When NOT to use it:** If you simply need to join datasets for a pipeline output, a Transforms join is sufficient. Link types add value when the relationship needs to be queryable, traversable, and visible across Foundry applications. Also note: links between object types in *different* Ontologies are not supported — use a shared Ontology instead.

## Key concepts & terminology

- **Link type** — The schema (template) defining a relationship category between two object types (e.g., `employee-employer`).
- **Link** — A single instance of that relationship between two specific objects (e.g., Alice → Acme Corp).
- **Cardinality** — Whether each side of the relationship holds one or many objects. Cardinality is set per-side: `one` or `many`.
- **One-to-many** — One object on side A links to many objects on side B (e.g., one Company has many Employees). Backed by a foreign key on the "many" side.
- **Many-to-many** — Many objects on side A link to many objects on side B (e.g., Employees ↔ Projects). Backed by a separate join-table dataset.
- **Foreign key** — A property on one object type whose value matches the primary key of a related object type; used to back one-to-one and one-to-many link types.
- **Join dataset (join table)** — A dedicated dataset containing pairs of primary keys, one column per object type; required to back many-to-many link types.
- **Object-backed link** — A many-to-one link that uses a third intermediary object type (with its own properties) to store metadata about the relationship itself.
- **Traversal** — Navigating from one object to its linked objects at query or application runtime, chaining multiple link hops if needed.
- **API name** — The programmatic identifier for a link direction, used in Functions (e.g., `employee.employer.get()`). Must start lowercase, alphanumeric, 1–100 characters.
- **Visibility** — Controls how prominently a link appears in apps: `prominent`, `normal`, or `hidden`.

## Core capabilities / features

- **Three backing strategies:**
  - *Object type foreign keys* — For one-to-one or many-to-one cardinality. One property on an object type acts as a foreign key pointing to the primary key of another object type. No extra dataset needed.
  - *Join table dataset* — For many-to-many cardinality. A dataset with at least two columns (one per object's primary key) defines all link pairs. Foundry can auto-generate the join table schema.
  - *Backing object type* — For many-to-one relationships that carry extra metadata. An intermediary object type stores details about each connection, connected to both endpoints via their own link types.

- **Bidirectional naming** — Each link type has two directions, each with its own display name, plural display name, and API name (e.g., `worksFor` on the Employee side, `hasEmployee` on the Company side).

- **Cardinality metadata** — Applications use cardinality to know whether to render a single linked object or a list. For example, in `Employee → Employer`, Employee has cardinality `many` and Company has cardinality `one`.

- **Status lifecycle** — Link types carry a status flag (`active`, `experimental`, `deprecated`) to communicate maturity to consumers.

- **Governance and security** — Like object types, link types are versioned in the Ontology and subject to the same granular access controls.

- **Cross-application traversal** — Once defined, links are explorable in Object Explorer, queryable via Ontology SQL (many-to-many links require the join table to be registered in Ontology Manager before they appear in SQL), and traversable in Workshop app object set cards by chaining multiple link hops.

## How it works / typical workflow

1. **Open Ontology Manager** — Navigate to the Ontology Manager application in your Foundry enrollment.
2. **Initiate creation** — Select **New → Link type** (top right), or from an existing object type's overview page choose **Create new link type**.
3. **Choose relationship type** — Pick from *Object type foreign keys* (one-to-one/many-to-one), *Join table dataset* (many-to-many), or *Backing object type* (relationship with metadata).
4. **Define link resources:**
   - *Foreign key:* Select the two object types. Map the foreign key property on one to the primary key property on the other.
   - *Join dataset:* Select both object types and the join-table dataset. Map each dataset column to the appropriate object type's primary key.
   - *Object-backed:* Select two endpoint object types and one intermediary object type, then specify the existing many-to-one links connecting each endpoint to the intermediary.
5. **Name each direction** — Provide human-readable display names and review/edit the auto-generated API names for both link directions.
6. **Save location** — Choose a Foundry project to save the link type into, then click **Save** to commit changes to the Ontology.
7. **Verify in Object Explorer** — Navigate to an object instance and confirm that linked objects appear under the new link type.

## Example

**Scenario:** An HR dataset has an `employees` table with an `employer_id` column pointing to a `companies` table. You want Workshop users to click any Employee and see their Employer.

1. Object types `Employee` (primary key: `employee_id`) and `Company` (primary key: `company_id`) already exist.
2. The `employees` dataset has a column `employer_id` exposed as an `employerId` property on `Employee`.
3. In Ontology Manager, create a new link type using **Object type foreign keys**.
4. Set *source object type* = `Employee`, *foreign key property* = `employerId`; set *target object type* = `Company`, *primary key property* = `companyId`.
5. Name the directions: Employee side → `worksFor` (display: "Employer"), Company side → `hasEmployee` (display: "Employees").
6. Set cardinality: Employee = `many`, Company = `one`.
7. Save. In a Workshop app, an object set card for Employees can now be chained with a "traverse `worksFor`" card to display each employee's company.

In Functions, the link is accessible as:
```typescript
// Traverse from an Employee object to its linked Company
const employer = employee.worksFor.get();
```

## How it connects to the rest of Foundry

- **Ontology Manager** — The authoring environment where link types are created, versioned, and governed alongside object types and action types.
- **Object Explorer** — Uses link types to let analysts pivot between related objects interactively without writing code.
- **Workshop** — Object set cards can chain link traversals to filter or display related objects in apps.
- **Functions** — The Ontology TypeScript SDK exposes link type API names as first-class methods on object instances, enabling programmatic traversal.
- **Ontology SQL** — Many-to-many link types (backed by join tables) can be queried via SQL once registered in Ontology Manager.
- **Action types** — Actions can add or remove links between objects (e.g., assign an employee to a project), keeping the link data updated.
- **Pipeline Builder** — Ontology outputs in Pipeline Builder create or update the backing datasets (foreign key columns or join tables) that link types read from.
- **AIP / Agents** — Link types enrich the semantic context available to AI logic by exposing graph-structured relationships.

## Tips & gotchas for learners

- **One datasource per link type** — A dataset or branch cannot back multiple link types. Attempting this raises the error `Phonograph2:DatasetAndBranchAlreadyRegistered`. Keep join tables dedicated to a single link type.
- **Cross-Ontology links are not supported** — If two object types live in separate Ontologies, you cannot link them directly. Consolidate into a shared Ontology if traversal is needed.
- **API names are permanent after publication** — Choose API names carefully; they are used in Functions code and changing them later breaks existing code.
- **Cardinality is informational, not enforced** — Cardinality guides how applications display links (single value vs. list) but Foundry does not enforce it at the data level. Incorrect cardinality leads to misleading UI behavior.
- **Many-to-many in SQL requires explicit registration** — The join table must be registered in Ontology Manager before the link appears in Ontology SQL queries.
- **Self-referential links are valid** — You can link an object type to itself (e.g., `Manager → DirectReport` on the same `Employee` type), which is useful for hierarchies and org charts.
- **Status flag matters for consumers** — Mark experimental link types as `experimental` to signal that the schema may change, preventing downstream Functions or apps from taking hard dependencies prematurely.

## Official documentation

- [Link types overview](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview)
- [Create a link type](https://www.palantir.com/docs/foundry/object-link-types/create-link-type)
- [Link type metadata reference](https://www.palantir.com/docs/foundry/object-link-types/link-type-metadata)
- [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Functions: Objects and links API](https://www.palantir.com/docs/foundry/functions/api-objects-links)
