<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Streaming &amp; Streams</b></span><br>
<span style="color:#ABB3BF">A dual-layer (hot buffer + cold archive) real-time ingestion and pipeline framework that brings event-by-event data into Foundry with the same governance primitives as batch datasets.</span>
</td></tr></table>

---

## What it is

A **Stream** in Foundry is a first-class dataset-like resource that wraps a collection of rows stored across two layers: a low-latency **hot buffer** for newly arrived records and a **cold storage** archive backed by the Foundry file system. Because every stream exposes the same governance primitives as a regular dataset — branching, version control, permissions, schema management — any Foundry application can consume real-time data without needing specialised real-time infrastructure knowledge.

**Streaming pipelines** extend that foundation: they are continuously running Flink-powered transform jobs wired between one or more input streams and one or more output streams or datasets, processing each row immediately as it arrives rather than in scheduled batches.

---

## How it works

### 1. Ingestion — data enters a Foundry Stream

| Path | Mechanism |
|---|---|
| Pull from Kafka / Kinesis | A **streaming sync** in Data Connection runs as a long-running agent job, continuously reading topic partitions into a Foundry Stream. Each consumer thread handles a subset of partitions; threads are configurable for throughput. |
| CDC / push-based | A push-based ingestion endpoint writes rows directly to the hot buffer. CDC sources write change events row-by-row. |
| Batch → Stream conversion | A batch dataset can be used as the input of a streaming pipeline in Pipeline Builder; records are emitted as stream rows. |

### 2. Hot buffer — low-latency availability

As each record is written, it lands in the **hot buffer**: an in-memory/fast-disk layer that downstream Flink jobs and Foundry applications can read within milliseconds. The hot buffer provides a hybrid view — readers see both un-archived records still in hot storage and older records that have already been persisted to cold storage, giving a complete, ordered view of the stream at any point in time.

Unlike datasets, streams have **no transaction boundaries**. Each row is its own atomic unit of state; this per-row state tracking enables push-based (event-driven) downstream computations without polling or batch commits.

### 3. Archiving — hot buffer → cold storage

Every few minutes, a background **archive job** scans the hot buffer and moves its contents into Foundry's persistent cold storage (the file system). Once archived, the data is readable as a standard Foundry dataset — with full history, schema, and version lineage. Archive jobs are lightweight batch processes that only run when new data exists, so they do not consume continuous compute.

### 4. Streaming pipeline execution — Flink runtime

A streaming pipeline is a directed acyclic graph of **transform nodes** that executes on Apache Flink. The execution model is:

1. **Input node** reads rows from one or more Foundry Streams via the hot buffer.
2. Each row is passed through the transform graph immediately — no micro-batch window is required unless an explicit windowing transform is added.
3. **Keying** (`Key by` transform): one or more columns are designated as partition keys. Flink routes all records sharing the same key value to the same parallel operator instance. This is required for any stateful transform that must correlate events across time (e.g., running totals, sessionisation).
4. **Stateful transforms** maintain Flink-managed state per key (e.g., counters, accumulators, sliding windows). State types and evolution are abstracted by pre-built transform nodes; users do not manage checkpoints manually.
5. The processed rows are written to an **output Stream or dataset**. By default streaming pipelines emit to a single Flink job group, but multiple job groups can be configured with separate compute profiles for isolation or cost control.
6. The output partitions default to 8 (configurable up to 16 in pipeline settings).

### 5. Streaming profiles

**Streaming profiles** are named compute configuration bundles applied to a pipeline or job group. They control parallelism, memory, and fault-tolerance settings. A default profile suits most workloads; custom profiles are created for high-throughput or low-latency requirements.

### 6. Replaying a stream

When logic changes require reprocessing historical data, a **stream reset** operation clears the pipeline's Flink state and replays from cold storage. Replaying from a Java UDF deployment requires bumping the `logicVersion` in the pipeline configuration YAML, which triggers a full re-run.

---

## User interface

Streams and streaming pipelines are primarily managed through two applications: <span style="color:#8ABBFF"><b>Data Connection</b></span> (ingestion) and <span style="color:#8ABBFF"><b>Pipeline Builder</b></span> (transforms).

### Data Connection — setting up a streaming sync

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;padding:10px;width:100%">
<tr>
<td style="padding:8px 12px;color:#ABB3BF;font-size:13px">
<b style="color:#fff">Panel / Area</b>
</td>
<td style="padding:8px 12px;color:#ABB3BF;font-size:13px">
<b style="color:#fff">What you see &amp; do</b>
</td>
</tr>
<tr style="border-top:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#8ABBFF">+ New Source</span></td>
<td style="padding:8px 12px;color:#ABB3BF">Opens the connector picker. Select <b>Kafka</b>, <b>Amazon Kinesis</b>, or other streaming connector types.</td>
</tr>
<tr style="border-top:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#8ABBFF">Source configuration panel</span></td>
<td style="padding:8px 12px;color:#ABB3BF">Set broker addresses, topic names, consumer group, credential method (SSL / Username+Password / Azure AD / Kerberos / None), Schema Registry URL, and thread count (each thread = one Kafka consumer).</td>
</tr>
<tr style="border-top:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#8ABBFF">Sync type selector</span></td>
<td style="padding:8px 12px;color:#ABB3BF">Toggle between <b>batch</b>, <b>incremental</b>, and <b>streaming</b>. Streaming mode disables the schedule selector (job runs continuously).</td>
</tr>
<tr style="border-top:1px solid #383E47">
<td style="padding:8px 12px"><span style="color:#8ABBFF">Agent connection toggle</span></td>
<td style="padding:8px 12px;color:#ABB3BF">Recommended for streaming syncs — routes traffic through an on-premises agent for bandwidth and availability.</td>
</tr>
</table>

### Pipeline Builder — building a streaming pipeline

The Pipeline Builder canvas is a dark-themed <span style="color:#8ABBFF">node graph editor</span>. Nodes are dragged from the left panel onto the canvas and wired together:

- <span style="color:#2D72D2"><b>Input node</b></span> — select a Foundry Stream as source; a <span style="color:#ABB3BF">data preview pane</span> opens below the canvas showing the most recent records from the hot buffer.
- <span style="color:#2D72D2"><b>Transform nodes</b></span> — Filter, Map, Key by, Join, Parse JSON, Stateful UDF, Window Aggregate, and others. Each node has a right-side <span style="color:#ABB3BF">configuration panel</span> for expression editing and parameter input.
- <span style="color:#2D72D2"><b>Output node</b></span> — wire to a Stream or Dataset. Right-click the output node → <b>Open</b> to preview the output stream in the stream preview page.

**What you see — pipeline status chips:**

<span style="color:#238551"><b>● Running</b></span> — Flink cluster active, processing records in real time
<span style="color:#C87619"><b>● Starting</b></span> — cluster bootstrapping (~1 min)
<span style="color:#CD4246"><b>● Failed</b></span> — job error; check logs in the right-side diagnostics panel
<span style="color:#ABB3BF"><b>● Idle</b></span> — no input data; cluster running but not processing

**Stream monitoring view** (accessible from the output stream node or the stream resource page): displays throughput charts (records/sec), consumer lag, archive job status, partition count, and schema version. Alerts can be configured for lag thresholds.

**Streaming profiles** are applied per job group via the <span style="color:#8ABBFF">Build settings</span> panel: choose from default or custom named profiles that set parallelism, memory, and checkpoint interval.

---

## Worked example

**Scenario: Real-time IoT sensor ingestion and aggregation**

1. A factory floor publishes temperature readings to a Kafka topic `sensors.temp` at 500 msg/sec.
2. In **Data Connection**, a new Kafka source is created pointing to the broker. A streaming sync is configured with 4 consumer threads (one per Kafka partition), routed through an on-premises agent, with SSL authentication.
3. The sync begins immediately — records flow into a Foundry Stream called `raw_sensor_readings`. The hot buffer makes them available within milliseconds; the archive job persists them to cold storage every few minutes as a queryable dataset.
4. In **Pipeline Builder**, a new streaming pipeline is created:
   - **Input**: `raw_sensor_readings` stream
   - **Parse JSON** transform: unpacks the `value` column (Kafka payload) into typed columns (`device_id`, `temp_celsius`, `event_ts`).
   - **Key by** transform: keys on `device_id` so all readings for a device go to the same Flink operator.
   - **Stateful window aggregate** transform: computes a 60-second rolling average temperature per device.
   - **Output**: a new Stream `sensor_avg_60s`, also written to a dataset `sensor_averages` for historical querying.
5. The pipeline shows <span style="color:#238551"><b>● Running</b></span>. The stream preview page shows records arriving in the output with sub-second latency.
6. Downstream, a Foundry application subscribes to `sensor_avg_60s` to trigger alerts when any device average exceeds 85 °C.

---

## Documentation map

- **Core concepts**
  - [Streams](https://www.palantir.com/docs/foundry/data-integration/streams) — hot buffer, cold storage, archiving, per-row transactions, schema management
  - [Change data capture (CDC)](https://www.palantir.com/docs/foundry/data-integration/change-data-capture) — row-level CDC streaming into Foundry

- **Resource guides (Data connectivity &amp; integration)**
  - [Streaming](https://www.palantir.com/docs/foundry/data-integration/streaming-guide) — end-to-end streaming guide
  - [Flink fundamentals](https://www.palantir.com/docs/foundry/data-integration/flink-streaming) — Flink architecture, operators, state
  - [Reset stream](https://www.palantir.com/docs/foundry/data-integration/reset-stream) — replaying / clearing stream state
  - [Stream monitoring](https://www.palantir.com/docs/foundry/data-integration/stream-monitoring) — throughput, lag, archive job metrics
  - [Streaming profiles](https://www.palantir.com/docs/foundry/data-integration/streaming-profiles) — compute profile configuration

- **Building pipelines — Streaming pipelines**
  - [Overview](https://www.palantir.com/docs/foundry/building-pipelines/streaming-overview)
  - [Comparison: Streaming vs. batch](https://www.palantir.com/docs/foundry/building-pipelines/stream-vs-batch)
  - [Performance considerations](https://www.palantir.com/docs/foundry/building-pipelines/streaming-performance-considerations)
  - [Streaming compute usage](https://www.palantir.com/docs/foundry/building-pipelines/streaming-compute-usage)
  - [Keys](https://www.palantir.com/docs/foundry/building-pipelines/streaming-keys)
  - [Streaming stateful transforms](https://www.palantir.com/docs/foundry/building-pipelines/streaming-stateful-transforms)
  - [Create a streaming pipeline with Pipeline Builder](https://www.palantir.com/docs/foundry/building-pipelines/create-stream-pipeline-pb)

- **Data Connection**
  - [Set up a streaming sync](https://www.palantir.com/docs/foundry/data-connection/set-up-streaming-sync)
  - [Push data into a stream](https://www.palantir.com/docs/foundry/data-connection/push-based-ingestion)

- **Available connectors**
  - [Kafka](https://www.palantir.com/docs/foundry/available-connectors/kafka)
  - [Amazon Kinesis](https://www.palantir.com/docs/foundry/available-connectors/amazon-kinesis)

- **Product QAs**
  - [Streaming Q&amp;A](https://www.palantir.com/docs/foundry/questions-answers/streaming)

---

## Official documentation

- [Core concepts · Streams](https://www.palantir.com/docs/foundry/data-integration/streams)
- [Resource guides · Streaming](https://www.palantir.com/docs/foundry/data-integration/streaming-guide)
- [Building pipelines · Streaming pipelines · Overview](https://www.palantir.com/docs/foundry/building-pipelines/streaming-overview)
- [Building pipelines · Streaming stateful transforms](https://www.palantir.com/docs/foundry/building-pipelines/streaming-stateful-transforms)
- [Data Connection · Set up a streaming sync](https://www.palantir.com/docs/foundry/data-connection/set-up-streaming-sync)
- [Available connectors · Kafka](https://www.palantir.com/docs/foundry/available-connectors/kafka)
- [Building pipelines · Keys](https://www.palantir.com/docs/foundry/building-pipelines/streaming-keys)
- [Product QAs · Streaming](https://www.palantir.com/docs/foundry/questions-answers/streaming)
