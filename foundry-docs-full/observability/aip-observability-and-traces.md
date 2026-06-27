<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · OBSERVABILITY</b><br>
<span style="font-size:22px"><b>AIP Observability, Traces &amp; Metrics</b></span><br>
<span style="color:#ABB3BF">End-to-end visibility into AIP workflow executions via distributed traces, real-time metrics, structured logs, and 30-day execution history.</span>
</td></tr></table>

## What it is

AIP Observability is Foundry's built-in monitoring and debugging suite for AI-powered workflows. It surfaces execution history, distributed traces, service logs, and near real-time performance metrics for every Function, Action, Automation, and AIP Logic application running on the platform. The capability lives inside **Workflow Lineage** (opened with <kbd>Ctrl+I</kbd> / <kbd>⌘+I</kbd> from any Workshop app or Functions repository) and requires no additional instrumentation beyond writing normal Foundry code.

---

## How it works

AIP Observability is built around four layered data structures that Foundry generates automatically for every execution:

**1. Span collection (distributed tracing)**
When a workflow runs, Foundry's runtime wraps each logical operation — a Function call, an Action, an LLM prompt, an Ontology load, or an Automate step — in a **span**. A span records its operation name, start time, duration, input parameters, output values, and any error payload. Spans are linked by parent-child references so that a single user-triggered request (e.g., a Workshop button click) produces a tree of spans whose root is the top-level caller.

**2. Trace assembly**
All spans that share the same `foundryTraceId` (also exposed as `x-b3-traceid` for external correlation) are assembled into a **distributed trace** — the complete timeline from request initiation to response receipt. Traces cross service boundaries: an Action that calls a Function that calls an LLM model produces one unified trace rather than three isolated records.

**3. Metrics aggregation**
In parallel, Foundry aggregates span data into two time-series metrics per resource:
- **Success/failure counts** — binned in near real-time
- **P95 execution duration** — rolling 30-day window

These metrics are computed for Functions, Actions, and AIP Logic resources and exposed in Workflow Lineage without requiring any separate metric-collection pipeline.

**4. Log correlation**
Each span is associated with structured **service logs** — timestamped entries at `DEBUG`, `INFO`, `WARN`, `ERROR`, and `TRACE` levels, including any custom `print` or logging statements written in Python/Java function code. Logs are co-indexed with trace IDs so clicking into a span immediately surfaces its log stream, LLM prompt text, token counts, and stack traces.

**End-to-end data flow:**

1. A user (or Automation trigger) invokes a Function, Action, or AIP Logic workflow.
2. Foundry's runtime instruments the call, creating a root span with a fresh `foundryTraceId`.
3. Each downstream call (nested Functions, LLM requests, Ontology reads/writes) generates child spans attached to the same trace.
4. On completion or failure, all spans are flushed to the Foundry observability store.
5. Execution history records the top-level result (status, duration, caller, version) and is queryable for 30 days.
6. Metrics counters and P95 latency are updated near real-time in Workflow Lineage.
7. Administrators grant log-access permissions per project; users always retain access to their own executions for 24 hours.
8. Logs and traces can optionally be **exported to streaming datasets** for custom dashboards or external telemetry pipelines.

**Performance optimization path:** The trace waterfall reveals sequential operations that could be parallelized, unbatched LLM calls that could be grouped, and redundant Ontology loads — enabling data-driven refactoring before issues surface in production.

---

## User interface

AIP Observability is accessed via the **Workflow Lineage** panel. The UI has three main screens:

**Run History table** — the entry point. A filterable table showing every execution of the selected resource over 30 days.

<table style="border-collapse:collapse;background:#1C2127;border:1px solid #383E47;font-size:13px">
<thead><tr style="background:#252A31">
<th style="padding:8px 12px;color:#8ABBFF;border-bottom:1px solid #383E47">Column</th>
<th style="padding:8px 12px;color:#8ABBFF;border-bottom:1px solid #383E47">Content</th>
</tr></thead>
<tbody>
<tr><td style="padding:7px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Timestamp</td><td style="padding:7px 12px;color:#fff;border-bottom:1px solid #383E47">Completion time of the run</td></tr>
<tr><td style="padding:7px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Status</td><td style="padding:7px 12px;border-bottom:1px solid #383E47"><span style="color:#238551"><b>● success</b></span> &nbsp; <span style="color:#CD4246"><b>● failed</b></span></td></tr>
<tr><td style="padding:7px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Runtime</td><td style="padding:7px 12px;color:#fff;border-bottom:1px solid #383E47">Total wall-clock duration</td></tr>
<tr><td style="padding:7px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Caller</td><td style="padding:7px 12px;color:#fff;border-bottom:1px solid #383E47">Triggering resource (Workshop app, Agent, Automation, OSDK app, etc.)</td></tr>
<tr><td style="padding:7px 12px;color:#ABB3BF">Source executor</td><td style="padding:7px 12px;color:#fff">Top-level executable type in the call chain</td></tr>
</tbody>
</table>

Filters available: <span style="color:#8ABBFF">Status</span>, <span style="color:#8ABBFF">Date range</span>, <span style="color:#8ABBFF">User</span>, <span style="color:#8ABBFF">Duration range</span>, <span style="color:#8ABBFF">Function version</span>, <span style="color:#8ABBFF">Caller</span>, <span style="color:#8ABBFF">Failure type</span>. Multiple filters combine with AND logic.

**Trace view** — opened by clicking "View log details" on any row. The main area shows a **waterfall diagram**: horizontal bars representing each span's duration arranged top-to-bottom in call-stack order, with nested indentation showing parent-child relationships. The left panel lists all spans; clicking a span opens a right-side detail drawer showing:

- Operation name and type (<span style="color:#147EB3">Function</span> / <span style="color:#9D3F9D">Action</span> / <span style="color:#00A396">LLM call</span> / <span style="color:#D1980B">Automation</span>)
- Start time, duration
- Input parameters and returned outputs
- For LLM spans: full prompt text, model response, and token count breakdown
- Error message and stack trace (for failed spans)
- `foundryTraceId` and `x-b3-traceid` correlation identifiers

**Metrics panel** — accessed from the <span style="color:#2D72D2">Metrics</span> tab in Workflow Lineage. Displays two line charts per resource: request counts (success vs. failure) and P95 latency, both plotted over rolling 30-day windows. The **AIP usage tab** adds model-level breakdowns:

- <span style="color:#238551"><b>Successful</b></span> — completed model requests / tokens
- <span style="color:#C87619"><b>Attempted</b></span> — total attempts including rate-limited ones
- <span style="color:#CD4246"><b>Rate-limited</b></span> — requests blocked by capacity limits

Users can toggle between "Model requests" and "Token usage" views and hover over graph points for precise values per Workshop app, Automation, or OSDK application.

**Log search** — a cross-execution full-text search across all service logs for a given resource, supporting `INFO`/`WARN`/`ERROR` level filters and pattern matching. Results link directly back to the parent trace.

**Bulk model replacement** — the <span style="color:#2D72D2">Replace model</span> tab lets operators swap the underlying LLM across all AIP Logic functions in a project simultaneously, enabling mass migration without editing each function individually.

---

## Worked example

**Scenario:** An Agent that classifies customer support tickets is taking 8–12 seconds per request, causing user complaints.

1. Open Workflow Lineage with <kbd>Ctrl+I</kbd> from the Workshop app hosting the Agent.
2. Navigate to the `classifyTicket` Function and open the **Run history** tab.
3. Filter by `Status: success` and `Duration: > 5s` to isolate slow executions.
4. Click "View log details" on a 10-second run to open the **Trace view**.
5. The waterfall reveals three sequential LLM spans (`gpt-4o`) each taking ~3s, called one-by-one inside a Python `for` loop.
6. The detail drawer for each LLM span shows identical token counts (~200 prompt tokens), confirming unbatched calls to the same model.
7. The developer refactors the Function to issue all three calls concurrently using `asyncio.gather`.
8. After deploying, the Metrics panel shows P95 latency dropping from 10s to 3.5s within minutes of the next executions appearing in Run history.
9. Token usage in the AIP usage tab remains unchanged, confirming no regression in model consumption.

---

## Documentation map

The following sub-pages live beneath the AIP Observability section in Foundry docs:

- **Run history** — filtering and inspecting the 30-day execution log
- **Trace view** — waterfall diagram, span details, LLM prompt/response inspection
- **Service logs and debugging** — structured log levels, custom log messages, error stack traces
- **Log search** — cross-execution full-text search across all service logs
- **Log permissioning** — administrator controls for granting/revoking log access per project
- **Metrics** — success/failure counts and P95 latency per Function, Action, and AIP Logic resource
- **Performance monitoring and optimization** — identifying bottlenecks, concurrent execution patterns, batching strategies
- **AIP usage metrics** (Workflow Lineage) — model request counts, token usage, rate-limit tracking, bulk model replacement

Adjacent observability tooling referenced from these pages:

- **Data Health** — scope-based monitoring rules, health checks, PagerDuty/Slack/webhook alerting
- **Workflow Lineage** — broader platform lineage, dependency graphs, and pipeline history
- **AIP Evals** — structured evaluation of LLM output quality (separate from runtime tracing)

---

## Official documentation

- [Overview · Observability · Palantir](https://www.palantir.com/docs/foundry/observability/overview)
- [AIP observability · Overview · Palantir](https://www.palantir.com/docs/foundry/aip-observability/overview)
- [AIP observability · Trace view · Palantir](https://www.palantir.com/docs/foundry/aip-observability/trace-view)
- [AIP observability · Execution history · Palantir](https://www.palantir.com/docs/foundry/aip-observability/run-history)
- [AIP observability · Performance monitoring and optimization · Palantir](https://www.palantir.com/docs/foundry/aip-observability/performance-monitoring-and-optimization)
- [AIP observability · Logging and debugging · Palantir](https://www.palantir.com/docs/foundry/aip-observability/service-logs-and-debugging)
- [Workflow Lineage · AIP usage metrics and observability · Palantir](https://www.palantir.com/docs/foundry/workflow-lineage/aip-usage-observability)
