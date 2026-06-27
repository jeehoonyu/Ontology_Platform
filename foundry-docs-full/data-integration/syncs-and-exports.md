<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Syncs &amp; Exports</b></span><br>
<span style="color:#ABB3BF">Bidirectional data movement between external systems and Foundry — inbound via Syncs, outbound via Exports — orchestrated through the Data Connection application.</span>
</td></tr></table>

---

## What it is

**Syncs &amp; Exports** are the core data-movement primitives inside the **Data Connection** application. A *sync* reads data from a connected external source (database, file store, message queue) and writes it into a Foundry dataset or stream. An *export* does the inverse — it takes a Foundry dataset or stream and pushes it to an external destination. Both execute as Foundry build jobs, meaning they participate in the same scheduling, lineage, and health-monitoring infrastructure as every other pipeline in the platform.

---

## How it works

### Building blocks

| Object | Role |
|---|---|
| **Agent** | A process (deployed on-prem or in cloud) that brokers network calls between Foundry and the external system. Each sync and export is dispatched to a healthy agent. |
| **Source** | A named connection configuration (credentials, host, port, auth) registered in Data Connection. One source can back many syncs. |
| **Sync** | A Foundry-managed job definition that describes *what* to read from a source and *where* to write in Foundry. Creates and owns an output dataset. |
| **Export** | A Foundry-managed job definition that describes *which* Foundry dataset or stream to read and *where* to write it externally. |
| **Schedule** | A cron-style or dependency-triggered schedule attached to a sync or export, driving builds through the Foundry build system. |

---

### Sync execution model (step by step)

1. **Build triggered.** A sync build fires on schedule, on manual trigger, or as a downstream dependency of an upstream dataset update. The Foundry build system enqueues the job.

2. **Agent selection.** The build system dispatches the job to a healthy agent — either randomly or to whichever agent has the shortest sync queue (configurable). Each agent can run multiple syncs concurrently based on allocated resources; there is no cross-agent parallelism for a single sync job.

3. **Connector invocation.** The agent loads the appropriate connector plugin (JDBC driver, S3 SDK, Kafka client, etc.) and opens a connection to the source using the stored credentials.

4. **Full vs. incremental read.**
   - **Full snapshot:** The connector reads all matching rows/files and overwrites the output dataset transaction.
   - **Incremental:** The connector reads only rows where a bookmark column (timestamp, sequence ID) exceeds the value recorded from the last successful sync. New rows are written as an `APPEND` transaction to the Foundry dataset, preserving prior transactions for lineage. The bookmark value is persisted in sync state.

5. **Schema handling.** For tabular syncs, the connector maps source columns to Foundry schema types. For file-based syncs, raw files are written to the dataset without enforcing a schema (schema inference can be applied in a downstream transform).

6. **Write to Foundry.** Data is written into the output dataset as a new transaction. Foundry records provenance (run ID, source, timestamp) on every transaction. The dataset becomes immediately available to downstream pipelines once the transaction commits.

7. **Health update.** The sync reports success or failure back to Data Connection. Health state, last-run metadata, and error logs are surfaced in the UI.

---

### Streaming sync distinction

A streaming sync runs **continuously** rather than periodically. The agent maintains a persistent connection to the source (Kafka topic, Kinesis stream, etc.) and writes micro-batches to a Foundry stream with minimal latency. Configuration mirrors batch syncs (source, agent, credentials) but the output is a Foundry stream object rather than a versioned dataset.

---

### Export execution model (step by step)

1. **Build triggered.** An export build fires on schedule, manual trigger, or when the upstream Foundry dataset receives a new transaction.

2. **Agent selection.** Same agent dispatch mechanism as syncs.

3. **Source dataset read.** The export job reads the configured Foundry dataset. For *file exports*, only files modified since the last successfully exported transaction are written by default (delta behavior). For *streaming exports*, records are read from a Foundry stream and published to the target queue or topic.

4. **Connector write.** The agent's connector writes the data to the external destination (S3 bucket, database table, Kafka topic, data warehouse, etc.).

5. **Tabular exports (legacy path).** The new export framework supports file and streaming destinations. Tabular (JDBC) destinations currently require the legacy *Export Tasks* mechanism.

6. **Confirmation and health.** On success the export records which dataset transaction was exported. The next run will use this checkpoint to determine the delta. Health and run logs appear in the Data Connection UI.

---

### Large-dataset exports

Datasets exceeding the 10 M-row data-proxy limit should be converted from Parquet to CSV in a Foundry transform first, then exported via file-based export to S3 or a streaming system (e.g., Kafka). Custom cleanup logic for the destination (e.g., deleting stale S3 objects) must be implemented via an external transformation triggered before the export.

---

## User interface

The <span style="color:#8ABBFF"><b>Data Connection</b></span> application is accessible from the Foundry navigation bar. Its layout follows a left-sidebar catalog on a dark <span style="color:#1C2127"><b>panel</b></span> background.

### Overall layout

- **Left sidebar** — hierarchical tree of <span style="color:#8ABBFF">Sources</span>, <span style="color:#8ABBFF">Syncs</span>, <span style="color:#8ABBFF">Exports</span>, <span style="color:#8ABBFF">Webhooks</span>, and <span style="color:#8ABBFF">Listeners</span>. Clicking any node opens its detail pane on the right.
- **Main content area** — a tabbed panel (Overview / Configuration / Logs / Health) for the selected object.
- **Top action bar** — primary actions such as <span style="color:#2D72D2"><b>Run now</b></span>, <span style="color:#2D72D2"><b>Edit schedule</b></span>, and <span style="color:#2D72D2"><b>Create sync</b></span>.

### Creating a sync

1. Navigate to the relevant **Source** in the sidebar.
2. Click <span style="color:#2D72D2"><b>+ Create</b></span> next to *Batch sync* (or *Streaming sync*).
3. Configure: table/query selection, column mapping, incremental column (if incremental), output dataset path in Foundry.
4. (Optional) attach a schedule using the **Schedule** tab — a cron expression or event-based trigger.
5. Save. The output dataset appears in Foundry's filesystem immediately; data arrives after the first successful build.

### Sync &amp; export status chips

<table style="border-collapse:collapse">
<tr>
<td style="background:#1C2127;padding:8px 14px;border:1px solid #383E47">
<span style="color:#238551"><b>● Healthy</b></span> — last run succeeded, data is current
</td>
<td style="background:#1C2127;padding:8px 14px;border:1px solid #383E47">
<span style="color:#C87619"><b>● Stale / Pending</b></span> — not yet run, or schedule delayed
</td>
</tr>
<tr>
<td style="background:#1C2127;padding:8px 14px;border:1px solid #383E47">
<span style="color:#CD4246"><b>● Failed</b></span> — last run errored; details in Logs tab
</td>
<td style="background:#1C2127;padding:8px 14px;border:1px solid #383E47">
<span style="color:#2D72D2"><b>● Running</b></span> — build in progress
</td>
</tr>
</table>

### Key UI panels

| Panel | What it shows |
|---|---|
| <span style="color:#8ABBFF">Overview</span> | Last run time, status chip, dataset/stream output link, agent assignment |
| <span style="color:#8ABBFF">Configuration</span> | Source, connector settings, column/table selection, incremental column, output path |
| <span style="color:#8ABBFF">Schedule</span> | Cron editor, dependency triggers, enabled/disabled toggle |
| <span style="color:#8ABBFF">Logs</span> | Per-run log lines; filterable by run ID, severity, time range |
| <span style="color:#8ABBFF">Health</span> | Trend chart of recent run durations and outcomes |

---

## Worked example

**Scenario:** A PostgreSQL operational database holds a `orders` table with millions of rows. The team wants to sync new orders into Foundry daily and export the enriched result back to an S3 bucket for a BI tool.

1. **Register source.** In Data Connection, create a PostgreSQL source with host, port, database name, and credentials. Test connection. An agent on the same VPC handles the traffic.

2. **Create an incremental batch sync.** Select the `orders` table, set `updated_at` as the incremental column. Choose an output dataset path in Foundry (`/data/raw/orders`). Attach a daily schedule at 02:00 UTC.

3. **Build pipeline.** In Code Workbook (or Transforms), create a transform that reads `/data/raw/orders`, joins with `/data/reference/customers`, and writes an enriched dataset to `/data/curated/orders_enriched`.

4. **Create an export.** In Data Connection, create a new Export pointing at `/data/curated/orders_enriched`. Choose S3 as the destination, configure bucket path and credentials, enable delta-export (only new files). Schedule to trigger whenever `/data/curated/orders_enriched` receives a new transaction.

5. **Observe.** Each night: sync writes new `orders` rows as an APPEND transaction → transform build fires → export pushes only the new Parquet files to S3. The BI tool reads fresh data without manual intervention. The Data Connection health dashboard shows all three objects as <span style="color:#238551"><b>● Healthy</b></span>.

---

## Documentation map

Sub-pages and sections beneath this tool in the official docs:

- **Data Connection / Core concepts** — agents, sources, datasets, streams, builds, schedules, health checks
- **Data Connection / Syncs**
  - Set up a sync (batch)
  - Set up a streaming sync
  - File-based syncs
  - Media set syncs
  - Optimize JDBC syncs
  - Troubleshooting reference
- **Data Connection / Exports**
  - Export overview
  - Export tasks [Legacy]
- **Data Connection / Sources**
  - Set up a source
  - Source exploration
- **Data Connection / Agents**
  - Set up an agent
  - Agent configuration reference
  - Foundry worker vs. agent worker
- **Data Connection / Connection security**
  - Private links: AWS, Azure, GCP (VPC connectivity)
  - OpenID Connect (OIDC) authentication
- **Data Connection / Webhooks**
- **Data Connection / Listeners** (HTTPS, WebSocket, Email, Google Pub/Sub, Slack, Jira)
- **Building Pipelines / Incremental pipelines** — Creating incremental syncs, maintaining incremental performance
- **Available connectors / Foundry** — full connector catalog

---

## Official documentation

- [Data Connection — Overview](https://www.palantir.com/docs/foundry/data-connection/overview)
- [Data Connection — Core concepts](https://www.palantir.com/docs/foundry/data-connection/core-concepts)
- [Data Connection — Set up a sync](https://www.palantir.com/docs/foundry/data-connection/set-up-sync)
- [Data Connection — Set up a streaming sync](https://www.palantir.com/docs/foundry/data-connection/set-up-streaming-sync)
- [Data Connection — File-based syncs](https://www.palantir.com/docs/foundry/data-connection/file-based-syncs)
- [Data Connection — Exports — Overview](https://www.palantir.com/docs/foundry/data-connection/export-overview)
- [Data Connection — Export tasks (Legacy)](https://www.palantir.com/docs/foundry/data-connection/export-tasks)
- [Data Connection — Optimize JDBC syncs](https://www.palantir.com/docs/foundry/data-connection/optimize-jdbc-syncs)
- [Data Connection — Syncs troubleshooting](https://www.palantir.com/docs/foundry/data-connection/syncs-troubleshooting)
- [Building pipelines — Creating incremental syncs](https://www.palantir.com/docs/foundry/building-pipelines/create-incremental-syncs)
- [Product Q&amp;As — Data Connection](https://www.palantir.com/docs/foundry/questions-answers/data-connection)
