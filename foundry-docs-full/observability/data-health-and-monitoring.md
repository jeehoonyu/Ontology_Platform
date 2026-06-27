<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · OBSERVABILITY</b><br>
<span style="font-size:22px"><b>Data Health &amp; Monitoring</b></span><br>
<span style="color:#ABB3BF">Rule-based platform-wide observability that tracks dataset freshness, build status, and resource health — alerting teams before failures reach production.</span>
</td></tr></table>

## What it is

Data Health & Monitoring is Palantir Foundry's built-in observability layer for detecting and surfacing issues across datasets, schedules, streaming datasets, functions, actions, object types, and more. It provides two complementary systems — **Health Checks** (per-resource content and schema validation) and **Monitoring Views** (scope-based rules that scale automatically as resources are added) — surfaced through a dedicated **Data Health** application and integrated directly into Data Lineage and Dataset Preview. Alerts are routed through in-platform notifications, email digests, or external channels including PagerDuty, Slack, and webhooks.

---

## How it works

### Building blocks

| Object | Description |
|---|---|
| **Health Check** | A single validation rule attached to one dataset, schedule, or table. Stores a history of pass/fail results. |
| **Monitoring View** | A named collection of monitoring rules and health checks scoped to a project, folder, application, or individual resource. |
| **Monitoring Rule** | Within a Monitoring View: a typed rule (e.g. "Dataset freshness", "Schedule status") with configurable thresholds and alert severity. |
| **Scope** | Static (a specific named resource) or Dynamic (folder, project, Workflow Lineage, Workshop, or OSDK application — auto-updates as resources are added or removed). |
| **Alert** | A fired notification when a check or rule crosses its configured threshold. Carries severity: low, medium, or high. |

### Execution and data-flow — step by step

1. **Triggering.** Health Checks are event-driven: a *Job Status* check fires every time the monitored dataset is refreshed; a *Schedule Status* check fires each time the configured schedule runs. Freshness checks run continuously or on a schedule to compare the current clock against the dataset's last transaction timestamp or a designated timestamp column.

2. **Evaluation.** For each trigger event Foundry evaluates the check predicate against the resource's metadata (transaction log, build log, row counts, schema snapshot, or column values). Code-based checks written in Python (via `data-expectations` in Code Repository) are evaluated at build time and can abort the build on failure.

3. **Result recording.** Each evaluation produces a timestamped pass/fail result appended to the check's **historic result log**, visible in the Health tab of Dataset Preview and in Data Lineage under Metrics > Health. Foundry retains 30 days of execution and performance metrics.

4. **Alert generation.** When a check transitions from passing to failing (or a Monitoring Rule threshold is crossed), Foundry generates an alert. The alert is tagged with the rule name, resource RID, failure reason, severity, and timestamp.

5. **Alert routing.** Subscribers receive alerts via:
   - Foundry in-platform notifications (any user with Viewer permissions on the Monitoring View)
   - Email digest summaries
   - External integrations: PagerDuty, Slack, or a configurable REST webhook endpoint

6. **Alert suppression.** Individual alerts or entire rules can be **snoozed** (with a configurable duration and reason) to suppress noise during planned outages or known incidents.

7. **Lineage integration.** Data Lineage renders each dataset node with a color-coded health badge derived from the latest check result, giving pipeline owners at-a-glance status across the full DAG without opening the Data Health application.

### Check types reference

| Check | Scope | What it validates |
|---|---|---|
| **Job Status** | Dataset | The build for this specific output dataset completed successfully |
| **Schedule Status** | Schedule | The full schedule run (all intermediate datasets) completed |
| **Schedule Duration** | Schedule | Build duration stayed within expected bounds |
| **Time Since Last Updated** | Dataset | Elapsed time since last transaction (including empty transactions) is within threshold |
| **Data Freshness** | Dataset | Last transaction timestamp vs. max value in a designated timestamp column |
| **Sync Freshness** | Synced dataset | Latest sync time vs. max datetime column value |
| **Content / Schema** | Dataset, Table | Row count ranges, column presence, null rates, value distributions |
| **Data Expectations (code)** | Dataset (Code Repo) | Python-defined assertions evaluated at build time; failures abort the build |

---

## User interface

The <span style="color:#8ABBFF">**Data Health**</span> application is accessible from the Foundry main sidebar. It is the primary hub for both authoring and triaging.

### Application layout

```
┌──────────────────────────────────────────────────────────┐  background #111418
│  Sidebar: Monitoring Views | Health Checks | Debugging   │  panel #1C2127
├────────────────┬─────────────────────────────────────────┤
│  Resource list │  Detail / editor panel                  │  raised #252A31
│  (filterable)  │  Tabs: Manage monitors | Subscriptions  │
│                │        Troubleshoot alerts              │
└────────────────┴─────────────────────────────────────────┘
```

**Top-level tabs inside a Monitoring View:**

- <span style="color:#2D72D2">**Manage monitors**</span> — add/edit rules, set metric thresholds, assign severity
- <span style="color:#2D72D2">**Manage subscriptions**</span> — subscribe users or external channels
- <span style="color:#2D72D2">**Troubleshoot alerts**</span> — filter fired alerts by name, resource, failure reason, timestamp; snooze individual alerts

**Health tab (Dataset Preview):** Directly accessible on any dataset. Shows the list of checks attached to that resource, each displaying its latest evaluation result and a sparkline of recent history.

**Data Lineage (Metrics > Health):** Schedule-level checks are configured and viewed here; dataset nodes in the DAG show color-coded health badges.

### Status chips

<table><tr>
<td style="background:#1C2127;padding:10px 16px;border:1px solid #383E47;border-radius:4px">
<span style="color:#238551"><b>● Passing</b></span> &nbsp;&nbsp;
<span style="color:#CD4246"><b>● Failing</b></span> &nbsp;&nbsp;
<span style="color:#C87619"><b>● Stale / Warning</b></span> &nbsp;&nbsp;
<span style="color:#ABB3BF"><b>● Not evaluated</b></span> &nbsp;&nbsp;
<span style="color:#2D72D2"><b>● Primary action</b></span>
</td></tr></table>

**What you see — key UI elements:**

| Element | Location | Color / style |
|---|---|---|
| Resource health badge | Data Lineage node | <span style="color:#238551">Green</span> / <span style="color:#CD4246">Red</span> dot on dataset tile |
| Check history sparkline | Dataset Preview > Health tab | Miniature bar chart, bar color maps to result state |
| Alert severity badge | Troubleshoot alerts tab | <span style="color:#CD4246">High</span> · <span style="color:#C87619">Medium</span> · <span style="color:#ABB3BF">Low</span> |
| Snooze button | Per-alert row | <span style="color:#2D72D2">Blue</span> action button; opens duration picker |
| Dynamic scope indicator | Monitoring Rule editor | <span style="color:#8ABBFF">Auto-updates</span> label shown when folder/project scope selected |

---

## Worked example

**Scenario:** A nightly ETL schedule ingests sensor data into a dataset `sensor_readings`. The data team wants to know immediately if the schedule takes longer than 45 minutes or if the most recent row timestamp is more than 2 hours behind real time.

1. **Create a Monitoring View** called `Sensor Pipeline Health` in the Data Health application. Set scope to the project containing the pipeline.
2. **Add a Schedule Status rule** targeting the `sensor_readings` schedule. Set severity to **High** so on-call receives a PagerDuty page.
3. **Add a Schedule Duration rule** with a threshold of 45 minutes. Set severity to **Medium** (email notification).
4. **Add a Data Freshness health check** on the `sensor_readings` dataset. Configure it to compare `ingestion_timestamp` column max value against the current clock, with a 2-hour tolerance.
5. **Subscribe** the on-call Slack channel as an external integration on the Monitoring View.
6. That evening the schedule runs but one upstream job hangs. After 48 minutes the Schedule Duration rule fires — Slack receives an alert. After 90 minutes the Schedule Status rule fires — PagerDuty pages the on-call engineer. The Data Freshness check fires at the next evaluation window, turning the dataset node <span style="color:#CD4246">**red**</span> in Data Lineage, where teammates can immediately see the scope of impact across downstream consumers.

---

## Documentation map

The following sub-pages sit beneath Data Health & Monitoring in the Foundry docs:

- **Data Health > Overview** — entry point; describes both Health Checks and Monitoring Views
- **Health Checks > Overview** — configuring checks on datasets, schedules, and tables
- **Health Checks > Types of checks** — full reference for every check predicate and its parameters
- **Health Checks > Check evaluation** — trigger mechanics and result lifecycle
- **Health Checks > Watching resources** — subscribing to individual check results
- **Health Checks > Notifications** — alert delivery channels and email digest settings
- **Health Checks > Marketplace integration** — using Marketplace products with health checks
- **Monitoring Views > Overview / Introduction** — scope types, creation workflow, rule configuration
- **Monitoring Views > Rules reference** — all rule types, threshold options, severity levels
- **Monitoring Views > Check groups [Sunset]** — legacy predecessor to Monitoring Views
- **Maintaining Pipelines > Recommended health checks** — best-practice guide
- **Transforms Python > Data expectations (getting started)** — code-based checks in Code Repository
- **Pipeline Builder > Configure data health checks** — configuring checks from Pipeline Builder
- **Observability > Overview** — umbrella page covering Monitoring, Debugging, Tracing, and Analysis pillars
- **Observability > Data Health** — Data Health as one of the four Observability pillars

---

## Official documentation

- [Data Health · Overview](https://www.palantir.com/docs/foundry/data-health/overview)
- [Observability · Overview](https://www.palantir.com/docs/foundry/observability/overview)
- [Health Checks · Overview](https://www.palantir.com/docs/foundry/health-checks/overview)
- [Health Checks · Types of checks](https://palantir.com/docs/foundry/data-health/check-types/)
- [Monitoring Views · Overview (Maintaining Pipelines)](https://www.palantir.com/docs/foundry/maintaining-pipelines/monitoring-views-intro/)
- [Observability · Data Health application](https://www.palantir.com/docs/foundry/observability/data-health)
- [Health Checks · Core concepts (Data Integration)](https://www.palantir.com/docs/foundry/data-integration/health-checks)
