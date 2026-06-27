<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Schedules &amp; Builds</b></span><br>
<span style="color:#ABB3BF">Automate recurring pipeline execution by attaching trigger-driven build schedules to any set of output datasets.</span>
</td></tr></table>

## What it is

**Builds** and **Schedules** are the core execution and automation primitives in Foundry's data pipeline system. A **build** is a one-time, system-orchestrated computation that brings a set of output datasets up-to-date; it is composed of one or more **jobs**, each defined by a **JobSpec** that encodes the transformation logic for one or more outputs. A **schedule** wraps a build in a recurring trigger — either time-based or event-based — so that pipelines keep running continuously without manual intervention.

Together they form the end-to-end mechanism by which raw source data flows through transforms and arrives as fresh, queryable datasets for analysts, Ontology objects, and downstream applications.

---

## How it works

### Builds

1. **JobSpec publication.** When a data engineer commits or saves transformation logic in a Code Repository, Pipeline Builder, or another authoring tool, Foundry publishes a **JobSpec** — an immutable definition of what inputs feed into which outputs and the logic that connects them. JobSpecs are versioned; each commit produces a new JobSpec version.

2. **Build initiation.** A build can be started manually ("Run now"), triggered by a schedule, or called via the Orchestration API. The caller specifies a set of **target datasets** (the leaves of the dependency graph to build toward) and optional parameters.

3. **Resolution step.** Before any computation begins, the build system inspects every JobSpec in the upstream dependency tree. It compares the current input dataset transactions and the current JobSpec version against what was present when each output was last built.
   - An output is **fresh** if neither its upstream inputs nor its JobSpec have changed — it is skipped entirely.
   - An output is **stale** if any input has a newer transaction or the JobSpec has changed — it is queued for computation.
   - A **force build** overrides this check and recomputes every output regardless of freshness.

4. **Job graph construction.** The stale jobs are arranged into a directed acyclic execution graph respecting dependency order. Jobs whose inputs are all fresh or already completed can begin immediately; others wait.

5. **Job execution states.** Each job moves through a lifecycle:
   - **WAITING** — dependencies not yet satisfied.
   - **RUN_PENDING** — queued, awaiting an available execution environment (Spark cluster, container, etc.).
   - **RUNNING** — actively computing.
   - **COMPLETED** — outputs written and transaction committed to the dataset catalog.
   - **FAILED** — computation error; retries (if configured) are attempted within the same build.

6. **Output commit.** When a job completes successfully, Foundry commits a new **transaction** to each output dataset, making the new rows/schema version visible to readers. The dataset's "last updated" timestamp advances, which in turn can satisfy downstream dataset-update triggers.

7. **Build completion.** The build is marked **Succeeded** when all targeted jobs reach COMPLETED. It is **Failed** if any job exhausts its retries. Individual job failures can be configured to abort the entire build or allow remaining independent branches to continue (`abortOnFailure` policy).

### Schedules

A schedule is a persistent resource that owns a **trigger** and a **build specification** (the target datasets and build parameters). The schedule engine evaluates triggers continuously and fires a build whenever conditions are met.

**Trigger types:**

| Trigger | Condition |
|---|---|
| **Time trigger** | A cron expression + timezone; satisfied each time the wall-clock matches the expression. |
| **Dataset update trigger** | Satisfied when one or more specified datasets receive a new committed transaction. |
| **Combined/compound** | Logical AND/OR combinations of the above, e.g. "only run after dataset X updates AND it is after 02:00 UTC". |

When a trigger fires, the schedule engine attempts to start the associated build. If the resolution step determines all targets are already fresh, the schedule run is recorded as **Ignored** (no build created, nothing was stale). This prevents redundant computation when source data has not actually changed.

**Pause/resume semantics.** Pausing a schedule resets its trigger state — all observed events since the last run are forgotten. When the schedule is resumed, it begins watching for new events from that moment forward; it does not "catch up" on events that occurred while paused.

**Retry configuration.** Failed jobs can be retried a configurable number of times within the same build. A job is not marked FAILED until all retry attempts are exhausted or an unretriable error type is encountered.

---

## User interface

### Build Schedules application

The <span style="color:#8ABBFF">**Build Schedules**</span> application is accessible from the Foundry navigation sidebar under <span style="color:#ABB3BF">Apps</span>. It lists all schedules visible to the current user.

**Main list view** — a table where each row is one schedule. Key columns:

<table style="background:#1C2127;border:1px solid #383E47;border-collapse:collapse;width:100%">
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px;color:#8ABBFF"><b>Column</b></td>
  <td style="padding:8px 12px;color:#8ABBFF"><b>What it shows</b></td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px;color:#fff">Schedule name</td>
  <td style="padding:8px 12px;color:#ABB3BF">Human-readable label; links to the detail page</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px;color:#fff">Status</td>
  <td style="padding:8px 12px"><span style="color:#238551"><b>● Active</b></span> &nbsp;|&nbsp; <span style="color:#ABB3BF"><b>● Paused</b></span></td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px;color:#fff">Last run</td>
  <td style="padding:8px 12px;color:#ABB3BF">Timestamp of most recent trigger evaluation</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#fff">Recent runs</td>
  <td style="padding:8px 12px;color:#ABB3BF">Row of colored dots (most recent on the right); hover to see run outcome</td>
</tr>
</table>

**Run outcome dots:**
<span style="color:#238551"><b>● succeeded</b></span> &nbsp;·&nbsp; <span style="color:#ABB3BF"><b>● ignored</b></span> &nbsp;·&nbsp; <span style="color:#CD4246"><b>● failed</b></span> &nbsp;·&nbsp; <span style="color:#C87619"><b>● pending / building</b></span>

Clicking a dot opens the **Build Report** for that run.

---

### Schedule detail page

Opening a schedule shows three main panels arranged under a dark <span style="color:#111418">app background</span>:

- **<span style="color:#8ABBFF">Overview panel</span>** (top): schedule name, trigger definition (human-readable cron or event description), next predicted run time, and action buttons: <span style="color:#2D72D2">**Run now**</span>, <span style="color:#C87619">**Pause**</span>, **Edit**, **Delete**.

- **<span style="color:#8ABBFF">Run History tab</span>**: a chronological log of every trigger evaluation. Each row shows timestamp, run type (time vs. event), outcome (Succeeded / Ignored / Failed), and a link to the associated build. Selecting an Ignored row displays the reason (e.g. "All target datasets were up-to-date").

- **<span style="color:#8ABBFF">Metrics tab</span>**: charts showing build duration trends, failure rates, and dataset freshness over time. Use this to detect regressions in pipeline performance.

---

### Schedule editor

Reached via **Edit** on a detail page, or **Create new schedule** from Data Lineage or Pipeline Builder. Layout:

- **Trigger section**: radio buttons for <span style="color:#2D72D2">**Time**</span> vs. <span style="color:#2D72D2">**Dataset update**</span>. For time triggers, a visual picker covers common presets (hourly, daily, weekly); a toggle exposes the raw **cron expression** field and a timezone selector. For dataset-update triggers, a dataset search picker is shown.
- **Build targets section**: lists the output datasets the schedule will build toward. Datasets are selected from the project's resource tree.
- **Advanced options**: retry count per job, force-build toggle, parameterization key-value pairs.

---

### Data Lineage integration

In the <span style="color:#8ABBFF">Data Lineage</span> graph view, right-clicking any dataset node and choosing **Manage schedules…** opens a sidebar pane showing all schedules that cover that dataset. Selecting a schedule highlights the full set of JobSpecs it will build in the graph — giving an at-a-glance view of the pipeline scope. The <span style="color:#2D72D2">**Create new schedule**</span> button from this pane launches the schedule editor pre-populated with the selected dataset as the build target.

---

## Worked example

**Scenario:** A daily ETL pipeline ingests raw flight-delay CSV files from an external source, joins them with an airport reference table, and produces a `flights_cleaned` dataset consumed by an Ontology object type.

1. A data engineer authors the join transform in a Code Repository and merges to `main`. Foundry publishes a new **JobSpec** for `flights_cleaned`.

2. The engineer opens **Data Lineage**, right-clicks `flights_cleaned`, and chooses **Manage schedules → Create new schedule**.

3. In the schedule editor, they select **Dataset update** as the trigger and point it at the `raw_flight_data` dataset (the external connector writes here each morning). They set retry count to 2 and save.

4. The next morning the connector commits new rows to `raw_flight_data`. The schedule engine detects the new transaction and fires.

5. The **resolution step** checks `flights_cleaned`: its upstream input `raw_flight_data` has a newer transaction — it is **stale**. The `airport_reference` table has not changed — it is **fresh** and will not be recomputed.

6. A build is created. The `flights_cleaned` job moves WAITING → RUN_PENDING → RUNNING → COMPLETED. A new transaction is committed to `flights_cleaned`.

7. The schedule run is recorded as <span style="color:#238551">**● succeeded**</span>. The colored dot appears in the run history row. Downstream Ontology objects automatically reflect the updated dataset.

8. The following morning the connector fails to deliver new data. `raw_flight_data` is not updated. The trigger fires at the usual time but the resolution step finds `flights_cleaned` **fresh** — the run is recorded as <span style="color:#ABB3BF">**● ignored**</span> with reason "No stale job specs found."

---

## Documentation map

Sub-pages that live beneath Schedules &amp; Builds in the Foundry docs:

- **Core concepts / Schedules** — definition of schedules, triggers, run states, pause/resume semantics
- **Core concepts / Builds** — definition of builds, jobs, JobSpecs, staleness/freshness, force builds
- **Building pipelines / Scheduling / Overview** — scheduling within the pipeline authoring workflow
- **Building pipelines / Scheduling / Create a schedule** — step-by-step schedule creation UI walkthrough
- **Building pipelines / Scheduling / View and modify schedules** — editing, pausing, deleting schedules
- **Building pipelines / Scheduling / Find and manage schedules** — cross-project schedule discovery
- **Building pipelines / Scheduling / Common scheduling configurations** — pre-built patterns (hourly, daily, on-dataset-update)
- **Building pipelines / Scheduling / Trigger types reference** — full reference for time, dataset-update, and compound triggers; cron syntax
- **Building pipelines / Scheduling / Parameterization** — passing dynamic values to scheduled builds
- **Building pipelines / Scheduling / Troubleshooting reference** — diagnosing ignored runs, failed jobs, resource contention
- **Building pipelines / Best practices / Scheduling best practices** — avoiding thundering-herd, staggering cron times
- **Pipeline Builder / Schedules / Overview** — schedules within the Pipeline Builder visual editor
- **Pipeline Builder / Schedules / Create a schedule with AIP** — AI-assisted schedule creation
- **Data Lineage / Manage schedules** — managing schedules from the lineage graph
- **Optimizing pipelines / Troubleshooting schedules** — advanced debugging via metrics page
- **Dynamic Scheduling / Overview** — programmatic/dynamic schedule generation
- **API Reference / Orchestration v2 / Schedules** — REST API: create, get, run, delete schedules

---

## Official documentation

- [Core concepts · Schedules](https://www.palantir.com/docs/foundry/data-integration/schedules)
- [Core concepts · Builds](https://www.palantir.com/docs/foundry/data-integration/builds)
- [Building pipelines · Create a schedule](https://www.palantir.com/docs/foundry/building-pipelines/create-schedule)
- [Building pipelines · View and modify schedules](https://www.palantir.com/docs/foundry/building-pipelines/view-modify-schedules)
- [Building pipelines · Find and manage schedules](https://www.palantir.com/docs/foundry/building-pipelines/find-manage-schedules)
- [Building pipelines · Trigger types reference](https://www.palantir.com/docs/foundry/building-pipelines/triggers-reference)
- [Building pipelines · Common scheduling configurations](https://www.palantir.com/docs/foundry/building-pipelines/common-schedules)
- [Building pipelines · Scheduling best practices](https://www.palantir.com/docs/foundry/building-pipelines/scheduling-best-practices)
- [Building pipelines · Troubleshooting reference](https://www.palantir.com/docs/foundry/building-pipelines/schedule-troubleshooting)
- [Building pipelines · Parameterization](https://www.palantir.com/docs/foundry/building-pipelines/parameterization)
- [Pipeline Builder · Schedules overview](https://www.palantir.com/docs/foundry/pipeline-builder/schedules-overview)
- [Pipeline Builder · Create a schedule with AIP](https://www.palantir.com/docs/foundry/pipeline-builder/schedules-scheduler-aip)
- [Data Lineage · Manage schedules](https://www.palantir.com/docs/foundry/data-lineage/manage-schedules)
- [Optimizing pipelines · Troubleshoot schedules](https://www.palantir.com/docs/foundry/optimizing-pipelines/troubleshoot-schedules)
- [Dynamic Scheduling · Overview](https://www.palantir.com/docs/foundry/dynamic-scheduling/scheduling-overview)
- [API Reference · Get Schedule](https://www.palantir.com/docs/foundry/api/orchestration-v2-resources/schedules/get-schedule)
- [API Reference · Run Schedule](https://www.palantir.com/docs/foundry/api/orchestration-v2-resources/schedules/run-schedule)
