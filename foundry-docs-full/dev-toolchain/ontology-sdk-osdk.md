<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DEV TOOLCHAIN</b><br>
<span style="font-size:22px"><b>Ontology SDK (OSDK)</b></span><br>
<span style="color:#ABB3BF">A generated, type-safe library that gives any application ergonomic read/write access to a Foundry Ontology.</span>
</td></tr></table>

## What it is

The Ontology SDK (OSDK) is a code-generation system built into Foundry that produces a language-native library — TypeScript, Python, Java, or OpenAPI — scoped to exactly the object types, actions, and functions your application needs. Instead of hand-authoring REST calls against Foundry's Ontology API, developers import the generated package and interact with strongly-typed classes that mirror their data model. Because the Ontology lives centrally in Foundry, the SDK always reflects the current schema, and all access is enforced by both the application-scoped token and the end-user's own Foundry permissions.

## How it works

### 1. Define the application in Developer Console

A developer opens **Developer Console** inside their Foundry enrollment and clicks **+ New application**. The console collects the application name, redirect URIs (for OAuth PKCE flows), and the set of Ontology entities the app needs: specific object types, link types, action types, and functions. Only entities explicitly selected here are included in the generated package, which keeps the bundle small and limits the blast radius of any token compromise.

### 2. Code generation

After the entity selection is saved, Foundry generates a versioned SDK package:

- **TypeScript/NPM** — one or more `@osdk/…` scoped packages published to the enrollment's private NPM registry.
- **Python/Pip/Conda** — a wheel published to the enrollment's private PyPI feed.
- **Java/Maven** — a JAR artifact pushed to the enrollment's Maven repository.
- **OpenAPI spec** — a raw `openapi.json` that can target any language via standard tooling.

Each package contains generated classes and interfaces whose names match the Ontology's API names exactly. For example, an object type with API name `Employee` produces a class called `Employee` with typed properties (`employeeId: number`, `department: string`, etc.) and link traversal methods.

### 3. Client initialization and authentication

Applications install the generated package alongside the runtime core (`@osdk/client` for TypeScript). The client is instantiated once with the enrollment's stack URL, the application's client ID, and an auth handler:

```typescript
// TypeScript
import { createClient } from "@osdk/client";
import { createPublicOauthClient } from "@osdk/oauth";

const auth  = createPublicOauthClient(clientId, foundryUrl, redirectUrl);
const client = createClient(foundryUrl, clientId, auth);
```

For Python the pattern is analogous, using `foundry.Client(hostname=..., auth=...)`. The client wraps every outbound call in a bearer token derived from the OAuth flow, ensuring all queries run under the current user's identity.

### 4. Querying objects (runtime data flow)

Object reads follow a fluent/chained builder pattern that compiles down to Foundry's Ontology REST endpoints:

| Operation | TypeScript | Python |
|---|---|---|
| Fetch one by primary key | `client(Employee).fetchOne("e123")` | `client.ontology.objects.Employee.get("e123")` |
| Paginated list | `client(Employee).fetchPage({ $pageSize: 30 })` | `.page(page_size=30)` |
| Async iteration (all pages) | `client(Employee).asyncIter()` | `.iterate()` |
| Filter | `.where({ department: { $eq: "Eng" } })` | `.where(Employee.department == "Eng")` |
| Order | `$orderBy: { department: "asc" }` | `.order_by(Employee.department.asc())` |
| Aggregate | `$count`, `$avg`, `$max`, `$min`, `$sum`, `$approximateDistinct` | `.count()`, `.avg()`, etc. |

Filters compose with `$and`/`$or`/`$not` (TypeScript) or `&`/`|`/`~` (Python). Results for Object Storage V1 (Phonograph) are capped at 10,000 rows; Object Storage V2 has no hard limit.

### 5. Executing actions (write path)

Actions are predefined mutation operations authored in the Ontology. The OSDK exposes each action type as a typed function call:

```typescript
// TypeScript
await client(updateEmployee).applyAction(
  { employeeId: "e123", newDepartment: "Platform" },
  { $returnEdits: true }
);
```

`batchApplyAction()` accepts an array of parameter objects for bulk writes. The `$returnEdits` option returns the set of object RIDs that were created or modified, useful for refreshing UI state. On the Python side, the pattern is `client.ontology.actions.<ActionType>(params)`.

### 6. Calling Functions

Foundry Functions (TypeScript logic compiled and hosted in Foundry) are callable via the SDK:

```typescript
const result = await client(computeRisk).executeFunction({ portfolioId: "p42" });
```

The SDK handles serialization/deserialization; the caller receives a typed return value.

### 7. Link traversal

Generated link types expose helper methods to fetch related objects directly from an object instance, e.g., `employee.manager.fetchOne()` or `employee.reports.fetchPage(...)`, translating to the Ontology's linked-entity endpoints without the caller knowing RID structures.

### 8. Live subscriptions (TypeScript)

The TypeScript OSDK supports real-time object subscriptions that push incremental updates over a WebSocket, enabling reactive UIs without polling.

---

## User interface

The primary OSDK configuration surface is **Developer Console** (a Foundry platform application) and the **OSDK panel inside Slate** (for embedded use cases).

### Developer Console — Application Builder

<table style="background:#1C2127;border:1px solid #383E47;border-collapse:collapse;width:100%">
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;width:30%">UI Area</td>
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold">What you see / do</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Applications list</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Left sidebar. Each app shows its name and OAuth type. <b>+ New application</b> button at top.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Entities panel</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Three collapsible sections: <i>Object Types</i>, <i>Action Types</i>, <i>Functions</i>. Each row has a <b>+</b> button. Selecting a link type auto-adds its required object types.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>API Documentation tab</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Inline API explorer with prefilled <code>@osdk/create-app</code> bootstrap command. Copy-pasteable snippets for each selected entity.</td>
</tr>
<tr>
<td style="padding:8px 12px"><span style="color:#2D72D2"><b>Settings tab</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Client ID, redirect URIs, token scopes, and the package registry endpoint for the generated SDK.</td>
</tr>
</table>

### Slate — OSDK side panel

In Slate's edit mode, a sidebar icon opens the OSDK panel:

- **Ontology dropdown** — select which Ontology to bind.
- **Object/Action/Function sections** — add entities with **+**; unsaved additions glow <span style="color:#C87619"><b>● orange</b></span>.
- **Documentation sidebar** — clicking any entity shows its properties, parameter types, and ready-to-paste code snippets.
- **Regenerate** — available from a dropdown menu after Ontology schema changes. A "View latest generation logs" link surfaces any generation errors (<span style="color:#CD4246"><b>● red</b></span> indicators).
- Removed entities appear <span style="color:#ABB3BF"><b>crossed out</b></span> until the change is saved or reverted.

### Status indicators

<span style="color:#238551"><b>● Generated / up-to-date</b></span> · <span style="color:#C87619"><b>● Unsaved / pending regeneration</b></span> · <span style="color:#CD4246"><b>● Generation failed</b></span> · <span style="color:#2D72D2"><b>● Primary action button</b></span>

---

## Worked example

**Scenario:** A React dashboard shows all open maintenance tickets assigned to a logged-in field technician, lets her close a ticket, and refreshes the count in real time.

1. **In Developer Console** — create app `maintenance-dashboard`, select object type `MaintenanceTicket` and `Technician`, link type `AssignedTechnician`, action type `CloseTicket`. Save; Foundry publishes `@acme/maintenance-dashboard-osdk` to the private NPM registry.

2. **Bootstrap** — run the prefilled CLI command from the API Documentation tab:
   ```bash
   npx @osdk/create-app@latest --foundryUrl https://acme.palantirfoundry.com \
     --clientId abc123 --osdkPackage @acme/maintenance-dashboard-osdk
   ```
   This scaffolds a Vite/React project with auth wired up.

3. **Query on load** — in a React component:
   ```typescript
   const tickets = await client(MaintenanceTicket)
     .where({ status: { $eq: "open" }, assignedTechnicianId: { $eq: currentUser.id } })
     .fetchPage({ $pageSize: 50 });
   ```

4. **Execute action on button click** —
   ```typescript
   await client(CloseTicket).applyAction(
     { ticketId: ticket.primaryKey, resolution: "Fixed on site" },
     { $returnEdits: true }
   );
   ```

5. **Live update** — a subscription listener re-runs the query whenever `MaintenanceTicket` objects change, keeping the open-ticket count badge accurate without a manual refresh.

---

## Documentation map

- **Ontology SDK / Overview** — top-level product overview and language support matrix
- **Ontology SDK / Developer Console / Create a new application** — step-by-step app registration
- **Ontology SDK / TypeScript OSDK** — client init, `fetchOne/fetchPage/asyncIter`, filters, aggregations, actions, functions, subscriptions, migration guide, testing utilities
- **Ontology SDK / Python OSDK** — client init, object retrieval, pagination, ordering, filtering, aggregations, migration guide
- **Ontology SDK / Java OSDK** — Maven setup, Java client patterns
- **Ontology SDK / Build applications / Add OSDK to an existing application** — adding the package to a pre-existing TypeScript project
- **Ontology SDK / Marketplace deployment** — installing OSDK apps via the Foundry Marketplace
- **Slate / Read and write data / Use the Ontology SDK (OSDK) in Slate** — embedding OSDK in Slate dashboards
- **Developer Console / How-to guides / Bootstrap a TypeScript application** — `@osdk/create-app` walkthrough
- **Developer Console / How-to guides / Bootstrap a back-end TypeScript application** — Next.js server-side OSDK usage
- **API Reference / SDKs** — raw OpenAPI endpoint descriptions underlying the SDK
- **Ontology / Overview** — object types, link types, action types, functions, interfaces

---

## Official documentation

- [Ontology SDK — Overview](https://www.palantir.com/docs/foundry/ontology-sdk/overview)
- [Ontology SDK — TypeScript OSDK](https://www.palantir.com/docs/foundry/ontology-sdk/typescript-osdk)
- [Ontology SDK — Python OSDK](https://www.palantir.com/docs/foundry/ontology-sdk/python-osdk)
- [Ontology SDK — Java OSDK](https://www.palantir.com/docs/foundry/ontology-sdk/java-osdk)
- [Ontology SDK — Create a new Developer Console application](https://www.palantir.com/docs/foundry/ontology-sdk/create-a-new-osdk)
- [Ontology SDK — Add OSDK to an existing TypeScript application](https://www.palantir.com/docs/foundry/ontology-sdk/how-to-add-to-existing-typescript)
- [Slate — Use the Ontology SDK (OSDK) in Slate](https://www.palantir.com/docs/foundry/slate/concepts-osdk)
- [Developer Console — Bootstrap a TypeScript application](https://www.palantir.com/docs/foundry/developer-console/how-to-bootstrapping-typescript)
- [Developer Console — Bootstrap a back-end TypeScript application](https://www.palantir.com/docs/foundry/developer-console/how-to-bootstrapping-server-side-typescript)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [API Reference — SDKs](https://www.palantir.com/docs/foundry/api/general/overview/sdks)
