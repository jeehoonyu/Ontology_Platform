# Platform APIs & SDKs

> Foundry's platform APIs are REST endpoints (with official Python and TypeScript SDKs) for programmatically working with datasets, the Ontology, administration, orchestration, SQL, and more.

## What it is

Beyond the typed, Ontology-specific OSDK, Foundry exposes general-purpose **REST APIs** and **platform SDKs** for automating the platform itself. These let external systems and scripts read/write datasets, query the Ontology, manage files and permissions, trigger builds, run SQL, and administer resources. They're the integration layer for anything that needs to talk to Foundry from outside.

## When to use it

- You need to automate Foundry operations (uploads, builds, admin) from scripts/CI.
- You're integrating an external system that isn't an Ontology app.
- You want raw, flexible access where a typed OSDK isn't necessary.

**When NOT to use it / alternatives:** For typed Ontology access in an app, prefer the **OSDK**. For in-platform logic, use **Functions** and **transforms**.

## Key concepts & terminology

- **REST API** — HTTP endpoints for platform capabilities (datasets, ontology, admin, SQL, orchestration, media).
- **Platform SDK** — Official Python and TypeScript libraries wrapping the REST APIs.
- **Token / OAuth** — Authentication via user tokens or OAuth clients.
- **RID** — Resource Identifier; the canonical ID of any Foundry resource.
- **Orchestration API** — Endpoints to trigger and monitor builds/schedules.
- **SQL API** — Run SQL queries against Foundry data programmatically.

## Core capabilities / features

- **Datasets API** — Read/write datasets, manage transactions, branches, and files.
- **Ontology API** — Query objects, traverse links, apply Actions, call Functions.
- **Admin API** — Manage users, groups, and organization resources.
- **Orchestration API** — Trigger builds and inspect schedules/jobs.
- **SQL API** — Execute SQL queries over datasets/Ontology.
- **Connectivity & media APIs** — Manage sources, syncs, and media sets.
- **Official SDKs** — Python and TypeScript packages that simplify auth and calls.

## How it works / typical workflow

1. **Obtain credentials** — a user token or an OAuth client (via Developer Console).
2. **Choose an interface** — raw REST, or the Python/TypeScript platform SDK.
3. **Call the relevant API** — e.g., upload a file, query objects, trigger a build.
4. **Handle RIDs and pagination** in responses.
5. **Automate** within CI, external apps, or scheduled scripts.

## Example

```python
from foundry_sdk import FoundryClient   # official platform SDK (illustrative)

client = FoundryClient(token=TOKEN, hostname="my-stack.palantirfoundry.com")

# Read objects from the Ontology
orders = client.ontology.objects.Order.where(status="OPEN").take(50)

# Trigger a build via the orchestration API
client.orchestration.builds.create(target="ri.foundry.main.dataset.123")
```

## How it connects to the rest of Foundry

- **OSDK** — Built on top of these platform APIs, adding Ontology-specific typing.
- **Datasets / Transforms** — Programmatic dataset and build management.
- **Ontology** — Object/Action/Function access for external integrations.
- **Developer Console** — Issues OAuth clients used for API auth.
- **Security** — All access respects markings, permissions, and audit logging.

## Tips & gotchas for learners

- **OSDK vs platform API** — typed Ontology app → OSDK; general automation → platform API.
- **Guard credentials** — use scoped OAuth clients, not long-lived personal tokens, for apps.
- **Everything has an RID** — learn to find and pass resource identifiers.
- **Respect rate limits** and paginate large result sets.
- **API access is audited** and governed exactly like UI access.

## Official documentation

- [API: General overview / introduction](https://www.palantir.com/docs/foundry/api/general/overview/introduction)
- [Ontology SDK: Overview](https://www.palantir.com/docs/foundry/ontology-sdk/overview)
- [Dev toolchain: Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
