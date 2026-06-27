# Syncs & Exports

> Syncs import data from an external source into a Foundry dataset; exports push Foundry data back out to external systems.

## What it is

Once you've configured a **source** in Data Connection, **syncs** and **exports** are how data actually moves. A sync defines what to pull (which tables/files/topics), how to pull it (full snapshot vs incremental), and where it lands (a dataset). An export does the reverse: it takes a Foundry dataset and writes it to an external destination on a schedule or trigger. Together they form the import/export boundary of the platform.

## When to use it

- **Sync**: regularly bring an external table, file drop, or stream into Foundry.
- **Export**: deliver Foundry-computed results to a downstream operational system, warehouse, or file share.
- **Webhooks/listeners**: react to pushed events rather than polling.

**When NOT to use it / alternatives:** For data already inside Foundry, use transforms. For low-latency continuous data, use **streaming syncs** rather than frequent batch syncs.

## Key concepts & terminology

- **Sync** — A configured import from a source into a dataset.
- **Snapshot sync** — Replaces the whole dataset each run (SNAPSHOT transaction).
- **Incremental sync** — Pulls only new/changed rows since the last run (keyed on a column or cursor).
- **File-based sync** — Imports files (CSV, Parquet, etc.) from storage/SFTP.
- **Streaming sync** — Continuously ingests from a message broker into a stream.
- **Export** — A configured push of a dataset to an external destination.
- **Webhook / listener** — An endpoint that receives pushed events (HTTPS, WebSocket, email).

## Core capabilities / features

- **Snapshot and incremental modes** — Choose full reloads or efficient delta pulls.
- **File, table, and streaming syncs** — Handle structured tables, raw files, and real-time topics.
- **Exports back to source systems** — Close the loop by delivering results downstream.
- **Webhooks & listeners** — Event-driven ingestion for systems that push.
- **Scheduling** — Syncs/exports run on schedules or triggers.
- **Schema handling** — Map source columns to dataset columns; handle drift.
- **Monitoring** — Track sync health and failures via Data Health.

## How it works / typical workflow

1. Configure a **source** in Data Connection.
2. **Create a sync**, selecting the table/file/topic and target dataset.
3. Choose **snapshot or incremental**; for incremental, set the cursor/key column.
4. **Schedule** the sync (e.g., hourly) or trigger it on events.
5. For outbound flows, **create an export** from a dataset to the destination.
6. **Monitor** runs and add health checks for failures or staleness.

## Example

- **Incremental sync:** Pull `orders` where `updated_at > last_cursor` every 15 min into `/Project/raw/orders` (APPEND).
- **Export:** After computing `/Project/out/daily_summary`, export it nightly as CSV to an SFTP server for a partner.

## How it connects to the rest of Foundry

- **Data Connection / sources** — Syncs and exports run against configured sources.
- **Datasets / streams** — Syncs land data as datasets or streams.
- **Schedules** — Control when syncs/exports run.
- **Data Health** — Monitors freshness and failures.
- **Pipeline Builder / Transforms** — Consume synced raw data.

## Tips & gotchas for learners

- **Incremental needs a reliable cursor** (monotonic timestamp or ID) — gaps cause missed rows.
- **Snapshot is simplest but heavy** on big tables; use incremental when you can.
- **Exports leave the governance boundary** — confirm markings/policies allow it.
- **Add staleness checks** so a silently failing sync is caught quickly.
- **Schema drift** upstream can break syncs — monitor and version schemas.

## Official documentation

- [Data Connection: Syncs](https://www.palantir.com/docs/foundry/data-connection/syncs)
- [Data Connection: Overview](https://www.palantir.com/docs/foundry/data-connection/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
