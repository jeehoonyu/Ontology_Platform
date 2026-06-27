<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Functions on Objects</b></span><br>
<span style="color:#ABB3BF">Server-side TypeScript or Python logic that reads, aggregates, and edits ontology objects in a type-safe, Foundry-managed execution environment.</span>
</td></tr></table>

## What it is

**Functions on Objects** (often abbreviated **FOO**) is a Foundry capability that lets developers write server-side functions — in TypeScript or Python — whose parameters and return values are first-class ontology objects, object sets, links, and properties. Functions run inside isolated Foundry execution environments and can be surfaced in Workshop applications, Action types, and other platform consumers. Because object types and link types are imported as generated TypeScript interfaces or Python classes, the compiler enforces correctness at author time, before any code ships to production.

---

## How it works

### 1. Define and import ontology types

Every function that touches ontology data starts in a **Functions repository** (TypeScript or Python). The developer opens the <span style="color:#8ABBFF">Resource Imports</span> sidebar inside Foundry's in-browser IDE, clicks **Add**, selects the ontology to target, and checks off the object types, interface types, and link types the function needs. Clicking **Save** triggers **Code Assist** to restart and regenerate the `@foundry/ontology-api` package bindings — strongly-typed interfaces for every imported type. For private ontologies the package is scoped: `@foundry/ontology-api/<ontology-api-name>`.

### 2. Write the function

A read-only function uses the `@Function()` decorator; a function that mutates objects uses `@OntologyEditFunction()` (TypeScript v1), `createEditBatch` from `@osdk/functions` (TypeScript v2), or the `@function(edits=...)` pattern with `FoundryClient` (Python). Parameters are typed directly against the generated interfaces:

```typescript
import { Airport } from "@foundry/ontology-api";

@Function()
public airportLocation(airport: Airport): string {
    return `${airport.city}, ${airport.country}`;
}
```

Properties are accessed via dot notation. Because a property may not be set, values can return `undefined`. Array properties come back as `ReadOnlyArray`; to mutate them the developer must copy the array first.

### 3. Traverse links between objects

Link types become fields on the generated object interface. The traversal API differs by cardinality:

- **Single links** (one-to-one, many-to-one) — `employee.manager.get()` / `getAsync()`, returns the linked object or `undefined`.
- **Multi-links** (one-to-many, many-to-many) — `employee.reports.all()` / `allAsync()`, returns a `ReadOnlyArray` (empty if no links exist).
- **ObjectSet bulk traversal** — `employeeObjectSet.searchAroundToOtherObjectType()` fetches linked objects without loading individual instances first, which is significantly faster than iterating over individual object instances.

### 4. Search, filter, and aggregate

`Objects.search()` returns an `ObjectSet` that can be filtered, sorted, paginated, and aggregated server-side before results are returned to the caller. Because object search uses a snapshot of data taken *before* the function runs, newly created or modified objects within the same execution are not visible to subsequent searches in the same call.

### 5. Test in live preview

The in-browser **Functions Helper** lets a developer invoke any published or unpublished function against live data. When an `@OntologyEditFunction` is run in the helper during authoring, **edits are not applied** to real objects — the environment is sandboxed for safe iteration. Permissions on object types in live preview are governed by the repository's permissions on the backing datasources for each object type.

### 6. Publish and connect

After validating, the developer commits code and creates a **version tag** from the Branches tab. The published function becomes available platform-wide and can be wired to:

- **Workshop** widgets and application logic (read functions that return computed values or object sets).
- **Action types** as **function-backed actions** — the action invokes an `@OntologyEditFunction`, which applies creates, updates, or deletes to real objects when triggered from a production context.

### 7. Ontology edits in production

When an action backed by a function runs in production, the edit batch is applied transactionally. Edits cover: creating new objects, modifying property values, creating/deleting links between objects, and deleting objects. The `@Edits` decorator (TypeScript v1) or `Edits` type (TypeScript v2) carries **action provenance** metadata so every edit is traceable back to its triggering action.

---

## User interface

Functions on Objects are authored and managed inside the **Foundry in-browser IDE** (the Functions repository editor). The layout has three primary zones:

<table style="background:#1C2127;border:1px solid #383E47;border-collapse:collapse;width:100%">
<tr style="background:#252A31">
  <th style="color:#8ABBFF;padding:8px 12px;text-align:left">Zone</th>
  <th style="color:#8ABBFF;padding:8px 12px;text-align:left">What you see</th>
</tr>
<tr>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#FFFFFF"><span style="color:#2D72D2"><b>Resource Imports sidebar</b></span></td>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#ABB3BF">Lists all imported object types, link types, and interface types. An <b>Add</b> button opens a search modal for the ontology. Saving auto-restarts Code Assist.</td>
</tr>
<tr>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#FFFFFF"><span style="color:#2D72D2"><b>Code editor (center)</b></span></td>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#ABB3BF">Full TypeScript or Python editor with Code Assist providing autocomplete on object properties and link names. <code>Ctrl</code>+click on <code>@foundry/ontology-api</code> navigates to the generated <code>index.ts</code> listing all available types.</td>
</tr>
<tr>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#FFFFFF"><span style="color:#2D72D2"><b>Functions Helper (right panel)</b></span></td>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#ABB3BF">Live-preview panel. Select any <code>@Function()</code> or <code>@OntologyEditFunction()</code>, supply inputs (object pickers, text fields), and run against real data. Edit functions execute in a sandbox — no real writes occur during authoring.</td>
</tr>
<tr>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#FFFFFF"><span style="color:#2D72D2"><b>Branches tab</b></span></td>
  <td style="padding:8px 12px;border-top:1px solid #383E47;color:#ABB3BF">Branch management and version tagging. Published version tags make functions available to Workshop, Action types, and other platform consumers.</td>
</tr>
</table>

**Status indicators in the platform:**

<span style="color:#238551"><b>● published</b></span> · <span style="color:#C87619"><b>● draft / unpublished</b></span> · <span style="color:#CD4246"><b>● build error</b></span> · <span style="color:#2D72D2"><b>● live preview active</b></span>

---

## Worked example

**Scenario:** Round-robin assignment of security alerts to analysts.

1. In a TypeScript Functions repository, the developer imports two object types via the Resource Imports sidebar: `SecurityAlert` and `Analyst`.
2. Code Assist regenerates `@foundry/ontology-api` with typed interfaces for both.
3. The developer writes an `@OntologyEditFunction()` that calls `Objects.search()` to retrieve all `Analyst` objects, iterates over all unassigned `SecurityAlert` objects, and assigns each alert to an analyst using modulo indexing — distributing load evenly.
4. The function is run in the **Functions Helper** against live data. Alerts appear to be assigned in the preview output, but no real objects are modified.
5. After committing and tagging a version, the function is connected to an **Action type** called "Assign Alerts Round-Robin."
6. When a Foundry user triggers that action from a Workshop dashboard, the function executes in production: each `SecurityAlert` object's `assignedAnalyst` property is updated, and all changes are recorded with action provenance metadata.

---

## Documentation map

The following sub-pages sit beneath the Functions on Objects section of the Foundry docs:

- **Getting started** — workflow overview, first function, live preview walkthrough
- **Import object, interface, and link types** — Resource Imports sidebar, ontology selection, multi-type import, private ontologies
- **Objects and Links API** — property access, `SingleLink` / `MultiLink` traversal, `ReadOnlyArray` semantics, ontology metadata API
- **Object Sets API** — `Objects.search()`, `searchAround()`, filters, aggregations
- **Ontology edits (language-agnostic overview)** — edit lifecycle, transactionality, provenance
- **TypeScript v1: Ontology edits** — `@OntologyEditFunction`, `@Edits` decorator
- **TypeScript v2: Ontology edits** — `createEditBatch`, `Edits` type from `@osdk/functions`
- **Python: Ontology edits** — `FoundryClient`, `@function(edits=...)` pattern
- **Function-backed actions: Getting started** — connecting edit functions to Action types
- **Permissions** — datasource-level permissions in live preview and production
- **Unit testing** — testing framework for Functions repositories
- **Use functions in platform** — Workshop integration, embedding in applications

---

## Official documentation

- [Functions on Objects — Getting started](https://www.palantir.com/docs/foundry/functions/foo-getting-started)
- [Functions — Import object, interface, and link types](https://www.palantir.com/docs/foundry/functions/ontology-imports)
- [Functions — Objects and Links API](https://www.palantir.com/docs/foundry/functions/api-objects-links)
- [Functions — Language-agnostic ontology edits overview](https://www.palantir.com/docs/foundry/functions/edits-overview)
- [Code examples — Common operations: Functions on Objects](https://www.palantir.com/docs/foundry/code-examples/common-operations-functions-on-objects)
- [Action types — Function-backed actions: Getting started](https://www.palantir.com/docs/foundry/action-types/function-actions-getting-started)
- [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)
