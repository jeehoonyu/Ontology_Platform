# Data Connection (Sources & Agents)

> Data Connection is Foundry's framework for securely connecting to external systems — databases, cloud storage, APIs, message brokers — and importing or exporting data.

## What it is

Data Connection is where data enters and leaves Foundry. You configure a **source** (a connection to an external system such as an S3 bucket, a JDBC database, an SFTP server, or a REST API), optionally route it through an **agent** for network access into private environments, and then define **syncs** that pull data into datasets (or **exports** that push data back out). Foundry supports hundreds of connector types out of the box.

## When to use it

- You need to ingest data from an external system (ERP, CRM, database, cloud bucket, API, stream).
- You need to export Foundry results back to an operational system.
- You must connect to systems behind a firewall or in a private network (via an agent).

**When NOT to use it / alternatives:** Data already in Foundry doesn't need Data Connection — use transforms/pipelines. For purely manual one-off uploads, a direct file upload to a dataset may suffice.

## Key concepts & terminology

- **Source** — A configured connection to an external system, including its connection details and credentials.
- **Connector / source type** — The specific integration (JDBC, S3, SFTP, REST, Kafka, etc.).
- **Agent** — A lightweight process you run in your network that brokers connectivity between Foundry and private systems.
- **Direct connection** — Connectivity that does not require an agent (e.g., cloud-to-cloud).
- **Sync** — A configured import that pulls data from a source into a dataset.
- **Export** — A configured push of Foundry data out to an external system.
- **Credentials** — Secrets (passwords, keys, tokens) stored securely and attached to a source.

## Core capabilities / features

- **Hundreds of connectors** — ERPs, CRMs, cloud storage, JDBC/ODBC databases, REST/SOAP APIs, message brokers, SFTP, and more.
- **Agent-based and direct connectivity** — Reach private networks via an agent, or connect directly for cloud sources.
- **Secure credential storage** — Secrets are encrypted and access-controlled; never embedded in pipelines.
- **Batch and streaming ingestion** — Pull bounded snapshots, incremental loads, or continuous streams.
- **Exploration UI** — Browse source tables/files before configuring a sync.
- **Exports & webhooks** — Push data out, or react to incoming events.
- **Network & security controls** — Allowlists, egress policies, and governance over what connects where.

## How it works / typical workflow

1. **Create a source** of the appropriate connector type.
2. **Configure connectivity** — direct, or install/select an **agent** for private networks.
3. **Add credentials** securely and test the connection.
4. **Explore** the source to find the tables/files/topics you want.
5. **Create a sync** to import into a dataset (choose snapshot vs incremental).
6. **Schedule** the sync to refresh on a cadence.
7. Optionally configure **exports** to send results back out.

## Example

Ingesting from a Postgres database behind a firewall:

1. Install a **Data Connection agent** in the network that can reach Postgres.
2. Create a **JDBC source** pointing at the database; store credentials securely.
3. Explore and select the `public.orders` table.
4. Create an **incremental sync** keyed on `updated_at` into `/Project/raw/orders`.
5. Schedule it every 15 minutes.

## How it connects to the rest of Foundry

- **Datasets** — Syncs land raw data as datasets.
- **Syncs & exports** — The import/export mechanisms built on sources.
- **Streaming / streams** — Streaming sources feed real-time pipelines.
- **Schedules** — Syncs run on schedules.
- **Security** — Credentials, network egress, and markings are governed centrally.
- **Pipeline Builder / Transforms** — Consume the landed raw datasets.

## Tips & gotchas for learners

- **Agents are for private networks** — cloud-to-cloud sources usually connect directly.
- **Prefer incremental syncs** on large tables to avoid full reloads.
- **Credentials are governed** — store them in the source, never hard-code them.
- **Explore before syncing** to confirm you target the right tables/columns.
- **Network egress rules** can block connections — coordinate with administrators.

## Official documentation

- [Data Connection: Overview](https://www.palantir.com/docs/foundry/data-connection/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
- [Source type reference](https://www.palantir.com/docs/foundry/available-connectors/overview)
