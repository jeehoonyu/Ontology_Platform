# Data Health & Monitoring

> Data Health is Foundry's application for monitoring the health of platform resources at scale — using health checks on individual resources and scope-based monitoring rules across projects and pipelines.

## What it is

In a large platform, you can't manually watch every dataset and schedule. Data Health automates it. You attach **health checks** to resources (is this dataset fresh? did the schedule succeed? does the row count look right?) and define **monitoring views** with scope-based rules that apply checks across many resources at once — a whole project, folder, or application. When something breaks or goes stale, you get alerted before downstream users notice.

## When to use it

- You're running production pipelines that must stay fresh and correct.
- You need to monitor many datasets/schedules without per-resource manual checks.
- You want alerting on failures, staleness, schema drift, or anomalous metrics.

**When NOT to use it / alternatives:** For mapping dependencies use **Data Lineage**; for AI workflow tracing use **AIP observability/traces**.

## Key concepts & terminology

- **Health check** — A validation on a resource (freshness, build success, row count, schema, etc.).
- **Monitoring view** — A configuration applying checks across a scope at scale.
- **Scope-based rule** — A rule targeting a project/folder/application rather than one resource.
- **Alert / notification** — What fires when a check fails.
- **Freshness / staleness** — Whether a dataset updated within expected time.
- **Build status** — Success/failure of scheduled builds.

## Core capabilities / features

- **Per-resource health checks** — Freshness, build success, row counts, schema, and custom checks.
- **Scope-based monitoring views** — Apply rules across many resources at once.
- **Alerting** — Notify owners on failures or anomalies.
- **Coverage across resource types** — Datasets, schedules, tables, and more.
- **Dashboards** — See health status across your estate at a glance.
- **Integration with builds/schedules** — Surface build and freshness problems quickly.

## How it works / typical workflow

1. **Open Data Health** and pick resources (or a scope).
2. **Add health checks** — e.g., "must update every 24h," "build must succeed," "rows within range."
3. **Create monitoring views** with scope-based rules for many resources.
4. **Configure alerts/notifications** to owners.
5. **Monitor dashboards**; respond to alerts.
6. Use **Data Lineage** to trace a failing check to its root cause.

## Example

A production project gets a monitoring view requiring every output dataset to refresh within 24 hours and every schedule to succeed. When the overnight `raw_sales` sync fails, a freshness + build-status check fires an alert to the data team at 6 a.m., who fix it before the morning dashboards are viewed.

## How it connects to the rest of Foundry

- **Datasets / Schedules** — The primary monitored resources.
- **Data Lineage** — Provides the dependency map to trace failures.
- **Pipeline Builder / Transforms** — Produce the monitored outputs.
- **AIP observability** — Complementary monitoring for AI/Function workflows.
- **Marketplace/DevOps** — Health checks can ship with packaged products.

## Tips & gotchas for learners

- **Freshness + build-status checks** are the essential baseline for any production pipeline.
- **Scope-based views scale** — don't hand-configure hundreds of single checks.
- **Alert the right owners** — unrouted alerts get ignored.
- **Health tells you something broke; lineage tells you why.**
- **Set realistic thresholds** to avoid alert fatigue.

## Official documentation

- [Data Health: Overview](https://www.palantir.com/docs/foundry/data-health/overview)
- [Observability: Overview](https://www.palantir.com/docs/foundry/observability/overview)
