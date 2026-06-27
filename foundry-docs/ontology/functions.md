# Functions (Functions on Objects)

> Foundry Functions are server-side TypeScript or Python routines that read from—and optionally write to—the Ontology, powering computed values, custom aggregations, and complex multi-object edits across platform applications.

## What it is

Functions let code authors embed business logic directly into the Foundry Ontology layer, so that logic runs on the server and is reusable across Workshop, Slate, Quiver, and Action types. Instead of hard-coding calculations inside each application widget, you write the logic once as a Function and reference it wherever it is needed. Functions integrate tightly with object types and link types, giving them typed, autocomplete-friendly access to Ontology data. They solve two related problems: running read-only computations (queries) that return transformed or aggregated values, and running write operations (Ontology edit functions) that update objects when triggered by an Action.

## When to use it

- You need a derived column in a Workshop table whose value is computed per-row from object properties.
- You want a chart aggregation in Workshop or Quiver that changes dynamically based on user selections.
- You need to express a complex edit that touches many objects at once (e.g., bulk status updates) through a function-backed action.
- You want to expose a read-only computation to external callers through the API gateway (query functions with an `apiName`).
- You need to enrich Ontology objects by calling an external system via a webhook.
- You are running background automation in Automate where logic must execute asynchronously for up to 4 hours.

**When NOT to use it / alternatives:** If your logic is a simple, static property derivation that never changes, a derived property defined directly on the object type may be simpler. If you only need to move or transform raw data between datasets (not Ontology objects), use Pipeline Builder transforms instead.

## Key concepts & terminology

- **Function**: A TypeScript or Python method annotated with a decorator that makes it discoverable and executable by the platform.
- **Functions on Objects (FoO)**: The specific pattern of writing Functions that import Ontology object types and operate on them directly.
- **Query function**: A read-only Function (no side effects). Can optionally be exposed through the API gateway by giving it an `apiName`.
- **Ontology Edit Function**: A Function that returns Ontology edits (creates, modifies, or deletes objects). Used exclusively through function-backed actions.
- **Function-backed action**: An Action type whose logic is implemented by a published Ontology Edit Function rather than by simple rule configuration.
- **Decorator**: A TypeScript annotation (e.g., `@Function()`, `@OntologyEditFunction()`, `@Query()`) that marks a method's role and publishability.
- **Resource Imports**: A sidebar in the TypeScript repository used to import object types, link types, and interface types so the function can reference them with full type safety.
- **Tag / publish**: The act of committing code and publishing a versioned tag so the function is available to the rest of the platform.
- **OSDK (Ontology SDK)**: The SDK used in TypeScript v2 and Python functions that provides typed access to Ontology objects and is compatible with Developer Console.

## Core capabilities / features

- **Two supported languages**: TypeScript (v1 and v2) and Python (beta). TypeScript v2 and Python use the OSDK; TypeScript v1 uses older decorator patterns. A feature-support matrix documents which capabilities are available per language/version.
- **Read object properties and traverse links**: Once object types are imported, you access properties with dot notation and trigger autocomplete in the IDE. Link traversals return related objects or object sets.
- **Return computed values**: Functions can return primitive values, structured objects, object sets, or aggregated numbers, which downstream widgets consume directly.
- **Object Set operations**: Functions support searching, filtering, and aggregating over object sets for use in Workshop charts or table columns.
- **Ontology edits**: Using `@OntologyEditFunction` (v1), `createEditBatch` (v2), or the `FoundryClient` (Python), functions can create, modify, or delete objects. These edits only take effect when the function is wired to an action type.
- **Function-backed Workshop variables**: Most Workshop variables can be backed by a Function so they recompute automatically when their inputs change.
- **Function-backed table columns**: Object Table widgets support per-row computed columns that recalculate on the fly as users scroll.
- **Function-backed chart aggregations**: XY charts and Quiver object set plots derive aggregated values on demand using a Function.
- **Function-backed actions**: A published Ontology Edit Function is attached to an action type in the Rules section; action parameters are auto-generated from the function's inputs.
- **API gateway exposure (query functions)**: Read-only functions with an `apiName` are callable from external systems via the Foundry API gateway. API names must be lowerCamelCase, unique across imported Ontologies, and under 100 characters.
- **Notifications and webhooks**: Functions compute notification recipients and webhook parameters for action side effects.
- **Automate integration**: Functions can be triggered automatically on schedule or on event, running asynchronously for up to 4 hours.
- **Marketplace distribution**: Published functions can be packaged and distributed as Marketplace products.
- **Version management**: Actions pin to a specific function version by default; auto-upgrade can be enabled for semantic-version ranges, but is disabled for `0.y.z` unstable versions.

## How it works / typical workflow

1. **Create a TypeScript (or Python) repository** using the "functions on objects" template in Foundry's code authoring environment.
2. **Import object types** via the Resource Imports sidebar. The platform regenerates typed bindings automatically after each import.
3. **Write your function method** and annotate it with the appropriate decorator: `@Function()` for a read query, or `@OntologyEditFunction()` for a write operation.
4. **Test with Live Preview**: Open the Functions helper, switch to Live Preview, select a real object instance, and run the function to see its output. Datasource permissions follow the repository's access rules.
5. **Commit and publish a tag** via the Branches tab to make the function available to the rest of the platform.
6. **Wire it into the platform**: Reference the published function from a Workshop variable, table column, chart aggregation, action type rule, or Slate document.
7. **Manage versions**: When you update logic, publish a new tag and manually upgrade any action type rules that pin to a specific version (or enable auto-upgrade for stable semantic versions).

## Example

A simple query function that formats an airport's location from its Ontology object properties:

```typescript
import { Function } from "@foundry/functions-api";
import { Airport } from "@foundry/ontology-api";

export class AirportFunctions {
  @Function()
  public airportLocation(airport: Airport): string {
    return `${airport.city}, ${airport.country}`;
  }
}
```

After tagging and publishing, a Workshop Object Table can use `airportLocation` as a function-backed column. Each row calls the function with that row's `Airport` object, and the computed string appears in the cell.

For an edit example, annotating the method with `@OntologyEditFunction()` instead of `@Function()` lets an Action type call the same pattern to update object properties in the Ontology when a user submits a form.

## How it connects to the rest of Foundry

- **Ontology**: Functions are defined as part of the Ontology layer. They import object types and link types, making the Ontology the data contract for all function logic.
- **Action types**: Ontology Edit Functions are the engine behind function-backed actions, which are configured in the Action Types builder.
- **Workshop**: Workshop variables, Object Table columns, and XY chart aggregations all have native "function-backed" modes that call published Functions.
- **Slate and Quiver**: Slate documents can include Function references via the Platform tab; Quiver supports function-backed aggregations in object set plots.
- **Automate**: Functions are a first-class execution target for automated workflows and scheduled jobs.
- **API gateway**: Query functions with an `apiName` become callable REST endpoints, bridging Foundry logic to external consumers.
- **Pipeline Builder**: Functions are distinct from pipeline transforms — pipelines process raw datasets, while Functions operate on Ontology objects. However, Functions can be used as sidecar containers in Pipeline Builder for specialized use cases.
- **Developer Console / OSDK**: TypeScript v2 and Python functions use the OSDK, which integrates with Developer Console for local development and testing.

## Tips & gotchas for learners

- **Edit functions never run standalone**: Running an Ontology Edit Function in the authoring helper does NOT actually modify objects. The only path to real edits is through a configured action type.
- **Search lag after edits**: `Objects.search()` inside an edit function reflects the pre-edit state of the Ontology. If your function edits an object and then immediately searches for it, the search will not see the change.
- **Optional arrays vs. undefined**: In the code repository, optional array properties are `undefined`, but when the function is called through an action at runtime, they arrive as empty arrays. Write defensive checks for both cases.
- **API name versioning**: Query functions exposed through the API gateway always resolve to the latest tagged version — they do not follow semver the way internal function references do. Use separate API names (e.g., `myFunctionV2`) to support multiple versions simultaneously without breaking existing callers.
- **Function-backed actions cannot mix rule types**: A single action type cannot combine a function rule with other Ontology rule types. Design your action to be fully function-backed or fully rule-based.
- **Language choice matters**: Check the official feature-support matrix before committing to a language/version. Not all capabilities (e.g., certain edit patterns, external function calls) are available in every combination.
- **Permissions follow the repository**: During Live Preview testing, access to backing datasources is governed by the TypeScript repository's own datasource permissions, not the calling user's personal permissions.

## Official documentation

- [Functions: Overview](https://www.palantir.com/docs/foundry/functions/overview)
- [Functions on Objects: Getting Started](https://www.palantir.com/docs/foundry/functions/foo-getting-started)
- [Query Functions: Publish and Call via API Gateway](https://www.palantir.com/docs/foundry/functions/query-functions)
- [Ontology Edits](https://www.palantir.com/docs/foundry/functions/edits-overview)
- [Function-Backed Actions: Getting Started](https://www.palantir.com/docs/foundry/action-types/function-actions-getting-started)
- [Use Functions in the Platform](https://www.palantir.com/docs/foundry/functions/use-functions)
- [Feature Support by Language](https://www.palantir.com/docs/foundry/functions/language-feature-support)
- [Manage Published Functions](https://www.palantir.com/docs/foundry/functions/manage-functions)
- [Ontology Overview](https://www.palantir.com/docs/foundry/ontology/overview)
