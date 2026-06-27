<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Data Connection</b></span><br>
<span style="color:#ABB3BF">The secure infrastructure layer that links Foundry to external systems — databases, file stores, APIs, and SaaS applications — so raw data can be ingested as-is, without preprocessing outside the platform.</span>
</td></tr></table>

## What it is

Data Connection is Foundry's managed connectivity subsystem for reaching external data sources. It provides the primitives — **Agents**, **Sources**, and **Syncs** — through which an operator configures where data lives, how Foundry reaches it, and on what cadence data moves into Foundry datasets. It is deliberately minimal in its transformation surface: data arrives raw so that every change on the path from source to Ontology is version-controlled inside Foundry's pipeline graph.

Data Connection is distinct from the transformation layer (Pipeline Builder, Code Repositories). Its job ends once raw data lands in a Foundry dataset or stream; downstream tools handle enrichment and modeling.

## How it works

Data Connection is built around three layered objects that must be configured in order: Agent → Source → Sync.

**1. Agent deployment**

An Agent is a long-running process you deploy inside your network — on-premises or in a cloud VPC — that acts as the outbound relay between your environment and Foundry. The agent opens an authenticated WebSocket connection *to* Foundry (egress only), so no inbound firewall rules are required on your side. Two deployment models exist:

- **Foundry Worker** — a fully-managed, isolated container hosted inside Foundry's own compute plane. Foundry provisions it automatically; no infrastructure management is needed. Suited for cloud-accessible sources.
- **Agent Worker** — a self-hosted process you run inside your private network. Required when sources are behind a firewall, on an internal network, or reachable only via a corporate proxy. The agent worker is in a legacy maintenance phase; new deployments should prefer the Foundry Worker where possible.

The agent maintains a persistent, encrypted WebSocket connection to Foundry. All data and control messages flow over this single channel. Proxy configuration and Private Link connectivity (AWS PrivateLink, Azure Private Link, GCP Private Service Connect) are supported for extra network isolation.

**2. Source definition**

A Source is a named resource that stores everything needed to reach one external system: connection parameters (hostname, port, database name), authentication credentials (stored in Foundry's secrets vault — never in plain text), and the connector plugin that speaks the system's protocol. Foundry ships over 200 built-in connector plugins covering relational databases (PostgreSQL, MySQL, Oracle, Snowflake, BigQuery, Databricks), file protocols (S3, SFTP, FTPS, HDFS, local directory), enterprise systems (SAP, Salesforce, NetSuite, Dynamics), SaaS APIs (Jira, Slack, GitHub, HubSpot, Zendesk), and message queues (Kafka, Google Pub/Sub, Kinesis).

A source is bound to exactly one agent (the agent that can reach it). The source's credential is scoped by Foundry's permissions model so only authorized projects and users can attach syncs to it.

**3. Sync execution**

A Sync is the actual data-movement job. It references a source, specifies what to pull (a table, a query, a file glob, a topic), and maps the output to a Foundry dataset or stream. Sync types include:

- **Batch / JDBC sync** — full or incremental pull from a relational source, written to a Foundry dataset. Incremental mode uses a high-watermark column (e.g., `updated_at`) to fetch only new rows.
- **File-based sync** — copies files from a file protocol source (S3, SFTP, etc.) into a Foundry dataset or media set.
- **Streaming sync** — connects to a message queue (Kafka, Kinesis, Pub/Sub) and writes a continuous stream of records to a Foundry stream dataset.
- **Media set sync** — ingests binary/unstructured files (images, PDFs, audio) into a Foundry media set.
- **Export task** — reverse direction: writes a Foundry dataset to an external destination.

A sync can be triggered manually, on a cron-style schedule, or by a build trigger from upstream pipeline nodes. When a sync runs, the assigned agent (or Foundry Worker) reads from the source system, chunks the data, and uploads it to Foundry's object storage via the authenticated WebSocket channel. The resulting dataset transaction is committed atomically, preserving Foundry's branched-dataset versioning guarantees.

**4. Event-driven ingestion (Listeners)**

For push-based data, Data Connection exposes Listeners — persistent HTTPS endpoints, WebSocket endpoints, or email inboxes hosted by Foundry — that external systems can push events to. Supported flavors: HTTPS listeners (Google Pub/Sub push, Jira webhooks, Slack event subscriptions), WebSocket listeners, and email listeners. Incoming payloads are written to stream datasets or directly trigger pipeline builds.

**5. External transforms and functions**

Code in Foundry repositories can make outbound calls to external systems at transform time via External Functions, which also pass through the agent's secure channel, keeping all external communication auditable.

## User interface

Data Connection lives at <span style="color:#8ABBFF">**Control Panel → Data Connection**</span> (or via the platform's left-rail navigation under <span style="color:#8ABBFF">**Data Integration**</span>).

**Main layout**

The application uses a two-pane layout:
- Left sidebar (<span style="color:#ABB3BF">background #1C2127, border #383E47</span>): hierarchical tree listing **Agents**, **Sources**, **Syncs**, **Exports**, and **Listeners** as collapsible sections. Clicking any node opens its detail view in the right pane.
- Right content area (<span style="color:#ABB3BF">background #111418</span>): context-sensitive editor and status panel for the selected object.

**Agent panel**

Shows the agent's connection status, version, and last heartbeat time. A <span style="color:#238551"><b>● Connected</b></span> chip indicates the WebSocket is alive; <span style="color:#CD4246"><b>● Disconnected</b></span> means the agent process is down or unreachable. The panel surfaces agent logs inline for debugging.

**Source panel**

Displays connection parameters, credential references (masked), the bound agent, and a <span style="color:#2D72D2"><b>Test Connection</b></span> button that triggers a live connectivity probe via the agent. A <span style="color:#2D72D2"><b>Explore Source</b></span> action opens a schema browser — a tree of databases, schemas, tables, and columns — letting the operator inspect what is available before configuring a sync.

**Sync panel**

The sync configuration form is the primary interaction surface:

<table>
<tr style="background:#1C2127;color:#ABB3BF">
  <th style="padding:8px 12px;border:1px solid #383E47">UI area</th>
  <th style="padding:8px 12px;border:1px solid #383E47">What you configure</th>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Source selector</span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Pick the source object; auto-populates available tables</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Table / query</span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Choose a table from the explorer or enter a custom SQL query</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Incremental column</span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Select the high-watermark column for incremental syncs</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Destination dataset</span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Foundry dataset RID or path where rows are written</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF">Schedule</span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Cron expression or "trigger on upstream build"</td>
</tr>
</table>

**Sync run history** lists every execution with status chips:

<span style="color:#238551"><b>● Success</b></span> · <span style="color:#C87619"><b>● Running / Pending</b></span> · <span style="color:#CD4246"><b>● Failed</b></span> · <span style="color:#ABB3BF"><b>● Skipped</b></span>

Clicking a run opens a log drawer showing row counts, bytes transferred, duration, and any error details. The <span style="color:#2D72D2"><b>Run now</b></span> button triggers an ad-hoc execution.

**Pipeline Builder integration**

Data Connection sources can be imported directly into the <span style="color:#8ABBFF">Pipeline Builder</span> canvas by dragging a source node onto the graph, which creates a dataset-sync node backed by the Data Connection configuration without leaving the pipeline editor.

## Worked example

**Scenario:** A security team needs daily snapshots of a PostgreSQL incidents database that lives behind a corporate firewall, landing in a Foundry dataset for downstream pipeline analysis.

1. **Deploy an Agent Worker** on a VM inside the corporate network. The installer generates an enrollment token; pasting it in the Foundry UI registers the agent and establishes the outbound WebSocket tunnel. The agent panel shows <span style="color:#238551"><b>● Connected</b></span>.

2. **Create a Source** of type PostgreSQL. Enter hostname `incidents-db.corp.internal`, port `5432`, database `security_ops`. Add the service-account password as a Foundry secret. Bind the source to the agent just deployed. Click <span style="color:#2D72D2"><b>Test Connection</b></span> — the agent relays a test query and the panel returns a success badge. Click <span style="color:#2D72D2"><b>Explore Source</b></span> to confirm the `incidents` table is visible.

3. **Create a Sync** pointing at the `incidents` table. Set the incremental column to `updated_at`. Set the destination to `/Security/Raw/incidents` (a new Foundry dataset). Set a daily schedule at 02:00 UTC.

4. Click <span style="color:#2D72D2"><b>Run now</b></span> to trigger the first full load. The sync panel shows <span style="color:#C87619"><b>● Running</b></span>, then flips to <span style="color:#238551"><b>● Success</b></span> with row count 42,317 and bytes transferred 18.2 MB.

5. Subsequent nightly runs use the `updated_at` watermark, transferring only new or modified rows. The dataset's transaction log in Foundry records each sync as a versioned commit, so pipelines downstream can detect the new data and trigger automatically.

## Documentation map

- **Data Connection / Overview** — high-level introduction and navigation hub
- **Data Connection / Core concepts** — definitions of agents, sources, syncs, and listeners
- **Data Connection / Architecture** — deployment topology, Foundry Worker vs. Agent Worker, WebSocket channel design
- **Data Connection / Initial setup overview** — step-by-step first-time configuration guide
- **Data Connection / Agents / Set up an agent** — agent enrollment and registration
- **Data Connection / Agents / Agent configuration reference** — YAML config keys for agent runtime
- **Data Connection / Agents / Agent worker configuration reference** — legacy agent-worker specific options
- **Data Connection / Agents / Agent proxy configuration** — proxy and Private Link setup
- **Data Connection / Agents / Troubleshooting reference** — diagnostic procedures for connectivity issues
- **Data Connection / Connection security** — credential storage, TLS, permissions scoping
- **Data Connection / Sources / Set up a source** — creating and testing source objects
- **Data Connection / Sources / Source exploration** — browsing source schemas in the UI
- **Data Connection / Syncs / Set up a sync** — sync creation, scheduling, incremental configuration
- **Data Connection / Syncs / Optimize JDBC syncs** — parallelism and performance tuning
- **Data Connection / Syncs / File-based syncs** — file glob patterns, format options
- **Data Connection / Syncs / Streaming syncs** — Kafka, Kinesis, Pub/Sub integration
- **Data Connection / Syncs / Media set syncing** — binary/unstructured file ingestion
- **Data Connection / Exports** — writing Foundry data back to external systems
- **Data Connection / Webhooks and listeners** — HTTPS, WebSocket, and email listener setup
- **Data Connection / External connections from code / External functions** — outbound calls from transform code
- **Data Connection / OpenID Connect (OIDC)** — federated authentication for sources
- **Data Connection / FAQ** — common questions and answers
- **Available connectors / Foundry** — full catalogue of 200+ connector plugins

## Official documentation

- [Data Connection — Overview](https://www.palantir.com/docs/foundry/data-connection/overview)
- [Data Connection — Core concepts](https://www.palantir.com/docs/foundry/data-connection/core-concepts)
- [Data Connection — Architecture](https://www.palantir.com/docs/foundry/data-connection/architecture)
- [Data Connection — Initial setup overview](https://www.palantir.com/docs/foundry/data-connection/initial-setup-overview)
- [Data Connection — Set up a source](https://www.palantir.com/docs/foundry/data-connection/set-up-source)
- [Data Connection — Set up a sync](https://www.palantir.com/docs/foundry/data-connection/set-up-sync)
- [Data Connection — Set up an agent](https://www.palantir.com/docs/foundry/data-connection/set-up-agent)
- [Data Connection — Agent worker configuration reference](https://www.palantir.com/docs/foundry/data-connection/agent-worker)
- [Data Connection — Agent configuration reference](https://www.palantir.com/docs/foundry/data-connection/agent-configuration-reference)
- [Data Connection — FAQ](https://www.palantir.com/docs/foundry/data-connection/faq)
- [Data Integration — Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
- [Available connectors — Foundry](https://www.palantir.com/docs/foundry/available-connectors/foundry)
- [Pipeline Builder — Configure sources and dataset syncs](https://www.palantir.com/docs/foundry/pipeline-builder/datasets-sources)
