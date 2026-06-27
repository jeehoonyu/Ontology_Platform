# Data Integration — Overview

> Data integration in Palantir Foundry is the end-to-end capability for connecting external data sources to the platform, transforming that data into usable datasets, and managing the resulting pipelines throughout their lifecycle.

## What it is

Data integration covers everything from the moment raw data leaves a source system to the moment a clean, versioned dataset is ready for analysis or powering an Ontology. It solves the classic enterprise data problem: organizations have data scattered across dozens of systems (databases, cloud storage, SaaS apps, streams), and Foundry provides a unified framework — connectivity, transformation, scheduling, lineage, and health monitoring — to bring it all together in one governed platform. Within Foundry, data integration sits at the foundation layer: it feeds every downstream capability, including the Ontology, Workshop applications, and AIP models.

## When to use it

- You need to pull data from an external database (SQL Server, PostgreSQL, Oracle, Snowflake, etc.) into Foundry on a schedule.
- You are ingesting files from cloud storage (S3, Azure Blob, GCP) or SFTP/FTPS endpoints.
- You need near-real-time or streaming ingestion from event streams, webhooks, WebSocket feeds, or systems like Google Pub/Sub or Slack.
- You want to build reproducible, versioned transformation pipelines in Python, SQL, Java, R, or via a no-code visual editor.
- You need incremental updates via Change Data Capture (CDC) rather than full reloads.
- You want to export processed data back out to external systems.

**When NOT to use it / alternatives:** If your data already lives inside Foundry (e.g., produced by a prior pipeline), you do not need Data Connection — use Pipeline Builder or a Code Repository transform directly on existing datasets.

## Key concepts & terminology

- **Dataset** — The primary storage object in Foundry; a versioned, structured collection of data (like a table) that pipelines read from and write to.
- **Stream** — A continuous, ordered flow of records used for real-time / event-driven data rather than batch files.
- **Media set** — A storage container for unstructured data (images, PDFs, video, etc.).
- **Data Connection** — The Foundry subsystem (agents + sources + syncs) that manages connectivity to external systems.
- **Agent** — A lightweight process deployed in your network that acts as a secure intermediary between an external source and Foundry (required when the source is behind a firewall).
- **Source** — A configured representation of an external system (e.g., a specific database or S3 bucket) registered in Data Connection.
- **Sync** — A configured job that moves data from a Source into a Foundry dataset or stream on a schedule or trigger.
- **Export** — The reverse of a sync; moves data from Foundry out to an external system.
- **Change Data Capture (CDC)** — An incremental sync strategy that detects only modified/new records rather than re-ingesting an entire table.
- **Virtual table** — A database view exposed to Foundry that allows query pushdown without physically replicating data.
- **Iceberg table** — An open-table-format storage option for large-scale analytical datasets within Foundry.
- **Pipeline Builder** — A visual drag-and-drop tool for building transformation pipelines without writing code.
- **Code Repository** — A code-based environment (Python, SQL, Java, R, or containers) for building transforms programmatically.
- **Build** — The act of executing a pipeline to produce output datasets; Foundry tracks builds for lineage and rollback.
- **Branch** — A version-controlled copy of a pipeline or dataset used for development without affecting production data.
- **Health check** — A configured assertion on a dataset that alerts when data quality rules are violated.
- **Private Link** — A VPC-level network connection (AWS PrivateLink, Azure Private Link, GCP Private Service Connect) for secure, zero-public-internet data transfer.

## Core capabilities / features

- **Extensible connectivity:** Out-of-the-box connectors for relational databases, cloud storage, enterprise apps (Salesforce, SAP, NetSuite), and more — totaling 200+ supported source systems. Custom connectors can be built for non-standard systems.
- **Multiple transfer modes:**
  - *Batch* — scheduled full or incremental loads.
  - *Micro-batch* — frequent small loads for near-real-time latency.
  - *Streaming* — continuous ingestion via listeners (HTTPS, WebSocket, email, Pub/Sub).
- **Change Data Capture (CDC):** Detects row-level inserts, updates, and deletes at the source, reducing load and keeping Foundry data fresh without full reloads.
- **Transformation infrastructure:** Multimodal compute supports Python (PySpark), SQL, Java, R, and containerized workloads. Pipelines are declarative: Foundry figures out what needs to rebuild when upstream data changes.
- **Full lineage:** Every dataset version is traceable back through every transform and sync that produced it, enabling impact analysis and rollback.
- **Branching and builds:** Developers can branch pipelines and datasets to test changes safely, then merge to production — similar to Git branching for data.
- **Scheduling and automation:** Syncs and pipeline builds can be scheduled on cron-like intervals or triggered by upstream dataset changes.
- **Security and governance:** Granular permissions on sources, syncs, and datasets; OIDC authentication; Private Link for network-level isolation.
- **Push-based ingestion:** External systems can push data into Foundry streams without an agent, useful for IoT and webhook scenarios.
- **Export:** Processed datasets can be exported back to external systems, closing the loop for operational workflows.

## How it works / typical workflow

1. **Register a Source.** In the Data Connection application, define the external system (e.g., a PostgreSQL database) and configure credentials.
2. **Deploy an Agent (if needed).** If the source is on-premises or behind a firewall, deploy a Foundry agent on your network to broker the connection.
3. **Configure a Sync.** Specify which tables or files to pull, the target dataset in Foundry, the transfer mode (full, incremental, CDC), and a schedule.
4. **Run the initial sync.** Foundry ingests the data and creates the first version of the raw dataset.
5. **Build transformation pipelines.** In Pipeline Builder or a Code Repository, write transforms that read the raw dataset and produce cleaned, enriched output datasets.
6. **Schedule builds.** Attach a schedule (or dependency trigger) so the pipeline re-runs automatically when new data arrives.
7. **Set up health checks.** Define assertions (e.g., row count > 0, no nulls in key column) to catch data quality issues early.
8. **Publish datasets downstream.** Expose output datasets to the Ontology, Workshop, or other consumers.

## Example

A retail company wants to analyze daily sales. They have a SQL Server database on-premises.

1. They deploy a **Foundry agent** inside their corporate network.
2. In Data Connection, they create a **Source** pointing to the SQL Server and a **Sync** that pulls the `orders` table into a Foundry dataset called `raw_orders` every night at 2 AM using CDC (only new/updated rows).
3. In a **Code Repository**, they write a PySpark transform that joins `raw_orders` with a `products` dataset and produces `daily_sales_summary`.
4. They schedule the transform build to trigger **after** the nightly sync completes.
5. A **health check** asserts that `daily_sales_summary` always has at least 1,000 rows, alerting the team if the sync fails silently.

```python
# Simplified PySpark transform in a Code Repository
from transforms.api import transform_df, Input, Output

@transform_df(
    Output("/analytics/daily_sales_summary"),
    orders=Input("/raw/raw_orders"),
    products=Input("/raw/products"),
)
def compute(orders, products):
    return orders.join(products, "product_id").groupBy("sale_date", "category").sum("revenue")
```

## How it connects to the rest of Foundry

- **Ontology:** Output datasets from pipelines are linked to Ontology object types, turning raw tables into semantic business objects (e.g., a `Customer` or `Order` object).
- **Pipeline Builder / Code Repositories:** These are the transformation tools that operate on datasets produced by data integration syncs.
- **Workshop:** Applications built in Workshop query datasets and Ontology objects that data integration pipelines keep current.
- **AIP / Functions:** AI models and Functions consume datasets and streams ingested and prepared by data integration pipelines.
- **Data Connection:** The connectivity sub-system within data integration responsible for agents, sources, syncs, and exports.
- **Schedules & Builds:** The orchestration layer that chains syncs and transforms into end-to-end automated pipelines.

## Tips & gotchas for learners

- **Agent vs. Foundry worker:** If your source is reachable from the public internet, you may not need an agent — Foundry can connect directly. Agents are only required for private/on-prem sources.
- **CDC requires source support:** Not all databases support CDC (e.g., it requires specific configurations in PostgreSQL/SQL Server). Verify source compatibility before designing pipelines around it.
- **Branching is powerful but adds complexity:** Use branches for development, but make sure to merge and deprecate stale branches to avoid confusion.
- **Health checks are opt-in:** Foundry will not automatically validate your data — you must explicitly configure health checks to catch quality issues.
- **Virtual tables vs. syncs:** Virtual tables avoid data duplication but add query latency and depend on the source being available. Use syncs (physical copy) for performance-critical downstream workloads.
- **Lineage is automatic:** You do not need to manually document data lineage — Foundry tracks it for every build. Use the lineage view to understand impact before deleting or modifying datasets.
- **Connector availability varies by deployment:** Not all 200+ connectors are available in every Foundry instance; check with your platform administrator.

## Official documentation

- [Overview — Data integration](https://www.palantir.com/docs/foundry/data-integration/overview)
- [Connecting to data](https://www.palantir.com/docs/foundry/data-integration/connecting-to-data)
- [What is a data pipeline?](https://www.palantir.com/docs/foundry/data-integration/data-pipeline)
- [Core concepts — Datasets](https://www.palantir.com/docs/foundry/data-integration/datasets/index.html)
- [Data Connection — Overview](https://www.palantir.com/docs/foundry/data-connection/overview)
- [Pipeline Builder — Overview](https://www.palantir.com/docs/foundry/pipeline-builder/overview)
