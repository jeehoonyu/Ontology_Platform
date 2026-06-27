<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · APPLICATIONS</b><br>
<span style="font-size:22px"><b>Automate &amp; Autopilot</b></span><br>
<span style="color:#ABB3BF">Continuously evaluate Ontology conditions and execute effects automatically — then monitor those workflows at scale in a visual control center.</span>
</td></tr></table>

## What it is

**Automate** is Foundry's business automation application. It continuously evaluates conditions — time schedules, Ontology object changes, or both — and fires configurable effects (actions, AIP Logic functions, notifications, webhooks) whenever those conditions are satisfied. **Autopilot** is the companion control center (currently in beta) that layers on top of Automate to visualize, monitor, and debug the resulting automation workflows at scale through Kanban boards, dependency graphs, and detailed execution logs. Together they replace the legacy Object Monitors feature.

---

## How it works

### Automate: execution model

Every automation is a Foundry resource stored in a Compass folder. Each automation is composed of exactly one **condition block** and one or more **effect blocks**. The platform evaluates conditions continuously in the background; when a condition transitions from false to true, Automate fires the configured effects.

**1. Condition evaluation**

Conditions are evaluated against the live Ontology. There are two families:

- **Time-based conditions** — fire on a cron-like schedule (e.g., every Monday at 09:00). No object set is needed.
- **Object set conditions** — fire when a predefined Ontology object set changes. Three sub-types exist:
  - *Objects added to set* — a new object appears in the set.
  - *Objects removed from set* — an object leaves the set.
  - *Objects modified in set* — a property changes on an existing set member.
- **Combined conditions** — a time gate plus an object set condition used together (e.g., "every day, if there are open high-priority tickets").

Object-set conditions pick up data changes typically within minutes of the underlying dataset or action type writing new data.

**2. Effect execution**

When the condition fires, Automate runs all configured effect blocks. Supported effect types:

- **Action effects** — submit a Foundry Action Type against the Ontology. The action executes on behalf of the automation owner, who must satisfy the action's permission criteria. Multiple actions can be added; execution order is not guaranteed. Effect inputs (objects added/removed/modified) can be forwarded directly as action parameters, with three grouping modes: *once for all objects*, *once per batch* (configurable batch size), or *once per object group* (grouped by a property).
- **AIP Logic / Function effects** — invoke a Foundry Function or AIP Logic function, enabling AI-driven decision making inside the automation loop.
- **Notification effects** — send platform notifications or email (with PDF attachments from Notepad/Notepad templates). Recipients are defined as a static list of Foundry users/groups or resolved dynamically from object properties.
- **Fallback effects** — a secondary effect that fires if the primary effect fails.

**3. Error handling and retry**

Action effects support configurable retry policies: *constant backoff* (fixed wait between retries), *exponential backoff* (doubling wait), or *exponential with jitter* (randomized delay to avoid thundering-herd). Failures surface in the Overview page activity feed and in Autopilot's execution logs.

**4. Automation lifecycle**

Each automation has an **expiration policy**: indefinitely active, expire immediately after first run, or expire on a specific date. Automations run against the **automation owner's** permissions — transferring ownership changes whose credentials back the execution.

---

### Autopilot: visualization and monitoring layer

Autopilot reads the same automations and Ontology objects and renders them as a managed workflow. It does not change how automations execute; it adds observability and manual intervention capabilities on top.

**State inference** — Autopilot analyzes each automation's condition blocks and effect blocks to infer *states* (e.g., "Open", "In Progress", "Resolved"). States can also be defined manually. Each state has entry/exit conditions derived from the automations that move objects into or out of it.

**Workbench** — the primary UI surface, offering:
- *Kanban view* — one column per state; each card is an Ontology object. Cards move across columns as automations fire. Spinning icons in column headers indicate actively executing automations; animated indicators on cards show objects currently being processed.
- *Dependency graph view* — a node-link diagram of automations, action types, functions, and their relationships. Also shows the historical path a specific object has traveled through the workflow.
- Both views can be displayed side-by-side in split mode.

**Object Execution tab (experimental)** — full execution logs per object, traceable across all automations that touched it, with timestamps and attribution (automation, application, or human user).

---

## User interface

### Automate

The <span style="color:#8ABBFF">**Overview page**</span> is the landing screen. It shows:

- Recent activity feed (condition firings, effect completions, errors)
- Aggregate metrics: total automation count, recent execution counts, failure rates
- <span style="color:#2D72D2">**+ New automation**</span> button (top-right)

The **automation creation wizard** walks through four pages:

| Step | Panel | What you configure |
|------|-------|--------------------|
| 1 | <span style="color:#8ABBFF">Condition</span> | Time schedule and/or object set condition type |
| 2 | <span style="color:#8ABBFF">Effect</span> | Add notification, action, function, or fallback |
| 3 | <span style="color:#8ABBFF">Summary</span> | Review condensed condition + effect before saving |
| 4 | <span style="color:#8ABBFF">Settings</span> | Name, Compass save location, expiration policy, permissions |

The <span style="color:#2D72D2">**Automations tab**</span> lists all automations the user can access, with filters by type, status, and owner.

**Status chips used across Automate:**

<span style="color:#238551"><b>● active</b></span> &nbsp;·&nbsp; <span style="color:#C87619"><b>● pending / stale</b></span> &nbsp;·&nbsp; <span style="color:#CD4246"><b>● failed</b></span> &nbsp;·&nbsp; <span style="color:#ABB3BF"><b>● expired</b></span>

### Autopilot

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47;color:#8ABBFF"><b>Region</b></td>
<td style="padding:8px 12px;border:1px solid #383E47;color:#8ABBFF"><b>What you see</b></td>
</tr>
<tr style="background:#111418">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#ABB3BF">Left sidebar</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">States list — add, reorder (drag-and-drop), delete, zoom to state. Each state shows entry/exit condition summary.</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#ABB3BF">Top toolbar</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">View selector: Kanban / Graph / Split. Search objects with <code>Cmd+F</code> / <code>Ctrl+F</code>. Filter toggle for linked objects.</td>
</tr>
<tr style="background:#111418">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#ABB3BF">Kanban columns</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">One column per state. Column header shows <span style="color:#2D72D2"><b>spinning icon</b></span> when automation is actively running. Cards show object title + configurable Ontology properties.</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#ABB3BF">Object side panel</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Opens on card click. Shows full edit history, property changes over time, attribution (automation / app / user), and object metadata preview.</td>
</tr>
<tr style="background:#111418">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#ABB3BF">State config panel</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Opens on state click. Tabs: Definition (object type, entry/exit conditions), Display (column color/icon), Upstream/Downstream (last 100 transitions), Preview.</td>
</tr>
<tr style="background:#1C2127">
<td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#ABB3BF">Dependency graph</span></td>
<td style="padding:8px 12px;border:1px solid #383E47">Node-link diagram of automations, action types, and functions. Click an object to highlight its historical path through the graph.</td>
</tr>
</table>

Right-clicking a card exposes: filter workbench by this object, manually retry an automation, bulk-execute automations on selected objects, copy object title/properties.

---

## Worked example

**Scenario: Auto-escalate high-priority support tickets that have been open for more than 24 hours.**

1. A `SupportTicket` object type exists in the Ontology with properties `priority`, `status`, and `opened_at`.
2. In **Automate**, create a new automation with a **combined condition**: time trigger (every hour) + object set condition targeting the set `{ SupportTicket | priority = "high" AND status = "open" AND opened_at < now() - 24h }`.
3. Add an **Action effect**: select the `EscalateTicket` action type; map the "objects modified in set" effect input to the action's `ticket` parameter. Set grouping to *execute once per object* so each ticket is escalated independently.
4. Add a **Notification effect**: send an email to the on-call group with the ticket ID and link.
5. Set expiration to *Indefinitely*.
6. Save to the `Support Automations` Compass folder.
7. In **Autopilot**, open the workbench. Autopilot infers states: `Open`, `Escalated`, `Closed`. The Kanban board shows all open tickets as cards in the `Open` column. When the automation fires on a ticket, the card animates and moves to `Escalated`. The dependency graph shows the `EscalateTicket` action downstream of the automation node. Clicking a card opens the side panel showing the timestamp and attribution (`automate://support-escalation-rule`).

---

## Documentation map

Sub-pages that live beneath Automate and Autopilot in the Foundry docs:

**Automate**
- Overview
- Getting started
- Condition — Object set conditions
- Condition — Evaluation latency
- Effects — Action effects
- Effects — Notification effects
- Effects — Fallback effects
- Manual executions
- Performance and troubleshooting — Troubleshooting performance
- AIP Logic — Automate AIP Logic integration

**Autopilot**
- Overview
- Workbench
- Workbench — Dependency graph view
- Workbench — Kanban board view

---

## Official documentation

- [Automate — Overview](https://www.palantir.com/docs/foundry/automate/overview)
- [Automate — Getting started](https://www.palantir.com/docs/foundry/automate/getting-started)
- [Automate — Effects: Action effects](https://www.palantir.com/docs/foundry/automate/effect-actions)
- [Automate — Effects: Notification effects](https://www.palantir.com/docs/foundry/automate/effect-notification)
- [Automate — Condition: Object set conditions](https://www.palantir.com/docs/foundry/automate/condition-objects)
- [Automate — Effects: Fallback effects](https://www.palantir.com/docs/foundry/automate/effect-fallback)
- [Automate — Manual executions](https://www.palantir.com/docs/foundry/automate/manual-execution)
- [Automate — Condition: Evaluation latency](https://www.palantir.com/docs/foundry/automate/condition-evaluation-latency)
- [Autopilot — Overview](https://www.palantir.com/docs/foundry/autopilot/overview)
- [Autopilot — Workbench](https://www.palantir.com/docs/foundry/autopilot/workbench)
- [Autopilot — Workbench: Kanban board view](https://www.palantir.com/docs/foundry/autopilot/workbench-kanban)
- [Autopilot — Workbench: Dependency graph view](https://www.palantir.com/docs/foundry/autopilot/workbench-graph)
- [AIP Logic — Automate integration](https://www.palantir.com/docs/foundry/logic/aip-logic-integration-automate)
