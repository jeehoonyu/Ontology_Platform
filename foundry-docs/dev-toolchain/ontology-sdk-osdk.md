# Ontology SDK (OSDK)

> The Ontology SDK (OSDK) generates strongly-typed SDKs — in TypeScript, Python, and Java — directly from your Ontology, so external applications can read objects, traverse links, and invoke Actions and Functions with full type safety.

## What it is

The OSDK turns your Ontology into code. Instead of hand-writing REST calls, you generate a typed client where every object type, link, Action, and Function becomes a typed method. Built and managed through **Developer Console**, the OSDK is the foundation for custom applications (often React/TypeScript) that sit on top of Foundry's semantic layer while respecting its permissions and governance.

## When to use it

- You're building a custom application (web, backend, data science) that uses Ontology data.
- You want type-safe, autocomplete-friendly access to objects, Actions, and Functions.
- You need programmatic writeback to the Ontology via Actions from outside Foundry.

**When NOT to use it / alternatives:** For no-code operational apps use **Workshop**. For raw, untyped access use the **platform REST APIs**. For in-platform logic use **Functions** directly.

## Key concepts & terminology

- **OSDK** — A generated, typed SDK specific to your Ontology version.
- **Developer Console** — The app for creating SDK-backed applications, OAuth clients, and generating SDKs.
- **OAuth client** — The registered credential an external app uses to authenticate.
- **Object set** — A typed, queryable collection of objects in the SDK.
- **Action** — A typed method that performs governed writeback.
- **Query / Function** — Typed methods exposing Ontology Functions.
- **Versioning** — SDKs are generated against a specific Ontology version for stability.

## Core capabilities / features

- **Typed access in TS/Python/Java** — Objects, properties, links, Actions, and Functions as typed code.
- **Object set operations** — Filter, search, paginate, and aggregate object sets.
- **Link traversal** — Navigate relationships with type safety.
- **Action invocation** — Trigger governed writeback (create/edit/delete) from your app.
- **Function calls** — Invoke Ontology Functions, including AIP Logic functions.
- **OAuth & permissions** — Apps authenticate via OAuth and inherit Foundry governance.
- **Developer Console workflow** — Generate, version, and manage SDKs and clients in one place.

## How it works / typical workflow

1. In **Developer Console**, create an application and register an **OAuth client**.
2. Select the object types, Actions, and Functions to expose.
3. **Generate the OSDK** for your language (TS/Python/Java).
4. Install the package and authenticate via OAuth.
5. Query object sets, traverse links, and invoke Actions/Functions in code.
6. Deploy your app; updates regenerate the SDK against the chosen Ontology version.

## Example

```typescript
import { client } from "./osdk";
import { Order } from "@my-ontology/sdk";

// Fetch recent high-value orders
const orders = await client(Order)
  .where({ orderTotal: { $gt: 1000 } })
  .fetchPage({ $pageSize: 25 });

// Invoke a governed Action (writeback)
await client(Order.actions.markShipped).applyAction({ order: orders.data[0] });
```

## How it connects to the rest of Foundry

- **Ontology** — The OSDK is generated from object types, links, Actions, and Functions.
- **Developer Console / Code Workspaces** — Where OSDK apps are built.
- **Actions / Functions** — Exposed as typed methods for writeback and logic.
- **Platform APIs** — The lower-level alternative the OSDK builds upon.
- **AIP** — Logic functions can be invoked through the SDK.

## Tips & gotchas for learners

- **Pin the Ontology version** your SDK targets for stable apps; regenerate intentionally.
- **Apps inherit permissions** — users only see objects/Actions they're authorized for.
- **Writeback goes through Actions** — you can't bypass governance to edit objects directly.
- **Developer Console is the hub** — OAuth clients and SDK generation live there.
- **Choose OSDK over raw REST** when you want type safety and maintainability.

## Official documentation

- [Ontology SDK: Overview](https://www.palantir.com/docs/foundry/ontology-sdk/overview)
- [Dev toolchain: Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
- [Functions: Overview](https://www.palantir.com/docs/foundry/functions/overview)
