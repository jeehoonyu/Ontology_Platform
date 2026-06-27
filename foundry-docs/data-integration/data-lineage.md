# Data Lineage

> Data Lineage is Foundry's interactive graph for visualizing how datasets, pipelines, and objects depend on one another — and for diagnosing builds and assessing the impact of changes.

## What it is

As pipelines grow, it becomes hard to know what feeds what. Data Lineage renders the entire dependency graph: raw datasets flow into transforms, which produce derived datasets, which back object types, which feed applications. Each node shows build status and health, so you can trace a problem from a broken dashboard back to the failing upstream sync, or — going forward — see everything that would be affected if you change a dataset's schema.

## When to use it

- A downstream output is stale or wrong and you need to find the root cause upstream.
- You're about to change a dataset and want to know what depends on it (impact analysis).
- You're onboarding to an unfamiliar pipeline and need a map of how it fits together.

**When NOT to use it / alternatives:** For deep build logs and metrics use Data Health / observability tools; lineage is the map, not the detailed log viewer.

## Key concepts & terminology

- **Lineage graph** — The directed graph of producers and consumers.
- **Node** — A dataset, transform, sync, object type, or other resource.
- **Edge** — A dependency (this output is built from that input).
- **Upstream / downstream** — Inputs feeding a node vs. consumers of it.
- **Impact analysis** — Determining everything downstream of a proposed change.
- **Build status** — Whether each node's latest build succeeded, failed, or is stale.
- **Health** — Health-check state surfaced on nodes.

## Core capabilities / features

- **End-to-end visualization** — From source syncs through transforms to Ontology and apps.
- **Upstream/downstream traversal** — Expand dependencies in either direction.
- **Build status overlay** — See success/failure/staleness across the graph at a glance.
- **Impact analysis** — Identify affected downstream resources before making a change.
- **Root-cause tracing** — Walk back from a failing output to the originating failure.
- **Trigger builds & inspect** — Jump from a node to its dataset/transform details or kick off a build.
- **Search & filter** — Locate specific resources within large graphs.

## How it works / typical workflow

1. Open **Data Lineage** from a dataset, pipeline, or project.
2. The graph centers on your resource with upstream inputs and downstream consumers.
3. **Expand nodes** to traverse further in either direction.
4. Read the **build/health overlay** to spot failures or staleness.
5. For a problem, **trace upstream** to the first failing node.
6. For a change, **trace downstream** to assess impact, then coordinate updates.

## Example

A Workshop dashboard shows yesterday's numbers. In Data Lineage you center on the backing object type, traverse upstream, and find that the `raw_sales` sync failed last night (red node). You fix the source credential, rebuild, and the green status propagates downstream to the dashboard.

## How it connects to the rest of Foundry

- **Datasets / Transforms / Pipeline Builder** — The producers and consumers shown as nodes.
- **Schedules** — Build status reflects scheduled runs.
- **Ontology** — Object types appear as downstream nodes of their backing datasets.
- **Data Health / Observability** — Provide the detailed checks and logs behind lineage's status overlay.
- **Marketplace / DevOps** — Lineage helps validate packaged products' dependencies.

## Tips & gotchas for learners

- **Trace upstream for failures, downstream for impact** — two different questions, same graph.
- **Lineage is the map, not the logs** — drill into a node for build details.
- **Large graphs get busy** — use search and collapse branches you don't need.
- **Stale ≠ failed** — a green-but-old node may just need a schedule.
- **Check lineage before schema changes** to avoid breaking unknown consumers.

## Official documentation

- [Data Lineage: Overview](https://www.palantir.com/docs/foundry/data-lineage/overview)
- [Observability: Overview](https://www.palantir.com/docs/foundry/observability/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
