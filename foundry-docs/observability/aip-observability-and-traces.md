# AIP Observability, Traces & Metrics

> AIP observability gives you visibility into the runtime behavior of Functions, Actions, AIP Logic, agents, streams, and compute modules — through trace views, metrics, and searchable logs.

## What it is

Data Health watches datasets and pipelines; AIP observability watches **logic and AI workflows**. When a Function errors, an AIP Logic call is slow, or an agent behaves unexpectedly, observability tools let you see exactly what happened. **Trace views** visualize a request's journey across Functions, Actions, and LLM calls with timing; **metrics** show near-real-time success/failure counts and durations; **log search/export** lets you find specific errors across all executions and ship telemetry externally.

## When to use it

- Debugging slow or failing Functions, Actions, or AIP Logic/agents.
- Understanding how an AI workflow traverses multiple tools/LLM calls.
- Tracking success rates, latency, and error patterns over time.
- Exporting logs/metrics/traces to an external monitoring system.

**When NOT to use it / alternatives:** For dataset freshness/build monitoring use **Data Health**; for dependency mapping use **Data Lineage**.

## Key concepts & terminology

- **Trace** — The end-to-end record of one request across functions/actions/LLM calls.
- **Span** — A single step within a trace, with its own timing.
- **Metric** — Aggregate counts/durations (success/failure, latency).
- **Log search** — Querying execution logs for messages/errors/patterns.
- **Log export** — Streaming telemetry (logs, metrics, traces) out for external analysis.
- **Workflow lineage / history** — Recent execution history for exploration.

## Core capabilities / features

- **Trace views** — Visualize request journeys across Functions, Actions, and LLM calls with performance detail.
- **Metrics** — Near-real-time success/failure counts and durations for Functions, Actions, AIP Logic, streams, and compute modules.
- **Log search** — Search across all executions for specific messages or errors.
- **Log export** — Create a telemetry stream for third-party/external analysis.
- **AIP-specific insights** — Visibility into agents, LLM calls, automations, and Ontology workflows.
- **Execution history** — Explore recent runs to diagnose intermittent issues.

## How it works / typical workflow

1. Run a Function/Action/AIP Logic/agent workflow.
2. **Open trace views** to see the request path and per-span timing.
3. **Inspect metrics** for success rates and latency trends.
4. **Search logs** for the specific error or message.
5. **Export telemetry** to an external system if needed.
6. Fix the issue and confirm via metrics/traces.

## Example

An AIP agent intermittently returns errors. You open a **trace**, see the request fan out to an Object Query tool, a Function, and an LLM call, and notice the Function span is failing on null input. **Log search** confirms a `NullPointerException`. You patch the Function and watch the **metric** success rate climb back to 100%.

## How it connects to the rest of Foundry

- **AIP Logic / Agent Studio** — Primary subjects of AIP observability.
- **Functions / Actions** — Traced and measured end to end.
- **Streams / Compute Modules** — Metrics cover their execution.
- **Data Health** — Complementary monitoring for data pipelines.
- **External SIEM/monitoring** — Log export integrates with outside tools.

## Tips & gotchas for learners

- **Traces show the path; metrics show the trend; logs show the detail** — use all three.
- **Instrument early** — observability is hardest to add after something breaks in prod.
- **Watch latency on LLM calls** — they're often the slowest spans in AI workflows.
- **Export telemetry** if your org standardizes monitoring outside Foundry.

## Official documentation

- [Observability: Overview](https://www.palantir.com/docs/foundry/observability/overview)
- [AIP: Overview](https://www.palantir.com/docs/foundry/aip/overview)
